"""Witness positions — the read-path temporal cursor (SPEC §9.3, 0.8.0 session 1).

A cursor denotes the **inclusive witness prefix** of rows a store had received at
a position: ``WHERE rowid <= resolved``. The selected prefix — domain facts and
self-lineage ``_decl.*`` rows alike — is then replayed in ``(ts, id)`` order, and
ontology resolves from the ``_decl`` rows *in the same prefix* (equal cursors ⇒
same position for selection and ontology). This is the "what a reader at P could
have seen" honesty of §9.3: late arrivals (merge / import / backdate) do not
rewrite what an earlier position shows, because a backdated fact lands at a
*later* witness position even though it sorts early under ``(ts, id)`` replay.

Contrast with the shipped ``as_of`` event-time projection (``ts <= T``): that is
an explicitly-requested analytical mode, never the cursor default. The two
selectors are **mutually exclusive** (A8): a read is either witness-cursor'd or
event-time-projected, never a chimera of both.

Design invariants this module pins:

- **Identity is a fact id, resolved by primary-key lookup ONLY** (A3). Ids are
  never ordered or parsed for cursor purposes — the corpus mixes uuid4-era and
  ULID-era ids, and even pure-ULID stores are not within-millisecond monotonic
  (see :func:`~engine.sqlite_store.gen_id`). ``id -> rowid`` is a ``WHERE id = ?``
  point lookup; ``rowid`` (append order) is the witness axis.

- **Facts-only axis** (A1). Facts and ticks occupy separate rowid domains with no
  durable cross-table receipt log in 0.8.0; the fold boundary needs only the
  facts axis (ticks never feed fold state). A store-wide receipt ordinal
  (GlobalReceiptPosition) is a queued protocol amendment, not smuggled in here.

- **Receipt-group atomicity** (A2). An absorb-edit ceremony writes multiple
  ``_decl.*`` rows atomically — one ``BEGIN IMMEDIATE``, one stamped effective
  ``ts``, contiguous rowids (``sqlite_store.absorb_edit``). A cursor that lands
  *strictly inside* such a group would select a half-applied ceremony, so
  resolution **refuses on ambiguity** (:class:`MidReceiptGroupPosition`) rather
  than silently folding a partial ontology. The guard lives at the engine
  selector — every ``at=`` seam runs it — not only in the CLI address resolver.
  In 0.8.0 the group boundary is a *heuristic* (contiguity + shared ts + shared
  lineage), origin-guaranteed by the write path but not interchange-guaranteed;
  a durable group id is a queued protocol amendment.

- **Unadopted stores** (N1). The live corpus is overwhelmingly pre-genesis: no
  ``_decl.genesis``, no ``store_meta.own_lineage`` marker, so nothing to qualify
  a durable handle with. In-session positions work everywhere, but a cursor
  against an unadopted store carries :attr:`WitnessPosition.unadopted` — durable
  serialization is a CLI-layer refusal (no surrogate ids invented here).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from engine.declaration import (
    DeclarationResolutionError,
    _open_readonly,
    _read_own_lineage,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from atoms.fold_state import FoldState

#: The empty / start-of-store cursor: the position *before* the first received
#: row. Its prefix (``rowid <= 0``) is empty. Distinct from "head" (newest row).
GENESIS_SENTINEL = ""


class WitnessResolutionError(DeclarationResolutionError):
    """Base for witness-position (read-path cursor) resolution failures."""


class UnknownWitnessHandle(WitnessResolutionError):
    """A cursor names a fact id no row in the store carries.

    Handles resolve by primary-key lookup only (A3); a miss is not a prefix to
    widen or an id to parse — it is an unresolvable position. (Prefix expansion
    is a CLI-layer convenience over :func:`~engine.vertex_reader.vertex_fact_by_id`;
    the engine seam takes a full, canonical fact id.)
    """


class MidReceiptGroupPosition(WitnessResolutionError):
    """A cursor lands strictly inside an atomic receipt group (A2).

    An absorb-edit ceremony's ``_decl.*`` rows are all-or-nothing: a prefix that
    includes some but not all of them would resolve a half-applied ontology.
    Raised only for the **refuse** boundary mode (exact ``fact:``/``seq:``
    forms) — naming a mid-ceremony row is an error with teaching. Floor-derived
    forms (``tick:``/wall-clock) pass ``group_boundary="floor"`` to
    :func:`resolve_witness_position`, which SNAPS to the position just before
    the ceremony's first row instead of raising.
    """


class WitnessAggregateUnsupported(WitnessResolutionError):
    """A witness position was handed to a combine/discover (aggregate) read.

    Witness positions are per-store — they resolve against one store's rowid
    axis. An aggregate has no shared witness order across members (A1/A9); a
    ``seq:``/``fact:`` handle is member-scoped. Address the member store
    directly, or use the event-time ``as_of`` projection for a uniform
    aggregate answer.
    """


class WitnessLineageMismatch(WitnessResolutionError):
    """A witness position is applied to a store it was not resolved against (A10).

    A position's ``rowid`` indexes ONE store's append order; applying it to a
    different store selects an unrelated prefix. A read is accepted only when the
    target store IS the store the position was resolved against (same resolved
    path — always valid, unadopted handles included, N1) or when the position is
    lineage-qualified and the target store shares that lineage (the portable
    lineage-handle contract). Anything else is refused — silence here is the
    "same handle silently means a different prefix" hazard A10 exists to close.
    """


class SeqOutOfRange(WitnessResolutionError):
    """A ``seq:N`` address names a receipt ordinal outside ``[1, total rows]``.

    ``seq`` is a 1-based receipt ordinal over ALL rows in rowid (append)
    order, ``_decl.*`` included — the inverse of :attr:`WitnessPosition.seq`.
    """


class UnknownTickHandle(WitnessResolutionError):
    """A ``tick:ID`` address names a tick id no row in the store carries."""


class NoWitnessAnchor(WitnessResolutionError):
    """A wall-clock or tick address has no usable witness-time anchor.

    Facts carry no receipt timestamp (module docstring) — only a sealed,
    chained tick's ``fact_cursor`` binds wall-clock to a witness position.
    Raised when the named tick predates the chain era (no ``fact_cursor``
    column, or an empty cursor on a pre-chain row), or when no chained tick
    exists at-or-before a wall-clock mark. Per A5, this is never silently
    approximated with a ts-cutoff — the caller routes to the explicit
    ``--as-of`` event-time projection instead.
    """


@dataclass(frozen=True)
class TickAnchor:
    """The last sealed tick at-or-before a witness position, if any.

    A tick's ``fact_cursor`` is the only wall-clock-bearing anchor on the facts
    axis (its ``ts`` is a signed claim, not a per-fact receipt time). This names
    the most recent sealed boundary whose window closed at-or-before the
    position — what the cursor is "as of" in dated terms. ``None`` when no sealed
    tick precedes the position (pre-first-tick era, or a store with no chained
    ticks): the position is in the unsealed/unanchored tail (A12).
    """

    name: str
    ts: float
    fact_cursor: str


@dataclass(frozen=True)
class WitnessPosition:
    """A resolved inclusive witness prefix — the rows a reader at P had received.

    Produced by :func:`resolve_witness_position`; the resolved ``rowid`` is the
    selection cutoff (``WHERE rowid <= rowid``). Frozen: a position is a fixed
    point, never a moving token (head is captured atomically at resolve time).
    """

    #: The durable canonical handle — the fact id at this position.
    #: :data:`GENESIS_SENTINEL` (``""``) for the empty/start-of-store position.
    fact_id: str
    #: Append-order cutoff. The prefix is every row with ``rowid <= rowid``.
    #: ``0`` is the empty prefix (before the first row).
    rowid: int
    #: Receipt ordinal — the count of rows at-or-before this position
    #: (``ROW_NUMBER`` over rowid order, display-tier, per-store). Includes
    #: ``_decl.*`` rows in the count, matching the ``seq:N`` address form.
    seq: int
    #: The store's own lineage id, or ``None`` when the store is unadopted.
    lineage: str | None
    #: ``True`` when the store has no ``own_lineage`` marker (pre-genesis or
    #: pre-marker): the handle is session-local, not portable (N1).
    unadopted: bool
    #: The last sealed tick at-or-before this position, or ``None`` (A12).
    anchor: TickAnchor | None
    #: The resolved (canonical, absolute) path of the store this position was
    #: resolved against. A position's rowid is meaningful ONLY in this store;
    #: :func:`verify_position_for_store` uses it to refuse cross-store misuse
    #: (A10) — especially for unadopted handles, which have no lineage to
    #: qualify them with.
    store: str


def _lineage_of(payload_text: str) -> str | None:
    """Extract a ``_decl`` row's declared lineage, or None (genesis / malformed)."""
    try:
        return json.loads(payload_text).get("lineage")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


def receipt_group_span(conn: sqlite3.Connection, rowid: int) -> tuple[int, int] | None:
    """If ``rowid`` falls strictly inside a receipt group, return its span.

    A receipt group is a maximal run of ``_decl.*`` rows that are **contiguous in
    rowid** and share one effective ``ts`` and one ``lineage`` — the atomic
    footprint of one absorb ceremony (``sqlite_store.absorb_edit``: one
    ``BEGIN IMMEDIATE``, one stamped ``ts``). Returns ``(first_rowid,
    last_rowid)`` when ``first <= rowid < last`` (the prefix would include a
    *partial* ceremony); ``None`` otherwise — a cutoff at-or-after the group's
    last row includes the whole ceremony (fine), and a genesis or a lone edit is
    a singleton run that can never be mid-group.

    Origin-guaranteed by the write path, not interchange-guaranteed: a
    kind-filtered slice can split a group across stores, and the shared-ts test
    is a heuristic until a durable group id ships (A2 residue). The scan is over
    ``_decl.*`` rows only — negligible on the live corpus (≤1 such row exists
    store-wide today).
    """
    rows = conn.execute(
        "SELECT rowid, ts, payload FROM facts WHERE kind GLOB '_decl.*' ORDER BY rowid"
    ).fetchall()
    if not rows:
        return None
    runs: list[tuple[int, int]] = []
    run_start = prev_rowid = rows[0][0]
    prev_ts = rows[0][1]
    prev_lineage = _lineage_of(rows[0][2])
    for rid, ts, payload_text in rows[1:]:
        lineage = _lineage_of(payload_text)
        if rid == prev_rowid + 1 and ts == prev_ts and lineage == prev_lineage:
            pass  # same ceremony — extend the run
        else:
            runs.append((run_start, prev_rowid))
            run_start = rid
        prev_rowid, prev_ts, prev_lineage = rid, ts, lineage
    runs.append((run_start, prev_rowid))
    for first, last in runs:
        if first <= rowid < last:
            return (first, last)
    return None


def _resolve_anchor(conn: sqlite3.Connection, rowid: int) -> TickAnchor | None:
    """Last sealed tick whose ``fact_cursor`` resolves at-or-before ``rowid``.

    Joins ``ticks.fact_cursor`` to ``facts.id`` (the same id→rowid resolution the
    window hash uses) and takes the highest cursor-rowid within the prefix. Pre-
    chain schemas (no ``fact_cursor`` column) and pre-chain rows (empty cursor)
    contribute nothing — honestly no anchor.

    Tie-break: when several ticks seal the SAME ``fact_cursor`` (a re-fired
    boundary), the LAST-appended tick wins (``t.rowid DESC``) — the "last tick"
    the docstring promises, resolved deterministically rather than by whichever
    row the engine happened to return.
    """
    tick_cols = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
    if "fact_cursor" not in tick_cols:
        return None
    row = conn.execute(
        "SELECT t.name, t.ts, t.fact_cursor FROM ticks t "
        "JOIN facts f ON f.id = t.fact_cursor "
        "WHERE t.fact_cursor IS NOT NULL AND t.fact_cursor <> '' "
        "AND f.rowid <= ? ORDER BY f.rowid DESC, t.rowid DESC LIMIT 1",
        (rowid,),
    ).fetchone()
    if row is None:
        return None
    return TickAnchor(name=row[0], ts=row[1], fact_cursor=row[2])


def resolve_witness_position(
    store_path: Path,
    address: str,
    *,
    timeout: float = 5.0,
    anchor: TickAnchor | None = None,
    group_boundary: str = "refuse",
) -> WitnessPosition:
    """Resolve a witness address to a :class:`WitnessPosition` against one store.

    Address forms handled at this engine seam:

    - ``"head"`` — the newest received fact, captured atomically (frozen once
      returned; no moving token). An empty store resolves to the empty prefix.
    - :data:`GENESIS_SENTINEL` (``""``) — the empty / start-of-store position.
    - a full, canonical fact id — resolved by **primary-key lookup only** (A3);
      an unknown id raises :class:`UnknownWitnessHandle`. Prefix expansion and
      ``seq:``/``tick:``/wall-clock address forms are CLI-layer resolutions that
      produce a fact id (or a rowid) to hand here.

    Runs the receipt-group guard (A2) — a mid-ceremony position raises
    :class:`MidReceiptGroupPosition`. Reads the ``own_lineage`` marker to set
    :attr:`WitnessPosition.unadopted` (N1).

    ``anchor``: for a ``tick:``/wall-clock address, the CALLER already knows the
    exact tick it snapped to (from :func:`resolve_tick_cursor` /
    :func:`resolve_tick_floor`) and passes it here so it is PRESERVED as the
    position's :attr:`~WitnessPosition.anchor` (review finding 7a). Re-deriving
    it from the cursor would be wrong when several ticks seal the same
    ``fact_cursor`` — one of them possibly *after* the requested mark — and the
    re-derivation would name that later tick instead of the floor tick actually
    selected. When ``None`` (head/seq/fact forms), the anchor is derived as the
    last sealed tick at-or-before the position.

    ``group_boundary`` governs a position that lands inside an atomic receipt
    group (A2). ``"refuse"`` (default, for exact forms — ``fact:``/``seq:``)
    raises :class:`MidReceiptGroupPosition`. ``"floor"`` (for floor-derived
    forms — ``tick:``/wall-clock, chosen by the CLI resolver per address form)
    **snaps** to the position just before the ceremony's first row — the last
    complete ontology state — rather than refusing (M3). ``head`` never lands
    mid-group (a completed ceremony committed atomically).
    """
    conn = _open_readonly(store_path, timeout=timeout)
    if conn is None:
        raise WitnessResolutionError(
            f"{store_path} is not a usable store — cannot resolve a witness "
            "position against it"
        )
    try:
        fact_id, rowid = _resolve_address_rowid(conn, address)
        span = receipt_group_span(conn, rowid)
        if span is not None:
            if group_boundary == "floor":
                # Snap OUT of the ceremony to the position just before its first
                # row — the last complete state (M3). Floor forms land on solid
                # ground rather than refusing.
                rowid = span[0] - 1
                fact_id = _id_at_rowid(conn, rowid)
            else:  # "refuse" — an exact fact:/seq: form never silently snaps.
                raise MidReceiptGroupPosition(
                    f"witness position {address!r} (rowid {rowid}) lands inside "
                    f"the atomic receipt group at rowids {span[0]}..{span[1]} — "
                    "a declaration edit ceremony is all-or-nothing. Address the "
                    f"position at-or-after rowid {span[1]} (the ceremony's last "
                    "row) to include the whole edit, or before its first row to "
                    "exclude it."
                )
        marker = _read_own_lineage(conn)
        seq = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE rowid <= ?", (rowid,)
        ).fetchone()[0]
        resolved_anchor = anchor if anchor is not None else _resolve_anchor(conn, rowid)
        return WitnessPosition(
            fact_id=fact_id,
            rowid=rowid,
            seq=seq,
            lineage=marker,
            unadopted=marker is None,
            anchor=resolved_anchor,
            store=str(Path(store_path).resolve()),
        )
    finally:
        conn.close()


def verify_position_for_store(
    at: WitnessPosition, store_path: Path, *, timeout: float = 5.0
) -> WitnessPosition:
    """Return the position to APPLY against ``store_path``, or refuse (A10).

    A witness position's ``rowid`` is an index into ONE store's append order;
    applying it to another store silently selects an unrelated prefix. Cases:

    - the target store IS the store the position was resolved against (same
      resolved path) — returns ``at`` unchanged (its rowid is valid, unadopted
      handles included, N1);
    - the position is lineage-qualified (adopted) AND the target store shares
      that lineage — **re-resolves** ``at.fact_id`` in the target store and
      returns the target-store position. The source rowid is NEVER reused: append
      order is per-store, so a merge that copied the fact reorders it (B1c). A
      fact id absent from the target raises :class:`UnknownWitnessHandle`;
      - an unadopted position (no lineage) on a different store, or a lineage
      mismatch, raises :class:`WitnessLineageMismatch` with teaching.

    Called at every engine ``at=`` selector (``vertex_fold`` / ``vertex_facts`` /
    ``resolve_declaration_documents``) before the rowid is applied, so no read
    layer trusts a foreign position — the guard that the in-memory check alone
    could not give once a handle is serialized and re-used across stores.
    """
    target = str(Path(store_path).resolve())
    if at.store == target:
        return at
    if at.lineage is None:
        raise WitnessLineageMismatch(
            f"witness position (fact {at.fact_id!r}) was resolved against "
            f"{at.store} but is being applied to {target} — an UNADOPTED handle "
            "is session-local to its own store (N1); its rowid means nothing "
            "here. Resolve the position against this store, or adopt the store "
            "to mint a portable lineage-qualified handle."
        )
    conn = _open_readonly(store_path, timeout=timeout)
    target_lineage = _read_own_lineage(conn) if conn is not None else None
    if conn is not None:
        conn.close()
    if target_lineage != at.lineage:
        raise WitnessLineageMismatch(
            f"witness position (lineage {at.lineage}) was resolved against "
            f"{at.store} and does not match this store's lineage "
            f"({target_lineage}) at {target} — a lineage-qualified handle "
            "resolves only against its own lineage (A10). Address the correct "
            "store, or re-resolve the position here."
        )
    # Same lineage, DIFFERENT store: re-resolve the fact id in the target store
    # so the applied rowid is the TARGET's append position (B1c) — never the
    # source's. The empty/genesis sentinel maps to the target's empty prefix.
    return resolve_witness_position(store_path, at.fact_id, timeout=timeout)


def _resolve_address_rowid(conn: sqlite3.Connection, address: str) -> tuple[str, int]:
    """Map an address to ``(fact_id, rowid)`` — primary-key lookup only (A3)."""
    if address == GENESIS_SENTINEL:
        return GENESIS_SENTINEL, 0
    if address == "head":
        row = conn.execute(
            "SELECT id, rowid FROM facts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return GENESIS_SENTINEL, 0  # empty store → empty prefix
        return row[0], row[1]
    # A full fact id — PK point lookup, never ordered or parsed.
    row = conn.execute(
        "SELECT rowid FROM facts WHERE id = ?", (address,)
    ).fetchone()
    if row is None:
        raise UnknownWitnessHandle(
            f"no fact with id {address!r} in this store — a witness handle "
            "resolves by exact id (ids are opaque; never parsed or ordered)"
        )
    return address, row[0]


def _id_at_rowid(conn: sqlite3.Connection, rowid: int) -> str:
    """The fact id at ``rowid``, or the empty sentinel for rowid <= 0."""
    if rowid <= 0:
        return GENESIS_SENTINEL
    row = conn.execute("SELECT id FROM facts WHERE rowid = ?", (rowid,)).fetchone()
    return row[0] if row else GENESIS_SENTINEL


def durable_handle(pos: WitnessPosition) -> str | None:
    """The PORTABLE address form for a position, or ``None`` if not serializable.

    A10-narrowed durable-handle contract (final-contracts Session 1):

    - **Adopted** store → ``fact:<lineage>/<id>`` — the lineage-qualified handle.
      Re-resolving it elsewhere verifies the lineage and re-resolves the id in
      the target store (never reuses a rowid), so the same handle can never
      silently mean a different prefix across stores.
    - **Unadopted** store (no lineage), or the empty/genesis sentinel → ``None``:
      **durable serialization is REFUSED** (N1). The position is session-local;
      no surrogate id is invented. A caller rendering cursor metadata MUST NOT
      present a bare ``fact:<id>`` as a reusable handle here — it is not portable
      (the id resolves in ANY store that merged the fact, to a different prefix).
    """
    if pos.unadopted or pos.lineage is None or not pos.fact_id:
        return None
    return f"fact:{pos.lineage}/{pos.fact_id}"


def expand_fact_prefix(store_path: Path, prefix: str, *, timeout: float = 5.0) -> str:
    """Resolve a (possibly partial) ``fact:`` id to its full canonical id.

    Exact-then-prefix resolution over ALL rows (``include_internal`` — witness
    identity is over every row regardless of kind: a ``_decl.*`` row is still a
    valid, addressable position, and the receipt-group guard, not kind, is what
    may refuse it). The engine owns store access, so this lives here rather than
    in the CLI (the app must not touch :class:`StoreReader` directly).

    Raises :class:`UnknownWitnessHandle` when nothing matches, and propagates
    ``StoreReader.fact_by_id``'s ``ValueError`` for an ambiguous prefix (two
    facts share it) — the CLI grammar layer turns both into its own address
    error. The resolved id still flows through :func:`resolve_witness_position`
    for the actual position (guard, lineage, anchor).
    """
    from .store_reader import StoreReader

    with StoreReader(store_path, timeout=timeout) as reader:
        found = reader.fact_by_id(prefix, include_internal=True)
    if found is None:
        raise UnknownWitnessHandle(
            f"no fact matches {prefix!r} in this store — a witness handle "
            "resolves by exact id or an unambiguous prefix"
        )
    return found["id"]


def resolve_seq(store_path: Path, n: int, *, timeout: float = 5.0) -> str:
    """Resolve a ``seq:N`` receipt ordinal to its fact id.

    The inverse of :attr:`WitnessPosition.seq`: ``seq`` is a 1-based ordinal
    over ALL rows in rowid (append) order, ``_decl.*`` included. This is a
    rowid→id lookup (``ORDER BY rowid`` + offset), never an ordering of ids
    (A3) — the resolved id still flows through
    :func:`resolve_witness_position` for the actual position (receipt-group
    guard, lineage, anchor).

    Raises :class:`SeqOutOfRange` for ``n < 1`` or ``n`` beyond the store's
    total receipt count.
    """
    conn = _open_readonly(store_path, timeout=timeout)
    if conn is None:
        raise WitnessResolutionError(
            f"{store_path} is not a usable store — cannot resolve seq:{n} "
            "against it"
        )
    try:
        row = (
            conn.execute(
                "SELECT id FROM facts ORDER BY rowid LIMIT 1 OFFSET ?",
                (n - 1,),
            ).fetchone()
            if n >= 1
            else None
        )
        if row is None:
            total = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            raise SeqOutOfRange(
                f"seq:{n} is out of range — this store has {total} receipt(s) "
                f"(valid range: seq:1..seq:{total})"
            )
        return row[0]
    finally:
        conn.close()


def resolve_tick_cursor(
    store_path: Path, tick_id: str, *, timeout: float = 5.0
) -> tuple[str, str, float]:
    """Resolve a ``tick:ID`` address to its ``(fact_cursor, name, ts)``.

    A tick's own id is a primary-key lookup into the ``ticks`` table (never
    ordered or parsed, A3's sibling rule); its ``fact_cursor`` is already a
    fact id and is handed to :func:`resolve_witness_position` unchanged.

    Raises :class:`UnknownTickHandle` when no tick carries that id, and
    :class:`NoWitnessAnchor` when the named tick predates the witness-chain
    era (no usable ``fact_cursor`` — A5's honest refusal, never a silent
    ts-approximation).
    """
    conn = _open_readonly(store_path, timeout=timeout)
    if conn is None:
        raise WitnessResolutionError(
            f"{store_path} is not a usable store — cannot resolve tick:"
            f"{tick_id} against it"
        )
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
        if "fact_cursor" not in cols:
            row = conn.execute(
                "SELECT name, ts FROM ticks WHERE id = ?", (tick_id,)
            ).fetchone()
            if row is None:
                raise UnknownTickHandle(
                    f"no tick with id {tick_id!r} in this store"
                )
            raise NoWitnessAnchor(
                f"tick:{tick_id} ({row[0]} @ {row[1]}) predates the "
                "witness-chain era (no fact_cursor column) — no witness "
                "anchor for this era. Use --as-of for the explicit "
                "event-time projection instead."
            )
        row = conn.execute(
            "SELECT name, ts, fact_cursor FROM ticks WHERE id = ?", (tick_id,)
        ).fetchone()
        if row is None:
            raise UnknownTickHandle(f"no tick with id {tick_id!r} in this store")
        name, ts, cursor = row
        if not cursor:
            raise NoWitnessAnchor(
                f"tick:{tick_id} ({name} @ {ts}) has no witness anchor — a "
                "pre-chain tick was never bound to a fact_cursor. Use "
                "--as-of for the explicit event-time projection instead."
            )
        return cursor, name, ts
    finally:
        conn.close()


def resolve_tick_floor(
    store_path: Path, mark_ts: float, *, timeout: float = 5.0
) -> tuple[str, str, float]:
    """The last sealed, chained tick at-or-before ``mark_ts`` — the wall-clock floor.

    Wall-clock addressing snaps to the newest tick whose window closed
    at-or-before the mark (A5): facts carry no receipt timestamp, so a tick's
    ``fact_cursor`` is the only anchor binding wall-clock to a witness
    position. Returns ``(fact_cursor, name, ts)`` of that tick.

    Raises :class:`NoWitnessAnchor` when no chained tick precedes the mark
    (sparse-tick eras, pre-chain ticks, or a pre-chain schema) — never a
    silent ts-approximation. The caller routes to the explicit ``--as-of``
    event-time projection instead.

    A tick whose ``fact_cursor`` does NOT resolve to a fact (a dangling cursor —
    e.g. a merged tick referencing a fact this store never received) is NOT a
    usable anchor: the JOIN skips it and the floor scan continues to the next
    resolvable tick, so a dangling cursor yields the honest "no anchor →
    --as-of" refusal, not a downstream unknown-fact error (review finding 7b).
    """
    conn = _open_readonly(store_path, timeout=timeout)
    if conn is None:
        raise WitnessResolutionError(
            f"{store_path} is not a usable store — cannot resolve a "
            "wall-clock address against it"
        )
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
        row = (
            conn.execute(
                "SELECT t.name, t.ts, t.fact_cursor FROM ticks t "
                "JOIN facts f ON f.id = t.fact_cursor "
                "WHERE t.ts <= ? AND t.fact_cursor IS NOT NULL "
                "AND t.fact_cursor <> '' ORDER BY t.ts DESC LIMIT 1",
                (mark_ts,),
            ).fetchone()
            if "fact_cursor" in cols
            else None
        )
        if row is None:
            raise NoWitnessAnchor(
                "no witness-time anchor — no sealed tick at or before this "
                "mark carries a cursor that resolves in this store. Use "
                "--as-of for the explicit event-time projection instead."
            )
        name, ts, cursor = row
        return cursor, name, ts
    finally:
        conn.close()


@dataclass(frozen=True)
class WitnessFold:
    """The machine-readable envelope of a fold reconstructed at a witness position.

    The answering **mode is a field**, not only rendered text (A11): a consumer
    reads :attr:`mode` / :attr:`status` to know how the answer was derived
    without parsing prose. :attr:`fold` is the same :class:`~atoms.fold_state.FoldState`
    the head read returns, so existing lenses render it unchanged.
    """

    #: The reconstructed fold state (specs/edges typed under the ``at=`` ontology).
    fold: FoldState
    #: The resolved position — fact id, seq ordinal, sealing tick anchor.
    position: WitnessPosition
    #: The selector that answered. Always ``"witness"`` here (vs the ``as_of``
    #: event-time projection).
    mode: str
    #: The honesty-ladder status of the ontology used (:data:`DECLARATION_STATUSES`):
    #: ``"store"`` (folded from the prefix's ``_decl`` rows), ``"file-pre-genesis"``
    #: (no lineage opened — the current file answered, N3), ``"unhistorized"``
    #: (position predates the genesis row — genesis floor), or ``"aggregate-head"``.
    status: str
