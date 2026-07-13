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
  overlay is applied on top of. More than one ``_decl.genesis`` row is an
  ambiguous lineage (:class:`AmbiguousLineage`) — pre-S6 a store cannot
  distinguish its own genesis from a merged-foreign one (no ``_decl.merged``
  receipts yet), so the conservative rule is to refuse rather than guess. This
  is revisited when merge provenance receipts land (S6).

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
    """More than one ``_decl.genesis`` row exists in the store.

    Pre-S6 a store cannot distinguish its own genesis from a merged-foreign one
    (no ``_decl.merged`` provenance receipts yet), so two genesis rows make the
    store's own lineage indeterminate. Conservative refusal, not last-write-wins
    — genesis is identity (SPEC §9.2). Revisited when merge receipts land.
    """


class UnsupportedProtocol(DeclarationResolutionError):
    """The genesis declares a protocol version this reader does not implement.

    Fail closed: a newer protocol may change document semantics, so the whole
    lineage is inert rather than partially interpreted (SPEC §9.2, build-plan
    "Protocol version in genesis").
    """


class _Unhistorized:
    """Sentinel: at the requested ``as_of``, the store had not opened its lineage.

    Distinct from ``None``. ``None`` means "no genesis at all" (pre-genesis
    store — the file is authoritative). :data:`UNHISTORIZED` means "a genesis
    exists, but it is *later* than the ``as_of`` cutoff" — at that instant the
    store's ontology was not yet historized. Keeping the two apart lets the
    read path (S5) render the honest "unhistorized before genesis" state rather
    than conflating it with a store that never opened a lineage.
    """

    _instance: _Unhistorized | None = None

    def __new__(cls) -> _Unhistorized:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "UNHISTORIZED"


UNHISTORIZED = _Unhistorized()


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
) -> list[dict[str, Any]] | None | _Unhistorized:
    """Fold the store's declaration events into a document set.

    Returns:

    - ``None`` — the store has no ``_decl.genesis`` (pre-genesis; the file is
      authoritative), or is not a usable SQLite store.
    - :data:`UNHISTORIZED` — a genesis exists but is later than ``as_of`` (the
      ontology was not yet historized at that instant).
    - ``list[dict]`` — the folded documents (``{"kind", "subject", "payload"}``
      each), ready for :func:`~lang.document.documents_to_vertex`.

    Fold (all inside the store, replay-ordered ``ORDER BY ts, id``):

    1. Locate the genesis. Zero → ``None``. More than one → :class:`AmbiguousLineage`.
    2. If ``as_of`` is set and the genesis is later → :data:`UNHISTORIZED`.
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
        if len(genesis_rows) > 1:
            raise AmbiguousLineage(
                f"{len(genesis_rows)} _decl.genesis rows in {store_path} — the "
                "store's own lineage is indeterminate (pre-S6: self vs "
                "merged-foreign genesis cannot be told apart)"
            )

        genesis_id, genesis_ts, genesis_payload_text = genesis_rows[0]

        if as_of is not None and genesis_ts > as_of:
            return UNHISTORIZED

        genesis_payload = json.loads(genesis_payload_text)
        protocol = genesis_payload.get("protocol", 1)
        if protocol > DECLARATION_PROTOCOL_VERSION:
            raise UnsupportedProtocol(
                f"genesis protocol {protocol} exceeds supported "
                f"{DECLARATION_PROTOCOL_VERSION} in {store_path} — refusing to "
                "partially interpret a newer declaration protocol"
            )

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
    - Otherwise (no store, store absent, no genesis, or ``as_of`` predates the
      genesis) → the file AST unchanged, current pre-genesis behavior.

    ``as_of`` is a timestamp cutoff hook for the read path (S5). Today an
    ``as_of`` that predates the genesis falls back to the file: before the
    lineage opened there is no store-form declaration, and the file is the only
    surviving record of that era. S5 owns the read-path wiring and may render
    the :data:`UNHISTORIZED` distinction differently.
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
        return documents_to_vertex(docs, path=vertex_path, store=store_field)
    # None (pre-genesis / unusable store) or UNHISTORIZED → file is the record.
    return file_ast
