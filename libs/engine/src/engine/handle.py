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

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from engine.declaration import _read_own_lineage
from engine.witness import GENESIS_SENTINEL

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
