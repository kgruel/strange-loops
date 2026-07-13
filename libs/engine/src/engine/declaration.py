"""Store-backed declaration resolver — the file dissolves to locator + ingress.

SPEC §9.5: a store is the canonical residence of its vertex declaration. The
``.vertex`` file survives as two things and no more — a **locator** (its
``store`` field says where the store lives) and an **ingress form** (the human
edit surface, and the pre-genesis fallback). Once a store's lineage is opened
(a ``_decl.genesis`` event exists), "a file that does persist is a cache of a
fold head, never an authority."

This module is that authority's read half. It reconstructs the same
``VertexFile`` AST the parser returns — so every downstream consumer (compiler,
vertex_reader, emit checks, signing) is untouched in type terms — from the
store's declaration events instead of from the file text.

The seam is :func:`load_declaration`. The fold is
:func:`resolve_declaration_documents`. Both are protocol surface the loops-go
conformance oracle mirrors, so the rules here are explicit over clever.

Resolution contract (SPEC §9.2 Lineage, §9.5):

- **Genesis is identity, not fold state.** A store's lineage is opened exactly
  once; the genesis event carries the whole initial document set as its
  payload. Genesis is NOT resolved by Latest — its documents are the base the
  overlay is applied on top of. **Which genesis is self is recorded outside
  the fact stream**: the ``store_meta`` table's ``own_lineage`` row, stamped
  by ``absorb_genesis`` in the same transaction that mints the genesis. Merge
  copies facts, never meta — so foreign genesis rows arrive as inert citizens
  and can never hijack identity. Resolution selects the genesis row whose id
  equals the marker; a marker whose row is missing is corruption
  (:class:`DeclarationResolutionError`). Compat for stores absorbed before the
  marker existed: no marker + exactly one genesis row → that row is self (the
  next write ceremony backfills the marker); no marker + several rows →
  :class:`AmbiguousLineage` (refuse rather than guess).

- **Self-lineage scoping from day one.** Merge already carries arbitrary fact
  rows across stores today, so a foreign store's declaration events can be
  physically present. Every overlay/tombstone row must carry
  ``lineage == <this store's genesis id>`` in its payload to participate; rows
  with a foreign or absent lineage are **inert** — read, counted, never folded.

- **Fail closed on protocol.** A genesis whose ``protocol`` exceeds
  :data:`~lang.document.DECLARATION_PROTOCOL_VERSION` is refused entirely
  (:class:`UnsupportedProtocol`) — never partially interpreted.

- **Overlay is Latest per (kind, subject), replay-ordered.** Non-genesis
  ``_decl.*-defined`` rows overlay the genesis document set; the store's replay
  order is ``ORDER BY ts, id`` (see ``SqliteStore.since``), so later-by-(ts, id)
  wins. ``_decl.*-retired``/``-removed`` rows are subject tombstones. Unknown
  ``_decl.*`` kinds (receipts, future protocol) are skipped safely.

- **Same-``ts`` tie-break: an edit is in force at its own ``ts``, inclusive.**
  The ``as_of`` cutoff is ``_ts <= as_of`` (a declaration edit at ``ts == as_of``
  participates), matching ``StoreReader.facts_between``'s inclusive upper bound
  (``ts <= until_ts``). With the equal-cursors default (``as_of = until_ts``,
  SPEC §9.3), the consequence is deterministic and explicit: **when a fact and a
  declaration edit share an exact float ``ts``, the fact folds under the NEW
  ontology** — the edit wins its own instant, regardless of physical append
  order. The tie-break is purely ``ts``-based (not witness/rowid order), so it is
  reproducible across runs and across a ``rebuild(dump(S))`` that reassigns
  rowids. Witness-order ("as of" the fact cursor) is the finer axis SPEC §9.4
  grounds fact-residence on; it is deferred (Q1) until a fact-cursor read surface
  exists — until then ``ts`` with this inclusive tie-break is the single axis.

NOTE (provisional, pre-S4): no edit ceremony exists yet, so today only
genesis-only stores occur in practice. The overlay/tombstone fold is
nonetheless built and tested against hand-constructed rows, because it is
protocol and because self-lineage scoping must be correct on arrival. The
overlay-row *payload shape* this reader consumes —
``{"lineage": <genesis id>, "subject": <str>, "payload": <document payload>}``
for a ``*-defined`` row and ``{"lineage": <genesis id>, "subject": <str>}`` for
a tombstone — is the provisional contract S4's edit ceremony must emit; S4 may
refine it, in which case this reader moves with it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from lang.document import (
    DECL_GENESIS,
    DECL_LENS_DEFINED,
    DECL_VERTEX_DEFINED,
    DECLARATION_PROTOCOL_VERSION,
    DEFINED_TO_TOMBSTONE,
    documents_to_vertex,
    is_internal_kind,
)

# ---------------------------------------------------------------------------
# Tombstone vocabulary: which "*-defined" subject a "*-retired/-removed" row
# removes. The forward mapping is the frozen vocabulary home in lang.document
# (DEFINED_TO_TOMBSTONE); this is its inverse. Lens and the vertex singleton
# have no tombstone — a lens is replaced by re-definition, and the
# vertex-defined singleton IS the identity.
# ---------------------------------------------------------------------------

_TOMBSTONE_OF_DEFINED: dict[str, str] = {v: k for k, v in DEFINED_TO_TOMBSTONE.items()}

#: The "*-defined" declaration kinds an overlay row may (re)define — the
#: tombstonable subjects plus the two singletons (lens, vertex) that are
#: replaced by re-definition and have no tombstone.
_DEFINED_KINDS: frozenset[str] = frozenset(_TOMBSTONE_OF_DEFINED.values()) | {
    DECL_LENS_DEFINED,
    DECL_VERTEX_DEFINED,
}


class DeclarationResolutionError(Exception):
    """Base for store-declaration resolution failures (fail-closed conditions)."""


class AmbiguousLineage(DeclarationResolutionError):
    """No ``own_lineage`` marker and more than one ``_decl.genesis`` row.

    Without the store-local marker (stores absorbed before it existed) a store
    cannot tell its own genesis from a merged-foreign one, so several genesis
    rows make the store's own lineage indeterminate. Conservative refusal, not
    last-write-wins — genesis is identity (SPEC §9.2). A marked store never
    raises this: foreign genesis rows are simply inert.
    """


class UnsupportedProtocol(DeclarationResolutionError):
    """The genesis declares a protocol version this reader does not implement.

    Fail closed: a newer protocol may change document semantics, so the whole
    lineage is inert rather than partially interpreted (SPEC §9.2, build-plan
    "Protocol version in genesis").
    """


class Unhistorized:
    """At the requested ``as_of``, the store had not opened its lineage.

    Distinct from ``None``. ``None`` means "no genesis at all" (pre-genesis
    store — the file is authoritative). ``Unhistorized`` means "a genesis
    exists, but it is *later* than the ``as_of`` cutoff" — at that instant the
    store's ontology was not yet historized. Per SPEC §9.2 the honest answer
    for that era is **the genesis document set as the earliest known state**
    ("rendered honestly as legacy, never retro-claimed") — NOT the current
    file, which may have drifted since and would retro-claim history that was
    never recorded. The instance therefore carries ``documents`` (the genesis
    floor) so the caller can project the earliest known ontology while
    rendering the unhistorized distinction.
    """

    __slots__ = ("documents",)

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Unhistorized({len(self.documents)} docs)"


def _read_own_lineage(conn: sqlite3.Connection) -> str | None:
    """Read the store-local ``own_lineage`` marker, or None if unmarked.

    The marker lives in ``store_meta`` — a store-local table merge never
    copies (merge carries facts; identity is not a fact). Stores absorbed
    before the marker existed simply lack the table/row.
    """
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'own_lineage'"
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _open_readonly(store_path: Path) -> sqlite3.Connection | None:
    """Open ``store_path`` read-only, or None if it is not a usable store.

    Read-only (URI ``mode=ro``) so declaration resolution never mutates a
    store and is safe alongside a concurrent writer (WAL). A path that is not a
    valid SQLite database (empty file, non-db bytes) yields None — the caller
    falls back to the file, never crashes.
    """
    try:
        conn = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    return conn


def resolve_declaration_documents(
    store_path: Path,
    *,
    as_of: float | None = None,
) -> list[dict[str, Any]] | None | Unhistorized:
    """Fold the store's declaration events into a document set.

    Returns:

    - ``None`` — the store has no own ``_decl.genesis`` (pre-genesis; the file
      is authoritative), or is not a usable SQLite store.
    - :class:`Unhistorized` — an own genesis exists but is later than ``as_of``;
      carries the genesis document set as the earliest known state.
    - ``list[dict]`` — the folded documents (``{"kind", "subject", "payload"}``
      each), ready for :func:`~lang.document.documents_to_vertex`.

    Fold (all inside the store, replay-ordered ``ORDER BY ts, id``):

    1. Locate the OWN genesis: the ``store_meta.own_lineage`` marker selects it
       by id (foreign genesis rows are inert regardless of count); a marker
       whose row is missing raises :class:`DeclarationResolutionError`.
       Compat without a marker: zero rows → ``None``; exactly one → self;
       more → :class:`AmbiguousLineage`.
    2. If ``as_of`` is set and the genesis is later → :class:`Unhistorized`
       carrying the genesis documents (the SPEC §9.2 earliest-known floor).
    3. Check ``protocol`` ≤ supported → else :class:`UnsupportedProtocol`.
    4. Seed the document dict (keyed by ``(kind, subject)``) from the genesis
       payload's ``documents``.
    5. Overlay every LATER ``_decl.*`` row that is self-lineage-scoped
       (``payload["lineage"] == genesis id``) and within ``as_of``:
       ``*-defined`` replaces its ``(kind, subject)`` document (Latest wins by
       replay order); a tombstone removes the paired ``*-defined`` subject;
       ``_decl.genesis`` and unknown ``_decl.*`` kinds are skipped.
    6. Return the surviving documents in insertion order (definition order,
       modulo later replacements keeping position).
    """
    conn = _open_readonly(store_path)
    if conn is None:
        return None
    try:
        try:
            genesis_rows = conn.execute(
                "SELECT id, ts, payload FROM facts WHERE kind = ? ORDER BY ts, id",
                (DECL_GENESIS,),
            ).fetchall()
        except sqlite3.Error:
            # No facts table / unreadable schema — not a usable store.
            return None

        if not genesis_rows:
            return None

        marker = _read_own_lineage(conn)
        if marker is not None:
            selected = [r for r in genesis_rows if r[0] == marker]
            if not selected:
                raise DeclarationResolutionError(
                    f"own_lineage marker {marker!r} in {store_path} has no "
                    "matching _decl.genesis row — the store's identity record "
                    "is corrupt (marker without its genesis)"
                )
            genesis_id, genesis_ts, genesis_payload_text = selected[0]
        elif len(genesis_rows) == 1:
            # Pre-marker store (absorbed before store_meta existed): the single
            # genesis is self. The next write ceremony backfills the marker.
            genesis_id, genesis_ts, genesis_payload_text = genesis_rows[0]
        else:
            raise AmbiguousLineage(
                f"{len(genesis_rows)} _decl.genesis rows in {store_path} and no "
                "own_lineage marker — the store's own lineage is indeterminate; "
                "if this store predates the marker, re-run a write ceremony on "
                "it before merging foreign stores"
            )

        genesis_payload = json.loads(genesis_payload_text)
        protocol = genesis_payload.get("protocol", 1)
        if protocol > DECLARATION_PROTOCOL_VERSION:
            raise UnsupportedProtocol(
                f"genesis protocol {protocol} exceeds supported "
                f"{DECLARATION_PROTOCOL_VERSION} in {store_path} — refusing to "
                "partially interpret a newer declaration protocol"
            )

        if as_of is not None and genesis_ts > as_of:
            return Unhistorized(list(genesis_payload.get("documents", ())))

        # Seed from the genesis document set, keyed by (kind, subject).
        docs: dict[tuple[str, str], dict[str, Any]] = {}
        for d in genesis_payload.get("documents", ()):
            docs[(d["kind"], d["subject"])] = d

        # Overlay later declaration rows. This GLOB scan only runs once a
        # genesis is confirmed — never on a pre-genesis store (the hot path),
        # where step 1 already returned None.
        overlay_rows = conn.execute(
            "SELECT id, kind, ts, payload FROM facts "
            "WHERE kind GLOB '_decl.*' AND kind <> ? ORDER BY ts, id",
            (DECL_GENESIS,),
        ).fetchall()

        for _row_id, kind, _ts, payload_text in overlay_rows:
            if not is_internal_kind(kind):  # defensive; GLOB already scopes
                continue
            # Inclusive cutoff (`> as_of`, not `>= as_of`): an edit AT `as_of`
            # is in force. With equal-cursors (`as_of == until_ts`) a fact and an
            # edit sharing an exact `ts` fold the fact under the NEW ontology —
            # the deterministic ts-axis tie-break (module docstring).
            if as_of is not None and _ts > as_of:
                continue
            try:
                payload = json.loads(payload_text)
            except (json.JSONDecodeError, TypeError):
                continue
            # Self-lineage scoping: a foreign or absent lineage is inert.
            if payload.get("lineage") != genesis_id:
                continue

            if kind in _TOMBSTONE_OF_DEFINED:
                subject = payload.get("subject")
                docs.pop((_TOMBSTONE_OF_DEFINED[kind], subject), None)
            elif kind in _DEFINED_KINDS:
                subject = payload.get("subject")
                docs[(kind, subject)] = {
                    "kind": kind,
                    "subject": subject,
                    "payload": payload.get("payload", {}),
                }
            # else: receipts (_decl.transit/_decl.merged) and unknown _decl.*
            # kinds — skipped safely (forward compat).

        return list(docs.values())
    finally:
        conn.close()


def load_declaration(vertex_path: Path, *, as_of: float | None = None):
    """Resolve a vertex's declaration — THE seam (SPEC §9.5).

    This is the single function every declaration-consulting site routes
    through instead of ``parse_vertex_file``. It returns the same
    ``VertexFile`` AST the parser returns, so callers are unchanged.

    The file is parsed for two irreducible things: the **locator** (its
    ``store`` field, which says where the store lives — this legitimately lives
    in the file, §9.5) and the **pre-genesis fallback** (the file AST itself,
    authoritative before a lineage is opened).

    - If the store exists and has opened its lineage → the store's folded
      declaration, projected back to a ``VertexFile`` with the file's locator
      re-attached.
    - If ``as_of`` predates the genesis → the **genesis document set** projected
      (SPEC §9.2: "an ontology-as-of read before the genesis reports
      unhistorized, earliest known state = the genesis document"). NOT the
      current file — the file may have drifted since absorption, and returning
      it would retro-claim history that was never recorded.
    - Otherwise (no store, store absent, no genesis) → the file AST unchanged,
      pre-genesis behavior: before the lineage opened, the file is the only
      surviving record of that era and IS authoritative.
    """
    from lang import parse_vertex_file

    file_ast = parse_vertex_file(vertex_path)

    store_field = file_ast.store
    if store_field is None:
        return file_ast

    store_path = store_field
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()
    if not store_path.exists():
        return file_ast

    docs = resolve_declaration_documents(store_path, as_of=as_of)
    if isinstance(docs, list):
        resolved = documents_to_vertex(docs, path=vertex_path, store=store_field)
        return _reattach_ingress(resolved, file_ast)
    if isinstance(docs, Unhistorized):
        # Earliest known state — the genesis floor, never the drifted file.
        resolved = documents_to_vertex(
            docs.documents, path=vertex_path, store=store_field
        )
        return _reattach_ingress(resolved, file_ast)
    # None (pre-genesis / unusable store) → the file is the record.
    return file_ast


def _reattach_ingress(resolved, file_ast):
    """Re-attach ingress-class values from the file onto the resolved AST.

    Env VALUES are ingress (SPEC §9.5 secrets-indirection): declaration
    payloads record only the key set, so projection yields values as "".
    Like the ``store`` locator, the live values come from the file — the one
    residence the declaration deliberately does not carry. The key SET stays
    store-authoritative: a key present in the file but absent from the
    resolved declaration is NOT added (that's an unabsorbed edit, surfaced at
    ``absorb -n``); a resolved key missing from the file resolves to "" and
    fails loudly at runtime, honestly reflecting the absent ingress.
    """
    if not resolved.sources_blocks or not file_ast.sources_blocks:
        return resolved

    # File-side value lookup: (block index, command, key) → value, falling
    # back to (command, key) so a block reshuffle doesn't orphan values.
    by_block: dict[tuple[int, str, str], str] = {}
    by_cmd: dict[tuple[str, str], str] = {}
    for bi, block in enumerate(file_ast.sources_blocks):
        for src in block.sources:
            for k, v in src.env:
                by_block[(bi, src.command, k)] = v
                by_cmd.setdefault((src.command, k), v)

    from lang.ast import InlineSource, SourcesBlock

    changed = False
    new_blocks = []
    for bi, block in enumerate(resolved.sources_blocks):
        new_sources = []
        for src in block.sources:
            if src.env and any(v == "" for _, v in src.env):
                env = tuple(
                    (
                        k,
                        v or by_block.get((bi, src.command, k),
                                          by_cmd.get((src.command, k), "")),
                    )
                    for k, v in src.env
                )
                if env != src.env:
                    changed = True
                    src = InlineSource(
                        command=src.command, kind=src.kind, observer=src.observer,
                        every=src.every, on=src.on, format=src.format,
                        timeout=src.timeout, origin=src.origin, env=env,
                        parse=src.parse, path=src.path,
                    )
            new_sources.append(src)
        new_blocks.append(SourcesBlock(mode=block.mode, sources=tuple(new_sources)))

    if not changed:
        return resolved
    from lang.ast import VertexFile

    # ast.py's custom frozen decorator defeats dataclasses.replace — rebuild
    # through the constructor with the full explicit field list.
    return VertexFile(
        name=resolved.name,
        loops=resolved.loops,
        store=resolved.store,
        discover=resolved.discover,
        sources=resolved.sources,
        vertices=resolved.vertices,
        routes=resolved.routes,
        emit=resolved.emit,
        combine=resolved.combine,
        sources_blocks=tuple(new_blocks),
        observers=resolved.observers,
        lens=resolved.lens,
        boundary=resolved.boundary,
        observer_scoped=resolved.observer_scoped,
        strict=resolved.strict,
        path=resolved.path,
    )
