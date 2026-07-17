"""VertexHandle — the daemon-shaped, in-process vertex session (0.8.0 session 2).

The missing primitive is not a background process; it is a **held, closeable,
recompilable vertex session** whose durable source of truth stays SQLite. One
consumer process opens one handle. ``ticked``, Watch, and the TUI all consume
this one contract rather than each re-loading the program per cycle.

The handle is a lifecycle + consistency boundary around:

- a cached compiled ontology plan (parse / pin-verify / compile once per epoch);
- a read-only **probe** connection for cross-process change detection;
- an immutable :class:`VertexSnapshot` (fold state + witness cursor + tick_seq +
  cumulative visible-domain count) painted without holding a transaction;
- a facts-only witness cursor and a separate ticks cursor (A1: two rowid axes,
  no invented cross-table order);
- a tick query hydrated at open (one blessed epoch scan — ``ticked``'s reconcile
  needs task→latest-close over all history);
- (S3) a write-through path with operation-fresh credentials.

**Transport (S0).** SQLite supplies durable catch-up, not cross-process
callbacks. ``PRAGMA data_version`` on the held probe connection is a cheap
invalidation *hint*; committed change is confirmed and consumed with
cursor-bearing ``facts.rowid`` / ``ticks.rowid`` queries. This is honest
polling for a committed-change event at the lowest layer, with an eventful
contract above it: consumers wake only for committed change and derive from a
lossless WAL-backed cursor.

**THE PROBE-TRANSACTION INVARIANT (contract, empirically verified).** The probe
connection must be **transaction-free between probes**. ``PRAGMA data_version``
pinned inside an *open read transaction* never advances — an external commit
stays invisible until the transaction closes, converting the design's bounded
latency into **unbounded silent staleness** (the exact failure class the handle
exists to eliminate). :class:`StoreProbe` therefore opens its connection in
autocommit mode (``isolation_level=None``) and every method leaves it
transaction-free; the only multi-statement consistency need — capturing both
heads and the new rows from one snapshot — is met by a short explicit
``BEGIN``/``COMMIT`` read transaction that is always closed before returning
(:meth:`StoreProbe.reading`). See ``test_handle_probe.py`` for the exit test.

**Reconstruction (S1+).** WAL-incremental means incremental *discovery*, not
blindly incremental *folding*. The facts rowid is the detection cursor; the
delivered state is a **full reconstruction** of the selected prefix in
``(ts, id)`` order (A7) — equal to a cold replay. In 0.8.0 the handle delegates
that reconstruction to the proven :func:`~engine.vertex_reader.vertex_fold`
``at=`` path (witness-position fold-state-as-of); insertion-aware checkpoints
that make the common case sublinear without changing the answer are the S5
ladder, not this slice.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Mapping

from engine.declaration import _read_own_lineage
from engine.witness import GENESIS_SENTINEL, WitnessPosition

if TYPE_CHECKING:  # pragma: no cover - typing only
    from atoms.fold_state import FoldItem, FoldState

# ---------------------------------------------------------------------------
# Error hierarchy — typed failures, never a bare Exception the caller can't
# discriminate. Every named row in the design's failure table has a home here.
# ---------------------------------------------------------------------------


class HandleError(Exception):
    """Base for all VertexHandle failures."""


class HandleClosed(HandleError):
    """A method was called on a closed handle. ``close()`` is idempotent; any
    later ``snapshot``/``refresh``/``receive``/``changes`` call raises this."""


class HandleInvalidated(HandleError):
    """The handle is in the INVALIDATED state — a reconstruction, recompile, or
    pin verification failed and the last-good snapshot is retained only for
    diagnostics. Normal reads/writes fail closed until a successful
    ``refresh()`` recovers or the handle is reopened. Silently serving the old
    ontology is not allowed."""


class StoreBusy(HandleError):
    """``SQLITE_BUSY``/locked during head capture or replay. A direct
    ``refresh()`` raises this rather than blocking; the ``changes()`` iterator
    retries with bounded backoff. Neither cursor is advanced."""


class StoreReplaced(HandleError):
    """The store file was replaced, its lineage changed, or the head rowid
    regressed — the held cursor no longer indexes the store it was resolved
    against. The handle must be closed and explicitly reopened; the old cursor
    is never silently reinterpreted against new bytes."""


class CursorInvalidated(HandleError):
    """A held cursor's fact id no longer resolves in the store (rebuild / slice
    / merge minted new ids). Explicit reopen / full bootstrap required."""


class AggregateHandleUnsupported(HandleError):
    """``open_vertex`` was handed a combine/discover aggregate vertex. Witness
    positions are per-store — the aggregate vector handle is S6. Open a member
    store directly, or use the one-shot aggregate read path."""


class ReadOnlyAggregate(HandleError):
    """``receive()`` on a storeless aggregate handle. Write-target resolution is
    an app/Digest concern, not the handle's."""


class ConditionalEmitUnsupported(HandleError):
    """``receive(expect=...)`` was called. The ``expect`` seam is named here so
    the handle does not foreclose the sibling conditional-emit/CAS design, but
    implementing a refresh→compare→append sequence would **not** be CAS and is
    forbidden. Post-write reconstruction canonicalizes STATE, not ADMISSION
    (the admission race is documented and deferred to the CAS sibling). Until
    that sibling lands, a conditional expectation is refused rather than
    faked."""


class ReceiveCommittedError(HandleError):
    """The fact committed but the compound live operation (boundary/tick
    persistence) then raised. The caller MUST be told the fact landed —
    retrying it as if nothing committed would duplicate data. Carries the
    committed ``fact_id``, the caught-up ``change`` (if any), and the
    originating ``cause``."""

    def __init__(self, fact_id: str, change: "ChangeBatch | None", cause: BaseException):
        self.fact_id = fact_id
        self.change = change
        self.cause = cause
        super().__init__(
            f"fact {fact_id!r} committed but the boundary/tick step failed: "
            f"{cause!r} — the fact landed; do not retry as uncommitted"
        )


# ---------------------------------------------------------------------------
# S0 data model — cursor-bearing reads. Frozen: a capture is a fixed point.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactHead:
    """The facts axis head: newest received fact by append order (A1).

    ``rowid`` is the ``facts.rowid`` cutoff (0 = empty store); ``fact_id`` the
    id at that rowid (:data:`~engine.witness.GENESIS_SENTINEL`, ``""``, when
    empty); ``count`` the total rows. The cursor is ``rowid`` — **never**
    synthesized from ``count`` (a deleted/gapped rowid would misalign the two;
    append-only keeps them dense but the code must not depend on it).
    """

    rowid: int
    fact_id: str
    count: int


@dataclass(frozen=True)
class TickHead:
    """The ticks axis head (a separate rowid domain from facts, A1). ``rowid``
    is the ``ticks.rowid`` cutoff (0 = none); ``count`` the total ticks."""

    rowid: int
    count: int


@dataclass(frozen=True)
class StoredFact:
    """A fact row with its ``rowid`` retained — the row identity the existing
    ``since()``/``since_raw()`` reads discard. ``rowid`` is the witness/detection
    axis; ``(ts, fact_id)`` is the replay order."""

    rowid: int
    fact_id: str
    kind: str
    ts: float
    observer: str
    origin: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class StoredTick:
    """A tick row with its ``rowid`` retained. A tick can wake a consumer and
    render an anchor but does not advance the facts witness position (A1)."""

    rowid: int
    tick_id: str
    name: str
    ts: float
    payload: Mapping[str, object]


@dataclass(frozen=True)
class StoreIdentity:
    """File + lineage identity of the store a probe is bound to.

    ``(device, inode)`` catches a same-path file swap that lineage alone would
    miss (an unadopted store has no lineage). ``lineage`` is the store's own
    ``_decl.genesis`` lineage id, or ``None`` when unadopted."""

    device: int
    inode: int
    lineage: str | None


def _decode_payload(text: str) -> dict:
    """Decode a stored JSON payload column to a plain dict."""
    import json

    return json.loads(text)


class StoreProbe:
    """Held read-only detection connection over one store's rowid axes (S0).

    Owns a single SQLite connection opened **read-only and in autocommit mode**
    (``isolation_level=None``) so it is transaction-free between probes — the
    correctness invariant this class exists to enforce (see the module
    docstring). All reads are point queries or a short explicit read
    transaction (:meth:`reading`) that always closes before returning.

    The probe reports *that* the store changed (``data_version``) and *which
    rows* (cursor-bearing ``facts_after``/``ticks_after``); it never folds,
    never writes, and never reconstructs — those belong to the handle.
    """

    def __init__(self, store_path: Path, *, timeout: float = 5.0) -> None:
        self._path = Path(store_path)
        self._timeout = timeout
        # Read-only URI + autocommit. mode=ro reads a WAL database (verified
        # cross-process). isolation_level=None means sqlite3 never implicitly
        # opens a transaction: the probe-transaction invariant is structural,
        # not a discipline the caller has to remember.
        try:
            self._conn: sqlite3.Connection | None = sqlite3.connect(
                f"file:{self._path}?mode=ro", uri=True, isolation_level=None,
                timeout=timeout,
            )
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise StoreBusy(f"cannot open probe on {self._path}: {exc}") from exc

    # -- invariant guards ---------------------------------------------------

    @property
    def in_transaction(self) -> bool:
        """Whether the probe connection currently holds an open transaction.

        Exposed for the invariant exit test: it MUST read ``False`` between
        every probe/refresh operation. A ``True`` here is the unbounded-
        staleness bug (``data_version`` frozen inside a pinned read snapshot).
        """
        return self._conn is not None and self._conn.in_transaction

    def _live(self) -> sqlite3.Connection:
        if self._conn is None:
            raise HandleClosed("store probe is closed")
        return self._conn

    # -- detection hint -----------------------------------------------------

    def data_version(self) -> int:
        """``PRAGMA data_version`` on the held connection — the cheap change hint.

        Bumps when *another* connection (including one in another process)
        commits; stable for reads and for this connection's own writes (the
        probe never writes). A bare read: opens no transaction, leaves the
        connection transaction-free.
        """
        conn = self._live()
        value = conn.execute("PRAGMA data_version").fetchone()[0]
        # Invariant belt-and-suspenders: a bare PRAGMA read must never pin a txn.
        assert not conn.in_transaction, (
            "probe left a transaction open after data_version() — the "
            "probe-transaction invariant is violated (unbounded staleness)"
        )
        return value

    # -- consistent capture (short read transaction) ------------------------

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        """A short explicit read transaction for a consistent multi-statement
        capture (both heads + the new rows from one snapshot).

        Opens ``BEGIN`` and always ``COMMIT``s before returning control to the
        caller's next probe, so the invariant holds: the connection is
        transaction-free *between* captures, pinned only for the duration of
        one capture. On any error the transaction is rolled back.
        """
        conn = self._live()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover - defensive
                pass
            raise
        assert not conn.in_transaction, (
            "probe left a transaction open after reading() — invariant violated"
        )

    # -- cursor-bearing reads (rowid retained, never count-derived) ---------

    def fact_head(self, conn: sqlite3.Connection | None = None) -> FactHead:
        """Newest fact by ``rowid`` + total count. ``conn`` may be a
        :meth:`reading` connection for a consistent capture."""
        c = conn or self._live()
        row = c.execute(
            "SELECT rowid, id FROM facts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        count = c.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        if row is None:
            return FactHead(rowid=0, fact_id=GENESIS_SENTINEL, count=0)
        return FactHead(rowid=row[0], fact_id=row[1], count=count)

    def facts_after(
        self, after: int, through: int, conn: sqlite3.Connection | None = None
    ) -> list[StoredFact]:
        """Facts with ``after < rowid <= through``, in append (rowid) order.

        Selection is by ``rowid`` alone (the detection cursor). Reconstruction
        re-orders these by ``(ts, id)`` — this read is the *receipt* stream, not
        the fold-replay order.
        """
        c = conn or self._live()
        rows = c.execute(
            "SELECT rowid, id, kind, ts, observer, origin, payload FROM facts "
            "WHERE rowid > ? AND rowid <= ? ORDER BY rowid",
            (after, through),
        ).fetchall()
        return [
            StoredFact(
                rowid=r[0], fact_id=r[1], kind=r[2], ts=r[3], observer=r[4],
                origin=r[5], payload=_decode_payload(r[6]),
            )
            for r in rows
        ]

    def tick_head(self, conn: sqlite3.Connection | None = None) -> TickHead:
        """Newest tick by ``rowid`` + total count (separate axis from facts)."""
        c = conn or self._live()
        row = c.execute(
            "SELECT rowid FROM ticks ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        count = c.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        if row is None:
            return TickHead(rowid=0, count=0)
        return TickHead(rowid=row[0], count=count)

    def ticks_after(
        self, after: int, through: int, conn: sqlite3.Connection | None = None
    ) -> list[StoredTick]:
        """Ticks with ``after < rowid <= through``, in append (rowid) order."""
        c = conn or self._live()
        rows = c.execute(
            "SELECT rowid, id, name, ts, payload FROM ticks "
            "WHERE rowid > ? AND rowid <= ? ORDER BY rowid",
            (after, through),
        ).fetchall()
        return [
            StoredTick(
                rowid=r[0], tick_id=r[1], name=r[2], ts=r[3],
                payload=_decode_payload(r[4]),
            )
            for r in rows
        ]

    def visible_domain_count(
        self, through: int, conn: sqlite3.Connection | None = None
    ) -> int:
        """Cumulative count of **visible domain** facts at ``rowid <= through``.

        Excludes the reserved ``_decl.*`` control receipts — the count Watch
        renders as "visible N" distinct from the receipt ``seq`` (which includes
        controls). ``through <= 0`` (empty prefix) is 0.
        """
        if through <= 0:
            return 0
        c = conn or self._live()
        return c.execute(
            "SELECT COUNT(*) FROM facts WHERE rowid <= ? AND kind NOT GLOB '_decl.*'",
            (through,),
        ).fetchone()[0]

    def identity(self) -> StoreIdentity:
        """File ``(device, inode)`` + own lineage — the store-replacement guard.

        A same-path swap changes ``(device, inode)``; lineage catches a genuine
        lineage change on an adopted store. Captured at open and re-checked on
        refresh so a replaced file raises :class:`StoreReplaced` rather than
        silently reinterpreting the old cursor against new bytes.
        """
        conn = self._live()
        st = os.stat(self._path)
        marker = _read_own_lineage(conn)
        return StoreIdentity(device=st.st_dev, inode=st.st_ino, lineage=marker)

    def close(self) -> None:
        """Release the probe connection (idempotent)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "StoreProbe":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# S1/S2 change model — the eventful contract above the polling transport.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FoldAddress:
    """A structural row address inside the fold. ``key`` is the fold key value
    for a keyed ("by") fold, or ``None`` for a non-keyed/whole-section fold."""

    kind: str
    key: str | None


@dataclass(frozen=True)
class RowChange:
    """A typed structural fold change — a highlight aid, NOT the authority.

    The published snapshot's ``fold`` is canonical (A7: every batch's fold is a
    full reconstruction). ``before``/``after`` are the folded items at
    ``address``; ``before is None`` means added, ``after is None`` means removed,
    both present means changed.
    """

    address: FoldAddress
    before: "FoldItem | None"
    after: "FoldItem | None"


@dataclass(frozen=True)
class ReceiptEvent:
    """One committed fact receipt — always delivered, even when the fold is
    unchanged. ``control`` is ``True`` for reserved ``_decl.*`` receipts; they
    are never silently hidden. ``seq`` is the ``facts.rowid``-derived receipt
    ordinal (includes controls)."""

    seq: int
    fact_id: str
    kind: str
    ts: float
    observer: str
    origin: str
    payload: Mapping[str, object]
    control: bool


@dataclass(frozen=True)
class TickEvent:
    """One committed tick. ``tick_seq`` is ``ticks.rowid`` — explicitly NOT a
    fact seq (A1: separate axes). A tick can wake a consumer and render an
    anchor but does not advance the facts witness position.

    Deviation from the advisor sketch (``tick: Tick``): carries the tick row's
    fields directly rather than a partly-reconstructed ``Tick`` object — the
    probe reads ``(rowid, id, name, ts, payload)``; a consumer needing the full
    sealed Tick (since/origin/chain) reads it via ``vertex_ticks``."""

    tick_seq: int
    tick_id: str
    name: str
    ts: float
    payload: Mapping[str, object]


@dataclass(frozen=True)
class VertexSnapshot:
    """An immutable, detached snapshot — paintable without holding a DB txn.

    ``position`` is the witness cursor (per-store; aggregate vector is S6).
    ``fold`` is the full reconstruction at that position (A7). ``tick_seq`` is
    the ticks-axis head (``ticks.rowid``). ``visible_domain_count`` is the
    cumulative count of visible domain facts (excludes ``_decl.*`` controls) —
    the "visible N" Watch/TUI render at mount, before any batch arrives (panel
    amendment F7). ``ontology_epoch`` is the resolved declaration-content
    digest; ``status`` the honesty-ladder status of the ontology used.

    Deviation: the advisor sketch's ``state_by_kind`` is not duplicated — the
    ``fold`` (``FoldState.sections``) IS the state by kind.
    """

    position: WitnessPosition
    fold: "FoldState"
    generation: int
    ontology_epoch: str
    tick_seq: int
    visible_domain_count: int
    status: str


@dataclass(frozen=True)
class ChangeBatch:
    """A delivered change — the minimum useful event, not a boolean dirty flag.

    Carries inclusive receipt range(s), every receipt (incl. visible ``_decl``
    controls), before/after witness positions, the cumulative visible-domain
    count, typed structural row changes, an ontology-change flag, an explicit
    tick list/flag, and replay-mode / catch-up diagnostics. Facts and ticks have
    separate rowid domains, so their relative order within one batch is
    disclosed as unknown — never sorted into a fake global sequence.
    """

    before: WitnessPosition
    after: WitnessPosition
    receipt_ranges: tuple[tuple[str, int, int], ...]  # (member, first_seq, last_seq)
    receipts: tuple[ReceiptEvent, ...]
    ticks: tuple[TickEvent, ...]
    rows: tuple[RowChange, ...]
    ontology_changed: bool
    tick_arrived: bool
    visible_domain_count: int
    replay_mode: str  # "full" | "checkpoint-suffix" | "tick-only"
    catching_up: bool
    oversized_group: bool
    generation: int
    idle_wake: bool = False  # S2: a deadline/idle wake with no store change


def _fold_sections(fold: "FoldState") -> dict:
    return {s.kind: s for s in fold.sections}


def _section_index(section) -> dict:
    """Index a section's items by their fold address key.

    Keyed ("by") folds index by the key-field value; other folds index by fact
    id (falling back to positional index). Used to diff two reconstructions.
    """
    out: dict = {}
    key_field = section.key_field
    for i, item in enumerate(section.items):
        if key_field is not None:
            k = str(item.payload.get(key_field, ""))
        elif item.id is not None:
            k = item.id
        else:
            k = f"#{i}"
        out[k] = item
    return out


def _diff_folds(before: "FoldState", after: "FoldState") -> tuple[RowChange, ...]:
    """Structural diff of two fold reconstructions → typed :class:`RowChange`s.

    A best-effort highlight aid (the snapshot fold stays canonical). Compares
    per-kind item sets keyed by fold address; emits added/removed/changed rows.
    """
    changes: list[RowChange] = []
    before_secs = _fold_sections(before)
    after_secs = _fold_sections(after)
    for kind in list(before_secs.keys()) + [
        k for k in after_secs if k not in before_secs
    ]:
        b_sec = before_secs.get(kind)
        a_sec = after_secs.get(kind)
        b_idx = _section_index(b_sec) if b_sec is not None else {}
        a_idx = _section_index(a_sec) if a_sec is not None else {}
        for key in list(b_idx.keys()) + [k for k in a_idx if k not in b_idx]:
            b_item = b_idx.get(key)
            a_item = a_idx.get(key)
            if b_item is a_item or b_item == a_item:
                continue
            changes.append(
                RowChange(address=FoldAddress(kind=kind, key=key),
                          before=b_item, after=a_item)
            )
    return tuple(changes)


# ---------------------------------------------------------------------------
# S1 — the held vertex session
# ---------------------------------------------------------------------------

_OPEN = "open"
_INVALIDATED = "invalidated"
_CLOSED = "closed"


def _is_control(kind: str) -> bool:
    from lang.document import is_internal_kind

    return is_internal_kind(kind)


def open_vertex(
    vertex_path: Path,
    *,
    validate_ast: bool = True,
    credentials: "CredentialProvider | None" = None,
) -> "VertexHandle":
    """Open a held, closeable vertex session over ``vertex_path`` (S1).

    Parses, verifies pins, compiles the ontology plan once, opens the store's
    read-only probe, captures the current head, and cold-reconstructs the
    opening snapshot — publishing nothing until all of that succeeds. The
    snapshot is immutable/detached so a TUI can paint it without holding a DB
    transaction.

    ``credentials`` (S3) supplies operation-fresh signers for ``receive()``;
    ``None`` opens a read-only handle. Aggregate (combine/discover) vertices are
    the S6 vector handle and are refused here.
    """
    return VertexHandle._open(
        vertex_path, validate_ast=validate_ast, credentials=credentials
    )


class VertexHandle:
    """A held, recompilable vertex session whose source of truth stays SQLite.

    Serializes ``refresh()`` and ``receive()`` under one lock and permits one
    active change iterator. Snapshot values are immutable and may be handed to a
    painter. Multiple independent subscriptions use independent handles.
    """

    def __init__(
        self,
        vertex_path: Path,
        *,
        store_path: Path | None,
        probe: StoreProbe | None,
        ast,
        specs: dict,
        credentials: "CredentialProvider | None",
    ) -> None:
        self._vertex_path = Path(vertex_path)
        self._store_path = store_path
        self._probe = probe
        self._ast = ast
        self._specs = specs
        self._credentials = credentials
        self._lock = threading.RLock()
        self._state = _OPEN
        self._snapshot: VertexSnapshot | None = None
        self._last_good: VertexSnapshot | None = None
        self._fact_cursor = 0
        self._tick_cursor = 0
        self._generation = 0
        self._file_stamp = ""
        self._tick_query: dict[str, StoredTick] = {}
        self._identity: StoreIdentity | None = None
        self._iterating = False
        # S3 lazily-built writer
        self._writer = None

    # -- construction -------------------------------------------------------

    @classmethod
    def _open(
        cls, vertex_path: Path, *, validate_ast: bool, credentials
    ) -> "VertexHandle":
        from engine.declaration import load_declaration, verify_source_pins
        from engine.compiler import compile_vertex

        vertex_path = Path(vertex_path)
        ast = load_declaration(vertex_path)
        # Refuse aggregates before pin/validate touch member resolution —
        # witness positions are per-store; the vector handle is S6.
        if ast.combine is not None or ast.discover is not None:
            raise AggregateHandleUnsupported(
                "open_vertex was handed a combine/discover aggregate vertex — "
                "witness positions are per-store; the aggregate vector handle "
                "is S6. Open a member store directly, or use the one-shot "
                "aggregate read path."
            )
        verify_source_pins(vertex_path)
        if validate_ast:
            from lang import validate

            validate(ast)
        specs = compile_vertex(ast)

        store_path = None
        probe = None
        if ast.store is not None:
            store_path = ast.store
            if not store_path.is_absolute():
                store_path = (vertex_path.parent / store_path).resolve()
            if store_path.exists():
                probe = StoreProbe(store_path)

        handle = cls(
            vertex_path, store_path=store_path, probe=probe, ast=ast,
            specs=specs, credentials=credentials,
        )
        try:
            handle._bootstrap()
        except BaseException:
            handle.close()
            raise
        return handle

    def _bootstrap(self) -> None:
        """Capture head, reconstruct, hydrate the tick query, publish (gen 0)."""
        self._file_stamp = self._compute_file_stamp()
        if self._probe is None:
            # Storeless / nonexistent store: bare head reconstruction.
            fold, status = self._reconstruct(None)
            position = WitnessPosition(
                fact_id=GENESIS_SENTINEL, rowid=0, seq=0, lineage=None,
                unadopted=True, anchor=None,
            )
            snap = VertexSnapshot(
                position=position, fold=fold, generation=0,
                ontology_epoch=self._compute_epoch(None), tick_seq=0,
                visible_domain_count=0, status=status,
            )
            self._publish(snap, fact_cursor=0, tick_cursor=0)
            return

        with self._probe.reading() as conn:
            fhead = self._probe.fact_head(conn)
            thead = self._probe.tick_head(conn)
            vdc = self._probe.visible_domain_count(fhead.rowid, conn)
            decl_head = self._decl_head_id(conn)
            all_ticks = self._probe.ticks_after(0, thead.rowid, conn)
        self._identity = self._probe.identity()
        position = self._resolve_position(fhead.fact_id)
        fold, status = self._reconstruct(position)
        self._tick_query = self._build_tick_query(all_ticks)
        snap = VertexSnapshot(
            position=position, fold=fold, generation=0,
            ontology_epoch=self._compute_epoch(decl_head), tick_seq=thead.rowid,
            visible_domain_count=vdc, status=status,
        )
        self._publish(snap, fact_cursor=fhead.rowid, tick_cursor=thead.rowid)

    # -- helpers ------------------------------------------------------------

    def _compute_file_stamp(self) -> str:
        try:
            return hashlib.sha256(self._vertex_path.read_bytes()).hexdigest()
        except OSError:
            return ""

    def _decl_head_id(self, conn: sqlite3.Connection) -> str | None:
        row = conn.execute(
            "SELECT id FROM facts WHERE kind GLOB '_decl.*' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def _compute_epoch(self, decl_head: str | None) -> str:
        """Resolved declaration-content digest: file bytes + store ``_decl`` head.

        Changes when the vertex file is edited OR a ``_decl`` ceremony lands —
        the two ways an ontology epoch turns over.
        """
        h = hashlib.sha256()
        h.update(self._file_stamp.encode())
        if decl_head:
            h.update(decl_head.encode())
        return h.hexdigest()

    def _resolve_position(self, fact_id: str) -> WitnessPosition:
        """Build the blessed position at exactly the captured head id.

        Resolving by the captured ``fact_id`` (not ``"head"``) pins the
        reconstruction rowid to the same row as the receipt range — race-free
        against a writer that commits between capture and resolve.
        """
        from engine.witness import resolve_witness_position

        assert self._store_path is not None
        return resolve_witness_position(self._store_path, fact_id)

    def _reconstruct(self, position: WitnessPosition | None):
        """Full reconstruction of the fold at ``position`` → ``(fold, status)``.

        Delegates to the proven ``vertex_fold`` ``at=`` path (A7: full replay in
        ``(ts, id)`` order, ontology resolved from the same prefix). ``None`` /
        storeless → a bare head read.
        """
        from engine.vertex_reader import vertex_fold, load_declaration_status

        if position is None or self._store_path is None:
            fold = vertex_fold(self._vertex_path)
            _ast, status = load_declaration_status(self._vertex_path)
            return fold, status
        wf = vertex_fold(self._vertex_path, at=position)
        return wf.fold, wf.status

    def _build_tick_query(self, ticks: list[StoredTick]) -> dict[str, StoredTick]:
        """name → latest tick (by append/rowid order) over the scanned ticks."""
        out: dict[str, StoredTick] = {}
        for t in ticks:
            out[t.name] = t  # ticks arrive rowid-ordered → last wins = latest
        return out

    def _publish(self, snapshot: VertexSnapshot, *, fact_cursor: int, tick_cursor: int) -> None:
        """Atomic swap of the published snapshot + cursors (all-or-nothing)."""
        self._snapshot = snapshot
        self._last_good = snapshot
        self._fact_cursor = fact_cursor
        self._tick_cursor = tick_cursor
        self._generation = snapshot.generation
        self._state = _OPEN

    def _ensure_usable(self) -> None:
        if self._state == _CLOSED:
            raise HandleClosed(f"handle for {self._vertex_path} is closed")
        if self._state == _INVALIDATED:
            raise HandleInvalidated(
                f"handle for {self._vertex_path} is invalidated — a "
                "reconstruction/recompile failed; refresh() to recover or reopen"
            )

    # -- public read surface ------------------------------------------------

    @property
    def snapshot(self) -> VertexSnapshot:
        """The current immutable snapshot. Raises if closed/invalidated."""
        self._ensure_usable()
        assert self._snapshot is not None
        return self._snapshot

    @property
    def diagnostic_snapshot(self) -> VertexSnapshot | None:
        """The last-good snapshot, retained for diagnostics even when the handle
        is invalidated. Not a live read — normal reads fail closed."""
        return self._last_good

    @property
    def state(self) -> str:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def tick_query(self) -> Mapping[str, StoredTick]:
        """Task→latest-tick map hydrated at open (one blessed epoch scan) and
        kept current by refresh. Serves ``ticked``'s reconcile, which needs
        name→latest-close over all history without re-scanning ticks from epoch
        zero every cycle."""
        return dict(self._tick_query)

    def latest_tick(self, name: str) -> StoredTick | None:
        """The most recent tick for ``name`` from the hydrated tick query."""
        return self._tick_query.get(name)

    # -- refresh ------------------------------------------------------------

    def refresh(self, *, force: bool = False) -> ChangeBatch | None:
        """Catch the handle up to the store's committed head (S1/S2).

        Captures the facts/ticks heads and the new rows in one short read
        transaction, builds a candidate snapshot off to the side, and on success
        atomically swaps runtime, snapshot, and cursors — returning the diff. On
        failure it advances neither cursor and invalidates the handle (last-good
        retained for diagnostics only).

        Returns ``None`` when nothing changed (no new facts, no new ticks, no
        ontology-stamp change) and ``force`` is false. ``force=True`` skips that
        short-circuit: it re-verifies heads and the declaration and
        full-reconstructs unconditionally (an ontology-change-shaped rebuild).

        A ``tick-only`` commit updates ``tick_seq`` and the tick query and
        returns a ``tick-only`` batch without refolding. Any ``_decl.*`` receipt
        (or a changed vertex-file stamp) forces re-resolution + recompile +
        invalidation of the compiled epoch before reconstruction.
        """
        with self._lock:
            if self._state == _CLOSED:
                raise HandleClosed(f"handle for {self._vertex_path} is closed")
            return self._refresh_locked(force=force)

    def _refresh_locked(self, *, force: bool) -> ChangeBatch | None:
        if self._probe is None:
            return self._refresh_storeless(force=force)

        # Store-replacement guard before trusting the old cursor.
        try:
            ident = self._probe.identity()
        except OSError as exc:
            raise StoreReplaced(f"store {self._store_path} vanished: {exc}") from exc
        if self._identity is not None and (
            ident.device != self._identity.device
            or ident.inode != self._identity.inode
            or ident.lineage != self._identity.lineage
        ):
            self._state = _INVALIDATED
            raise StoreReplaced(
                f"store {self._store_path} identity changed "
                f"({self._identity} -> {ident}) — reopen required; the old "
                "cursor is not reinterpreted against new bytes"
            )

        try:
            with self._probe.reading() as conn:
                fhead = self._probe.fact_head(conn)
                thead = self._probe.tick_head(conn)
                if fhead.rowid < self._fact_cursor or thead.rowid < self._tick_cursor:
                    self._state = _INVALIDATED
                    raise StoreReplaced(
                        f"head rowid regressed on {self._store_path} "
                        f"(facts {self._fact_cursor}->{fhead.rowid}, "
                        f"ticks {self._tick_cursor}->{thead.rowid}) — reopen required"
                    )
                new_facts = self._probe.facts_after(self._fact_cursor, fhead.rowid, conn)
                new_ticks = self._probe.ticks_after(self._tick_cursor, thead.rowid, conn)
                vdc = self._probe.visible_domain_count(fhead.rowid, conn)
                decl_head = self._decl_head_id(conn)
        except sqlite3.OperationalError as exc:
            raise StoreBusy(f"store busy during refresh: {exc}") from exc

        new_file_stamp = self._compute_file_stamp()
        file_changed = new_file_stamp != self._file_stamp
        has_new_facts = bool(new_facts)
        has_new_ticks = bool(new_ticks)

        if not force and not has_new_facts and not has_new_ticks and not file_changed:
            return None  # no-op

        # tick-only fast path: no facts, no ontology change, not forced.
        if not force and not has_new_facts and not file_changed and has_new_ticks:
            return self._advance_tick_only(new_ticks, thead, vdc)

        # Full path — reconstruct at the new head.
        ontology_changed = force or file_changed or any(
            _is_control(f.kind) for f in new_facts
        )
        return self._advance_full(
            fhead, thead, new_facts, new_ticks, vdc, decl_head,
            new_file_stamp, ontology_changed,
        )

    def _advance_tick_only(
        self, new_ticks: list[StoredTick], thead: TickHead, vdc: int
    ) -> ChangeBatch:
        before = self._snapshot.position
        tick_events = self._tick_events(new_ticks)
        for t in new_ticks:
            self._tick_query[t.name] = t
        snap = VertexSnapshot(
            position=before, fold=self._snapshot.fold,
            generation=self._generation + 1,
            ontology_epoch=self._snapshot.ontology_epoch, tick_seq=thead.rowid,
            visible_domain_count=vdc, status=self._snapshot.status,
        )
        self._publish(snap, fact_cursor=self._fact_cursor, tick_cursor=thead.rowid)
        return ChangeBatch(
            before=before, after=before, receipt_ranges=(),
            receipts=(), ticks=tick_events, rows=(),
            ontology_changed=False, tick_arrived=True, visible_domain_count=vdc,
            replay_mode="tick-only", catching_up=False, oversized_group=False,
            generation=snap.generation,
        )

    def _advance_full(
        self, fhead, thead, new_facts, new_ticks, vdc, decl_head,
        new_file_stamp, ontology_changed,
    ) -> ChangeBatch:
        before_pos = self._snapshot.position
        before_fold = self._snapshot.fold
        try:
            if ontology_changed:
                self._recompile(new_file_stamp)
            position = self._resolve_position(fhead.fact_id)
            fold, status = self._reconstruct(position)
        except HandleError:
            self._state = _INVALIDATED
            raise
        except Exception as exc:
            self._state = _INVALIDATED
            raise HandleInvalidated(
                f"reconstruction failed on {self._store_path}: {exc!r} — "
                "handle invalidated; last-good snapshot retained for diagnostics"
            ) from exc

        rows = _diff_folds(before_fold, fold)
        receipts = self._receipt_events(new_facts)
        tick_events = self._tick_events(new_ticks)
        for t in new_ticks:
            self._tick_query[t.name] = t
        receipt_ranges: tuple[tuple[str, int, int], ...] = ()
        if receipts:
            receipt_ranges = ((self._member_id(), receipts[0].seq, receipts[-1].seq),)

        snap = VertexSnapshot(
            position=position, fold=fold, generation=self._generation + 1,
            ontology_epoch=self._compute_epoch(decl_head), tick_seq=thead.rowid,
            visible_domain_count=vdc, status=status,
        )
        self._file_stamp = new_file_stamp
        self._publish(snap, fact_cursor=fhead.rowid, tick_cursor=thead.rowid)
        return ChangeBatch(
            before=before_pos, after=position, receipt_ranges=receipt_ranges,
            receipts=receipts, ticks=tick_events, rows=rows,
            ontology_changed=ontology_changed, tick_arrived=bool(new_ticks),
            visible_domain_count=vdc, replay_mode="full", catching_up=False,
            oversized_group=False, generation=snap.generation,
        )

    def _refresh_storeless(self, *, force: bool) -> ChangeBatch | None:
        new_file_stamp = self._compute_file_stamp()
        if not force and new_file_stamp == self._file_stamp:
            return None
        before_pos = self._snapshot.position
        before_fold = self._snapshot.fold
        try:
            self._recompile(new_file_stamp)
            fold, status = self._reconstruct(None)
        except Exception as exc:
            self._state = _INVALIDATED
            raise HandleInvalidated(
                f"storeless reconstruction failed for {self._vertex_path}: {exc!r}"
            ) from exc
        rows = _diff_folds(before_fold, fold)
        snap = VertexSnapshot(
            position=before_pos, fold=fold, generation=self._generation + 1,
            ontology_epoch=self._compute_epoch(None), tick_seq=0,
            visible_domain_count=0, status=status,
        )
        self._file_stamp = new_file_stamp
        self._publish(snap, fact_cursor=0, tick_cursor=0)
        return ChangeBatch(
            before=before_pos, after=before_pos, receipt_ranges=(), receipts=(),
            ticks=(), rows=rows, ontology_changed=True, tick_arrived=False,
            visible_domain_count=0, replay_mode="full", catching_up=False,
            oversized_group=False, generation=snap.generation,
        )

    def _recompile(self, new_file_stamp: str) -> None:
        """Re-resolve + re-verify pins + recompile the cached plan (epoch turn)."""
        from engine.declaration import load_declaration, verify_source_pins
        from engine.compiler import compile_vertex

        ast = load_declaration(self._vertex_path)
        verify_source_pins(self._vertex_path)
        self._ast = ast
        self._specs = compile_vertex(ast)
        self._file_stamp = new_file_stamp

    def _member_id(self) -> str:
        """The store's stable member id for receipt ranges (single-store: its
        resolved path). Aggregates (S6) name the advancing member."""
        return str(self._store_path) if self._store_path is not None else self._vertex_path.name

    def _receipt_events(self, facts: list[StoredFact]) -> tuple[ReceiptEvent, ...]:
        base = self._snapshot.position.seq
        out: list[ReceiptEvent] = []
        for i, f in enumerate(facts, start=1):
            out.append(ReceiptEvent(
                seq=base + i, fact_id=f.fact_id, kind=f.kind, ts=f.ts,
                observer=f.observer, origin=f.origin, payload=f.payload,
                control=_is_control(f.kind),
            ))
        return tuple(out)

    def _tick_events(self, ticks: list[StoredTick]) -> tuple[TickEvent, ...]:
        return tuple(
            TickEvent(tick_seq=t.rowid, tick_id=t.tick_id, name=t.name,
                      ts=t.ts, payload=t.payload)
            for t in ticks
        )

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Release probe + writer resources (idempotent). Detach only; no store
        mutation. Later method calls raise :class:`HandleClosed`."""
        with self._lock:
            self._state = _CLOSED
            if self._probe is not None:
                self._probe.close()
                self._probe = None
            if self._writer is not None:
                try:
                    self._writer.close()
                except Exception:  # pragma: no cover - defensive
                    pass
                self._writer = None

    def __enter__(self) -> "VertexHandle":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
