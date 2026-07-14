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
  (:class:`DeclarationResolutionError`). An UNMARKED store holding any genesis
  rows refuses (:class:`UnadoptedLineage`) — identity is claimed only by the
  explicit adopt ceremony (``loops store adopt``), never inferred from facts.

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

The overlay-row *payload shape* this reader consumes —
``{"lineage": <genesis id>, "subject": <str>, "payload": <document payload>}``
for a ``*-defined`` row and ``{"lineage": <genesis id>, "subject": <str>}`` for
a tombstone — is the contract the S4 edit ceremony (``SqliteStore.absorb_edit``)
emits; the Go conformance oracle mirrors both halves.
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
    """Retained alias tier — see :class:`UnadoptedLineage` (its subclass).

    Historically raised for "several genesis rows, no marker". The refusal is
    now uniform for ANY unmarked store holding genesis rows (a singleton is
    just as unprovable), raised as :class:`UnadoptedLineage`; existing
    ``except AmbiguousLineage`` handlers keep working via subclassing.
    """


class UnadoptedLineage(AmbiguousLineage):
    """Genesis rows exist but no ``own_lineage`` marker claims one as self.

    Facts alone cannot prove which genesis is self — a pre-marker own genesis
    and a merged-foreign one are physically identical, so ANY inference (even
    a singleton heuristic) is the hijack vector it tries to close. Identity
    is claimed only by the explicit adopt ceremony (``loops store adopt``),
    which stamps the marker under human intent (SPEC §9.2: genesis is
    identity; explicit over implicit).
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


class StoreBusy(DeclarationResolutionError):
    """The store is lock-contended within the caller's timeout budget.

    Raised only under ``on_locked="raise"`` — latency-bounded callers (shell
    completion) that must distinguish "locked, under-list" from "pre-genesis,
    the file is authoritative". The default path keeps the historical
    swallow-to-file-fallback behavior for interactive commands.
    """


def _open_readonly(
    store_path: Path, *, timeout: float = 5.0
) -> sqlite3.Connection | None:
    """Open ``store_path`` read-only, or None if it is not a usable store.

    Read-only (URI ``mode=ro``) so declaration resolution never mutates a
    store and is safe alongside a concurrent writer (WAL). A path that is not a
    valid SQLite database (empty file, non-db bytes) yields None — the caller
    falls back to the file, never crashes. ``timeout`` is sqlite's busy wait;
    latency-bounded callers pass a sub-second value.
    """
    try:
        conn = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True, timeout=timeout)
    except sqlite3.Error:
        return None
    return conn


def resolve_declaration_documents(
    store_path: Path,
    *,
    as_of: float | None = None,
    timeout: float = 5.0,
    on_locked: str = "swallow",
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
    conn = _open_readonly(store_path, timeout=timeout)
    if conn is None:
        return None
    try:
        try:
            genesis_rows = conn.execute(
                "SELECT id, ts, payload FROM facts WHERE kind = ? ORDER BY ts, id",
                (DECL_GENESIS,),
            ).fetchall()
        except sqlite3.Error as e:
            # Lock contention is DISTINGUISHABLE state for latency-bounded
            # callers: swallowing it here would flow to the file fallback —
            # a stale-file lie when a genesis exists (completion review
            # round 3 #2). Everything else (no facts table, unreadable
            # schema) means "not a usable store" as before.
            if on_locked == "raise" and "locked" in str(e).lower():
                raise StoreBusy(f"{store_path} is lock-contended: {e}") from e
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
        else:
            # No marker + genesis rows present. Facts alone CANNOT distinguish
            # a pre-marker own genesis from a merged-foreign one — a singleton
            # heuristic here is exactly the hijack it exists to prevent
            # (closing re-review #1). Identity is claimed only by the explicit
            # adopt ceremony (`loops store adopt`), never inferred.
            raise UnadoptedLineage(
                f"{len(genesis_rows)} _decl.genesis row(s) in {store_path} and "
                "no own_lineage marker — this store predates the identity "
                "marker (or received a foreign genesis via merge). Run "
                "`loops store adopt` to explicitly claim the store's own "
                "lineage; facts alone cannot prove which genesis is self"
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


#: Provenance statuses load_declaration_status reports alongside the AST.
#: "store"            — folded store declaration (head or honest as-of)
#: "file-pre-genesis" — no lineage opened; the file is authoritative
#: "unhistorized"     — as_of predates genesis; AST is the GENESIS FLOOR
#:                      (earliest known state), not a true as-of resolution
#: "aggregate-head"   — storeless combine/discover: membership is CURRENT
#:                      FILE state regardless of as_of (aggregation internal
#:                      tables not yet built — honesty caveat, SPEC §9.5)
DECLARATION_STATUSES = ("store", "file-pre-genesis", "unhistorized", "aggregate-head")


def load_declaration_status(
    vertex_path: Path,
    *,
    as_of: float | None = None,
    store_timeout: float = 5.0,
    on_locked: str = "swallow",
) -> tuple[Any, str]:
    """:func:`load_declaration` plus the provenance of what was resolved.

    The bare seam erases the ``Unhistorized`` distinction (every caller gets
    an AST); surfaces that RENDER a historical read need to say honestly which
    era the ontology came from — this is that channel (closing re-review #2).
    """
    from lang import parse_vertex_file

    file_ast = parse_vertex_file(vertex_path)
    store_field = file_ast.store
    if store_field is None:
        if as_of is not None and (
            file_ast.combine is not None or file_ast.discover is not None
        ):
            return file_ast, "aggregate-head"
        return file_ast, "file-pre-genesis"

    store_path = store_field
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()
    if not store_path.exists():
        return file_ast, "file-pre-genesis"

    docs = resolve_declaration_documents(
        store_path, as_of=as_of, timeout=store_timeout, on_locked=on_locked,
    )
    if isinstance(docs, list):
        resolved = documents_to_vertex(docs, path=vertex_path, store=store_field)
        return _reattach_ingress(resolved, file_ast), "store"
    if isinstance(docs, Unhistorized):
        resolved = documents_to_vertex(
            docs.documents, path=vertex_path, store=store_field
        )
        return _reattach_ingress(resolved, file_ast), "unhistorized"
    return file_ast, "file-pre-genesis"


def load_declaration(
    vertex_path: Path,
    *,
    as_of: float | None = None,
    store_timeout: float = 5.0,
    on_locked: str = "swallow",
):
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

    Rendering surfaces that must SAY which era the ontology came from use
    :func:`load_declaration_status` instead — this bare seam returns the same
    AST but erases the provenance.
    """
    ast, _status = load_declaration_status(
        vertex_path, as_of=as_of, store_timeout=store_timeout, on_locked=on_locked,
    )
    return ast


class SourceDrift(DeclarationResolutionError):
    """A pinned source file's content no longer matches its declaration pin.

    The ``source-defined`` event hash-pinned the referenced ``.loop`` (or
    template params file) at absorb time. Running with drifted content would
    ENACT undeclared behavior — the ontology would say one thing and the
    runtime do another (the §9.1 lie at the execution tier). Surfaced, never
    auto-enacted: re-absorb to accept the drift into the lineage.
    """


def verify_source_pins(vertex_path: Path) -> None:
    """Refuse to run over drifted pinned sources (SPEC §9.2, no-auto-enact).

    For every ``source-defined`` document carrying a ``content_sha256`` (or a
    ``from.params_sha256``), hash the referenced file's current bytes and
    raise :class:`SourceDrift` on mismatch. Pre-genesis stores (no documents)
    and unpinned rows (legacy genesis, missing files at absorb) are no-ops —
    the pin gate only guards claims the declaration actually makes.
    """
    import hashlib

    from lang import parse_vertex_file
    from lang.document import DECL_SOURCE_DEFINED

    file_ast = parse_vertex_file(vertex_path)
    store_field = file_ast.store
    if store_field is None:
        return
    store_path = store_field
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()
    if not store_path.exists():
        return
    docs = resolve_declaration_documents(store_path)
    if not isinstance(docs, list):
        return

    base = vertex_path.parent

    def _check(ref: str, pinned: str, what: str) -> None:
        path = Path(ref)
        candidate = path if path.is_absolute() else (base / path)
        try:
            current = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            raise SourceDrift(
                f"{what} {ref} is pinned in the declaration but unreadable — "
                "restore it or re-absorb"
            ) from None
        if current != pinned:
            raise SourceDrift(
                f"{what} {ref} has drifted from its declaration pin — the "
                "store's ontology no longer describes this file; run "
                "`loops store absorb` to declare the change (never "
                "auto-enacted)"
            )

    for d in docs:
        if d.get("kind") != DECL_SOURCE_DEFINED:
            continue
        payload = d.get("payload", {})
        pinned = payload.get("content_sha256")
        if pinned:
            ref = payload.get("template") or payload.get("path")
            if ref:
                _check(ref, pinned, "source")
        from_d = payload.get("from") or {}
        params_pin = from_d.get("params_sha256")
        if params_pin and from_d.get("path"):
            _check(from_d["path"], params_pin, "params file")


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

    # File-side value lookup keyed by OCCURRENCE identity — (block index,
    # command, occurrence-ordinal) — the same identity the document layer's
    # collision-suffixed subjects encode. Keying by command alone cross-wired
    # values between two sources sharing a command (re-review #4: a real
    # secret cross-wire). Fallback to (command, ordinal) so a block reshuffle
    # doesn't orphan values.
    #
    # Ordinal identity is only sound while the file's occurrence COUNT for a
    # (block, command) group matches the resolved declaration's. A structural
    # edit not yet absorbed (delete/insert one of two duplicate-command
    # sources) re-numbers the survivors and would misroute values across
    # sources (branch-review #2) — for such diverged groups re-attachment is
    # SKIPPED entirely: values resolve empty and fail loudly at runtime, and
    # `absorb -n` surfaces the divergence to reconcile. Within a count-stable
    # group, position IS the identity ("order is meaning").
    by_block: dict[tuple[int, str, int], dict[str, str]] = {}
    file_seen: dict[tuple[int, str], int] = {}
    for bi, block in enumerate(file_ast.sources_blocks):
        for src in block.sources:
            nth = file_seen.get((bi, src.command), 0)
            file_seen[(bi, src.command)] = nth + 1
            by_block[(bi, src.command, nth)] = dict(src.env)

    resolved_counts: dict[tuple[int, str], int] = {}
    for bi, block in enumerate(resolved.sources_blocks):
        for src in block.sources:
            resolved_counts[(bi, src.command)] = (
                resolved_counts.get((bi, src.command), 0) + 1
            )

    from lang.ast import InlineSource, SourcesBlock

    changed = False
    new_blocks = []
    resolved_seen: dict[tuple[int, str], int] = {}
    for bi, block in enumerate(resolved.sources_blocks):
        new_sources = []
        for src in block.sources:
            nth = resolved_seen.get((bi, src.command), 0)
            resolved_seen[(bi, src.command)] = nth + 1
            if src.env and any(v == "" for _, v in src.env):
                # Re-attach ONLY within a count-stable (block, command)
                # group — the sole scope where ordinal identity is provable.
                # No cross-block fallback: a moved source resolves empty
                # until re-absorbed (a fallback with block-local ordinals
                # cross-wired secrets across blocks — branch-review round 2).
                block_stable = (
                    resolved_counts.get((bi, src.command))
                    == file_seen.get((bi, src.command))
                )
                env_map = (
                    by_block.get((bi, src.command, nth), {})
                    if block_stable
                    else {}
                )
                env = tuple(
                    (k, v or env_map.get(k, ""))
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
