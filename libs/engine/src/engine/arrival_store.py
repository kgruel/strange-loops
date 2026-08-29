"""arrival_store — the write path for a store whose custody is its arrival log.

Cut A of the arrival substrate (decision:design/arrival-sliceA-authority):
a ``store`` locator ending in ``.arrival`` names an arrival log as the
canonical artifact, and the sqlite file at the sibling ``.db`` is a derived,
rebuildable index over it. Reads execute through the index in every mode
(arrival law 1); this class owns where a row lands FIRST.

Seam choice mirrors the log-canonical store one-for-one, and for the same
reason: ``SqliteStore.append``/``append_tick`` do the mint work and then
persist one fully-assembled row through the ``_write_fact_row`` /
``_write_tick_row`` / ``_ceremony_persist`` seam. Overriding the seam sees
the committed row for free and inherits every read method unchanged.

How a row becomes a record
--------------------------
The arrival record's ``body`` is :mod:`engine.arrival_body`'s object for the
committed row — ``payload`` rides as the stored TEXT string inside it, so
every existing fact signature and commitment hash survives the round trip,
and the index rebuilds by handing ``body`` back to the same reader. No
second encoding exists to disagree with. The record's ``k`` is the row
class (``fact`` / ``tick`` / ``batch``), never the fact's own kind — a fact
kind is data and rides inside ``body``, where it cannot collide with the
grammar's structural kinds (genesis, key introductions). Since wire v1
dropped ``body.t``, ``k`` is also the ONLY place the row class is written.

``origin``/``at`` mirror the row's own columns. ``observer`` splits by kind,
per decision:design/arrival-wire-v1-seam-triage: a FACT's names its author,
because that value selects the key that signs the record; a TICK's names
this log's custodian — the destination log's genesis observer — because a
tick has no author and its name is not an authorship claim. See
:meth:`ArrivalStore._custodian`.

Fact records are signed by the store's injected ``fact_signer`` over the
ARRIVAL content commitment — record-level attestation, resolvable by
:func:`engine.arrival.verify_authorship` from log coordinates alone. The
row's own signature (over the fact commitment) rides inside ``body`` as
data for the untouched legacy verify path; the two claims are different
subjects and both survive.

Write order per append: reconcile, stage the sqlite INSERT (uncommitted),
read the committed row back, append the record to the arrival log (durable,
fsync'd, under the log's own lock), stamp the resume mark, commit. A
failure after the log fsync rolls the index back and leaves the record
durable and unindexed — the recoverable state catch-up consumes.

Catch-up: consume, refuse — never rebuild
------------------------------------------
The index's cursor is the ratified three-field resume mark
(``arrival_lineage`` / ``arrival_offset`` / ``arrival_ordinal`` in
``store_meta``), validated at adoption by :meth:`engine.arrival.ArrivalLog.
walk_marked` — the anchor is re-checked at the site that trusts it, never
assumed. A fresh, empty index builds forward from ordinal 0 (building an
absent projection destroys nothing). Everything else that cannot be
consumed forward REFUSES with :class:`ArrivalCanonicalUnsupported`:
discarding rows and re-deriving the index is projection re-derivation, the
next cut's verb, and giving this class a repair verb now would pre-empt
that design (the same reasoning that keeps :meth:`adopt_lineage` a
refusal).

Detection scope, stated narrowly: the mark is offset-and-ordinal parity
plus the anchor checks. An out-of-band sqlite INSERT that leaves the mark
intact opens clean here — the arrival-side agreement audit is a later
cut's, alongside re-derivation. The log itself stays the authority either
way: everything the gate asks answers from the log alone.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Generic, Iterator, TypeVar

from .arrival import (
    ArrivalLog,
    GenesisRefused,
    ResumeMark,
)
from .arrival_body import (
    body_of_batch,
    body_of_fact_row,
    body_of_tick_row,
)
from .arrival_projection import has_rows, licensed_own_lineage, rows_of_record
from .jsonl_store import _as_int, _stamped_offset_current
from .residence import canonical_for, index_path_for
from .sqlite_store import (
    FACT_ALL_COLUMNS,
    FACT_COLUMN_INDEX,
    FACT_COLUMNS,
    FACT_INSERT_SQL,
    TICK_COLUMN_INDEX,
    TICK_INSERT_SQL,
    SqliteStore,
)

__all__ = [
    "ARRIVAL_LINEAGE_KEY",
    "ARRIVAL_OFFSET_KEY",
    "ARRIVAL_ORDINAL_KEY",
    "ArrivalCanonicalUnsupported",
    "ArrivalStore",
    "ensure_arrival_index",
]

# The resume mark's three store_meta keys — the ratified fields and no
# others. The old cursor custody's row counts deliberately do not return:
# the ordinal is dense, so "how many records precede this one" is ``ord``,
# by construction.
ARRIVAL_LINEAGE_KEY = "arrival_lineage"
ARRIVAL_OFFSET_KEY = "arrival_offset"
ARRIVAL_ORDINAL_KEY = "arrival_ordinal"

T = TypeVar("T")


class ArrivalCanonicalUnsupported(NotImplementedError):
    """An operation an arrival-canonical store refuses rather than fudges.

    Two families: history-mutating ops (they would rewrite index rows while
    the log kept the originals), and index states that only projection
    re-derivation can honestly resolve — which is the next cut's verb, so
    refusing keeps it designable there. A refusal names what the caller can
    do instead.
    """


class ArrivalStore(SqliteStore[T], Generic[T]):
    """A store whose canonical persistence is its arrival log.

    Same constructor as :class:`SqliteStore` plus an optional ``log_path``
    (defaults to the db path with the ``.arrival`` suffix). Opening runs
    catch-up; every append lands in the log first.

    The log must be minted before the store accepts writes — movement 1
    (genesis, with the founding key) is its custodian's act, performed with
    key material this class never sees. An unminted log opens as an empty
    store and refuses appends with the mint-first message.
    """

    def __init__(self, *, log_path: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._log = ArrivalLog(
            Path(log_path)
            if log_path is not None
            else canonical_for(self._path, "arrival")
        )
        self._coordinate_mode = "arrival"

        def _provider() -> Iterator[tuple[str, str, int, int]]:
            mark = self._read_mark()
            if mark is None:
                return
            for record in self._log.walk():
                if record["ord"] > mark.arrival_ordinal:
                    break
                ord_val = record["ord"]
                for seq, (t, row) in enumerate(rows_of_record(record)):
                    table = "facts" if t == "fact" else "ticks"
                    yield table, row[0], ord_val, seq

        self._coordinate_provider = _provider
        # The mark the last ceremony-path reconcile verified — see
        # _sync_derived_state / _ceremony_persist.
        self._reconciled_mark: ResumeMark | None = None
        try:
            self._ensure_meta_table()
            self._ensure_coordinate_schema()
            self._ensure_fact_signature_column()
            self._ensure_chain_columns()
            self.catch_up()
        except BaseException:
            # A raise out of __init__ must leave the db reopenable: an
            # uncommitted write on a leaked connection locks the file.
            conn = self._db
            try:
                conn.rollback()
            finally:
                conn.close()
            raise

    @property
    def log_path(self) -> Path:
        """The arrival log this store's sqlite index derives from."""
        return self._log.path

    @property
    def _db(self) -> sqlite3.Connection:
        """The open index connection, narrowed.

        ``SqliteStore`` nulls ``_conn`` on close; nothing in this class runs
        after close, so a None here is a caller bug and refuses loudly
        rather than surfacing as an attribute error three frames deep.
        """
        conn = self._conn
        if conn is None:
            raise RuntimeError(f"store at {self._path} is closed")
        return conn

    # ---- the resume mark ------------------------------------------------

    def _read_mark(self) -> ResumeMark | None:
        """The persisted mark, or None when any field is absent or untyped.

        All three fields or nothing: a partial mark is not a position, and
        :meth:`engine.arrival.ArrivalLog.walk_marked` re-validates whatever
        this returns at the adoption site anyway.
        """
        lineage = self._meta_get(ARRIVAL_LINEAGE_KEY)
        offset = _as_int(self._meta_get(ARRIVAL_OFFSET_KEY))
        ordinal = _as_int(self._meta_get(ARRIVAL_ORDINAL_KEY))
        if not isinstance(lineage, str) or offset is None or ordinal is None:
            return None
        return ResumeMark(
            arrival_lineage=lineage, arrival_offset=offset, arrival_ordinal=ordinal
        )

    def _stamp_mark(self, mark: ResumeMark) -> None:
        """Stage the three mark fields — the caller owns the commit."""
        self._meta_set(ARRIVAL_LINEAGE_KEY, mark.arrival_lineage)
        self._meta_set(ARRIVAL_OFFSET_KEY, mark.arrival_offset)
        self._meta_set(ARRIVAL_ORDINAL_KEY, mark.arrival_ordinal)

    # ---- catch-up --------------------------------------------------------

    def catch_up(self) -> str:
        """Reconcile the index with the log by consuming forward.

        Returns what it did: ``"synced"``, ``"tailed"``, ``"built"`` or
        ``"empty"``. Refuses (:class:`ArrivalCanonicalUnsupported`) whenever
        honesty would require discarding index rows — that is projection
        re-derivation, the next cut's verb.

        Runs on every open, so "there is nothing to do" is the case that has
        to be cheap: it answers from ``store_meta`` reads and one stat,
        taking no lock at all. Everything past that fast path takes the
        sqlite write lock —
        see the comment at the escalation for why the mark is re-read inside
        it, and why the fast path cannot weaken that.
        """
        mark = self._read_mark()
        if self._log.size() == 0:
            if has_rows(self._db) or mark is not None:
                raise ArrivalCanonicalUnsupported(
                    f"{self._path} carries index state but there is no "
                    f"arrival log at {self._log.path} — an index without its "
                    "log cannot be reconciled, and re-derivation cannot "
                    "manufacture a log: offering it here would name an "
                    "operation that destroys the only surviving artifact. "
                    "Restore the log, or open the db as a plain sqlite store"
                )
            return "empty"

        if mark is None and has_rows(self._db):
            raise ArrivalCanonicalUnsupported(
                f"{self._path} holds rows but no arrival resume mark — an "
                "index that carries state cannot be consumed forward. Run "
                "engine.arrival_projection.rederive_projections("
                f"{str(self._log.path)!r}) to discard the projection and "
                "rebuild it from the log, or open the db as a plain sqlite "
                "store"
            )

        # NOTHING TO DO — the lock-free common case. Catch-up runs on every
        # open, so an index that is already current must not take the write
        # lock: doing so would serialize every opener behind every other.
        # Both halves of the conjunct are load-bearing, because both are
        # things this method does: nothing to CONSUME (the mark names the
        # log's exact end, the same predicate :meth:`_reconcile` already
        # short-circuits on) and nothing to RESTORE (a present ``own_lineage``
        # is exactly the condition under which :meth:`_restore_own_lineage`
        # returns without staging). Drop the marker half and the ceremony
        # crash window stops recovering at the next open.
        #
        # A writer landing a record between the size() read and the return
        # makes this "synced" momentarily stale. That is the SAME staleness
        # _reconcile has always accepted on the same predicate, and it is
        # benign for the same reason: the position is re-read on every
        # append, and an append whose own coordinate does not follow the
        # reconciled one rolls back and consumes everything forward.
        if (
            mark is not None
            and mark.arrival_offset == self._log.size()
            and self._meta_get("own_lineage") is not None
        ):
            return "synced"

        # Everything above is a read. Consuming is a WRITE, and the mark it
        # decides from must be read under the same lock that the INSERTs
        # take — otherwise two processes catching the same index up both
        # read the pre-consume mark, both replay the same records, and the
        # loser's INSERT collides on the primary key and is misreported as
        # "the index holds state the log does not account for". Two
        # concurrent opens of a behind store are ordinary (a merge does two
        # of them), so the window is escalated to BEGIN IMMEDIATE and the
        # mark re-read inside it. The loser then blocks, sees the winner's
        # stamp, and consumes nothing.
        #
        # The escalation costs nothing in the common case because the fast
        # path above already returned; every opener that reaches here has
        # real work. The arrival APPEND lock is never taken: blocking every
        # writer in the system to build a projection is what this design
        # refuses.
        self._db.execute("BEGIN IMMEDIATE")
        try:
            mark = self._read_mark()
            resumed, records = self._log.walk_marked(mark)
            if mark is not None and resumed == 0:
                raise ArrivalCanonicalUnsupported(
                    f"{self._path} carries an arrival resume mark the log at "
                    f"{self._log.path} rejects — the index cannot be consumed "
                    "forward. Run engine.arrival_projection."
                    f"rederive_projections({str(self._log.path)!r}) to discard "
                    "the projection and rebuild it from the log"
                )
            last_mark: ResumeMark | None = None
            for record, record_mark in records:
                self._index_record(record)
                last_mark = record_mark
            self._restore_own_lineage()
            if last_mark is not None:
                self._stamp_mark(last_mark)
        except BaseException:
            self._db.rollback()
            raise
        # Always closed, even when nothing was staged: BEGIN IMMEDIATE holds
        # the write lock until the transaction ends, and a return that left
        # it open would wedge every other writer.
        self._db.commit()
        if last_mark is None:
            return "synced"
        return "built" if mark is None else "tailed"

    def _restore_own_lineage(self) -> bool:
        """Stage the ``own_lineage`` projection when it is ABSENT.

        The one residue of the ceremony crash window. ``_ceremony_persist``
        makes the genesis record durable and stages the marker; a crash
        before the caller's COMMIT rolls back the ``_decl.genesis`` INSERT,
        the marker and the mark together. Catch-up tails the record forward
        and the ROW recovers itself — the marker does not, because it is
        not in the log's rows. Restoring it here is a pure projection
        restore, and it is legal automatically for the same reason building
        an absent index is: absent→present destroys nothing.

        A PRESENT marker is never touched, so this path can never overwrite
        an identity claim. Judging a present, disagreeing marker is
        :func:`engine.arrival_projection.rederive_projections`'s, where the
        stamp would be destructive.

        Returns whether it staged a write, so the caller knows whether a
        commit is owed on the otherwise-no-op path.
        """
        if self._meta_get("own_lineage") is not None:
            return False
        try:
            lineage = self._log.lineage()
        except GenesisRefused:
            return False
        own = licensed_own_lineage(self._db, lineage)
        if own is None:
            return False
        self._meta_set("own_lineage", own)
        return True

    def _index_record(self, record: dict) -> None:
        """Stage one record's rows into the index — verbatim, no mint
        machinery, no signer; signatures ride as stored in the body.

        What a record expands to is :func:`engine.arrival_projection.
        rows_of_record`'s answer and not a second copy of it: the indexer
        and the re-deriver disagreeing about a record is the one
        disagreement this design cannot tolerate.
        """
        ord_val = record["ord"]
        for seq, (t, row) in enumerate(rows_of_record(record)):
            try:
                self._db.execute(
                    FACT_INSERT_SQL if t == "fact" else TICK_INSERT_SQL,
                    (*row, ord_val, seq),
                )
            except Exception as exc:
                raise ArrivalCanonicalUnsupported(
                    f"the index at {self._path} refuses {t} {row[0]!r} from "
                    f"ordinal {record['ord']} ({exc}) — it holds state the "
                    "log does not account for. Run engine.arrival_projection."
                    f"rederive_projections({str(self._log.path)!r}) to "
                    "discard the projection and rebuild it from the log"
                ) from exc

    def _reconcile(self) -> ResumeMark | None:
        """Refuse to stamp past a durable record the index has not consumed.

        Same posture as the log-canonical store: a long-lived handle never
        reopens, so every append reconciles first. Cheap in the common case
        — one meta read and one stat.

        Returns the mark this reconcile verified or (via catch-up) stamped,
        so the write paths consume the reconciled position instead of
        re-reading ``store_meta`` — the interloper checks are DEFINED
        against exactly this pre-append mark. ``None`` only when the log is
        empty, where no append can succeed anyway.
        """
        mark = self._read_mark()
        if mark is not None and mark.arrival_offset == self._log.size():
            return mark
        self.catch_up()
        return self._read_mark()

    def _sync_derived_state(self) -> None:
        """Reconcile before mint logic reads chain state off the index.

        The reconciled mark is kept for :meth:`_ceremony_persist`, which
        runs later inside the same ceremony transaction and must pin its
        append to the head the CEREMONY reconciled against — not to
        whatever the mark says by the time it runs.
        """
        self._reconciled_mark = self._reconcile()

    # ---- the write path --------------------------------------------------

    def _custodian(self) -> str:
        """The label a record this store MINTS puts in its envelope observer.

        The destination log's own genesis observer — ruling 2 of
        decision:design/arrival-wire-v1-seam-triage. A tick has no author:
        it is the custodian's fold engine producing a record, and the
        envelope observer says so. The previous spelling put the tick's
        NAME there, which read as an authorship claim a name cannot make.

        Scoped to what it claims, and no further. The label is TRUE but
        UNVERIFIED, on purpose: tick outer signatures are deferred (ruling
        3), so no tick's envelope observer is ever looked up in the key
        registry — ``_resolve`` gates on a signature being present and
        every tick mint passes ``signer=None``. An unverified true claim is
        what wire v1 pins; a verifiable one is a later design session's.

        Fact records are untouched by this: their envelope observer stays
        the row's author, because that value SELECTS THE SIGNING KEY
        (``fact_signer_for`` resolves ``keys/<observer>/ed25519.key``) and
        re-deriving it as custody would re-key every fact signature from
        author to custodian — a decision explicitly not made here.

        Reads through the genesis memo, so a store minting many ticks pays
        one validation. The refusal is re-spelled rather than surfaced raw
        for the reason :meth:`_genesis_lineage_id` re-spells its own: this
        class promises an unminted log refuses appends with the mint-first
        message, and "the log does not exist" is that state described from
        the wrong end.
        """
        try:
            return self._log.genesis()["observer"]
        except GenesisRefused as exc:
            raise GenesisRefused(
                f"{self._log.path} is empty — mint a genesis first; a "
                "record's envelope observer is the log's own genesis "
                "observer, so there is no custodian to name until movement "
                "1 has named one"
            ) from exc

    def _write(self, sql: str, row: tuple, encode_row, is_fact: bool) -> str | None:
        """Stage the INSERT, make the record durable in the log, stamp, commit.

        The INSERT runs first, uncommitted, so a rejected row fails before a
        byte reaches the log and a refused write can never orphan a record.
        The record's body is the arrival body grammar's object for the
        COMMITTED read-back row — the index and the log must derive-match. The record's arrival signature comes from
        the injected ``fact_signer`` over the arrival commitment; the same
        callable, a different digest, and the composing layer's
        domain-separation prefix already binds both to this store family.

        A record another writer lands in the log between the reconcile and
        the append would otherwise be skipped forever: our record arrives
        one ordinal later and the stamped mark would claim consumption it
        never performed. The append's own coordinate is the tell — when it
        is not the reconciled ordinal plus one, the staged INSERT rolls
        back (our record is already durable in the log) and catch-up
        consumes everything forward instead, the interloper included. The
        returned signature is the committed row's either way: catch-up
        re-inserts the identical row verbatim from the record's body.
        """
        consumed = self._reconcile()
        # Grammar pre-flight on the ASSEMBLED row, NOT dead work: sqlite's
        # column affinity coerces (e.g. a string ts commits as REAL), so the
        # committed-row encode below would ACCEPT a row the grammar refuses
        # — this is the gate that fails at the append site, where it is
        # attributable, instead of laundering the value.
        encode_row(row)
        try:
            table = "facts" if is_fact else "ticks"
            expected_ordinal = 0 if consumed is None else consumed.arrival_ordinal + 1
            staged_row = (*row, expected_ordinal, 0)
            self._db.execute(sql, staged_row)
            committed_row = self._committed_full_row(
                table, row[0]
            )
            sig_col_idx = (
                FACT_COLUMN_INDEX if is_fact else TICK_COLUMN_INDEX
            )["signature"]
            committed = committed_row[sig_col_idx]
            body = encode_row(committed_row[:-2])
            record, mark = self._log.append_marked(
                "fact" if is_fact else "tick",
                body,
                observer=committed_row[3] if is_fact else self._custodian(),
                origin=committed_row[4],
                at=committed_row[2],
                signer=self._fact_signer if is_fact else None,
            )
            # consumed is None on one REACHABLE interleave: the log was
            # empty at reconcile time and another process minted the
            # genesis inside the reconcile->append gap. Legal interleave is
            # refuse-or-consume, never crash — so a missing reconciled mark
            # takes the same gap path as a stale one: roll back and consume
            # everything forward, the fresh genesis included.
            if consumed is None or record["ord"] != consumed.arrival_ordinal + 1:
                self._db.rollback()
                self.catch_up()
                return committed
            self._stamp_mark(mark)
            self._db.commit()
            return committed
        except BaseException:
            self._db.rollback()
            raise


    def _allocate_ceremony_coordinates(
        self, conn: Any, count: int
    ) -> list[tuple[int, int]]:
        consumed = self._reconciled_mark
        expected_ordinal = 0 if consumed is None else consumed.arrival_ordinal + 1
        return [(expected_ordinal, idx) for idx in range(count)]

    def _write_fact_row(self, row: tuple) -> str | None:
        return self._write(FACT_INSERT_SQL, row, body_of_fact_row, True)

    def _write_tick_row(self, row: tuple) -> str | None:
        return self._write(TICK_INSERT_SQL, row, body_of_tick_row, False)

    def _ceremony_persist(self, rows: list[tuple]) -> None:
        """Make a declaration ceremony canonical: ONE arrival record, stamped.

        Runs inside the ceremony's open transaction after every check
        passed, immediately before the caller's COMMIT. One row rides as a
        ``fact`` record; several as one ``batch`` record — one record is the
        log's atomicity unit, so recovery can never expose a partial
        ceremony.

        ``following`` pins the append to the head the ceremony reconciled
        against: a record another writer lands mid-ceremony REFUSES the
        append before any byte is written (``AppendRejected``), the
        caller's transaction rolls back with the log byte-identical, and
        the ceremony is simply retryable — unlike :meth:`_write`, this path
        cannot resolve a gap after the fact, because the record it would
        have made durable is the ceremony itself.
        """
        persisted_rows = [
            r[:-2] if len(r) == len(FACT_ALL_COLUMNS) else r for r in rows
        ]
        if len(persisted_rows) > 1:
            k, body = "batch", body_of_batch(persisted_rows)
        else:
            k, body = "fact", body_of_fact_row(persisted_rows[0])
        consumed = self._reconciled_mark
        _, mark = self._log.append_marked(
            k,
            body,
            observer=rows[0][3],
            origin=rows[0][4],
            at=rows[0][2],
            signer=self._fact_signer,
            following=None if consumed is None else consumed.arrival_ordinal,
        )
        self._stamp_mark(mark)

    def _declaration_head_in_txn(
        self, conn: Any, lineage_id: str
    ) -> tuple[int, str] | None:
        """The ``(record_ordinal, id)`` of the newest self-lineage declaration.

        The CAS token names the axis this store actually accretes on. Its
        first coordinate is the ARRIVAL ordinal of the log record whose
        expansion carries the row — so the rows of one batch record (a
        multi-change edit ceremony) share an ordinal and the tie-break falls
        to the fact id, which is the one place this axis is observably not
        the index's rowid.

        The predicate is the base class's, verbatim: own genesis
        participates, and a foreign ``_decl.*`` row is excluded by the
        lineage its payload stamps. Only the coordinate changed.

        The log answers, because the log is the store. No ordinal column, no
        side table: a second place the coordinate is written is a second
        thing that can disagree with the log, and the indexer/re-deriver
        disagreement is the one this family does not tolerate. The cost is
        one forward walk per read — twice per edit ceremony, and ceremonies
        are rare.

        Bounded at the reconciled position rather than at end-of-file. The
        ceremony reads this INSIDE its transaction, having reconciled
        against a specific prefix; a record another writer lands mid-ceremony
        is :meth:`_ceremony_persist`'s ``following`` refusal to judge, not
        this read's, and the bound also keeps a walk from reaching a tail
        that is mid-append.
        """
        mark = self._read_mark()
        if mark is None:
            return None
        best: tuple[int, str] | None = None
        for record in self._log.walk():
            ordinal = record["ord"]
            if ordinal > mark.arrival_ordinal:
                break
            for kind_of_row, row in rows_of_record(record):
                if kind_of_row != "fact":
                    continue
                fact_id, kind, payload_text = row[0], row[1], row[5]
                if not kind.startswith("_decl."):
                    continue
                if fact_id == lineage_id:
                    pass  # own genesis participates
                else:
                    try:
                        payload = json.loads(payload_text)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if payload.get("lineage") != lineage_id:
                        continue
                candidate = (ordinal, fact_id)
                if best is None or candidate > best:
                    best = candidate
        return best

    # ---- ceremonies -------------------------------------------------------

    def _genesis_lineage_id(self) -> str:
        """The declaration genesis row projects the ARRIVAL lineage.

        ``store_meta.own_lineage`` is stamped with this same value by the
        base ceremony, so identity is written from arrival, read from
        sqlite, and re-derivable from the log with every projection gone —
        the strongest assertion in the cut's gate. The row id being the
        lineage id preserves the legacy invariant the CAS head-tracking
        keys off.
        """
        try:
            return self._log.lineage()
        except GenesisRefused as exc:
            raise GenesisRefused(
                f"{self._log.path} has no arrival genesis — the declaration "
                "absorb is movement 2; mint the arrival genesis (movement 1, "
                "with the founding key) first"
            ) from exc

    def _genesis_payload(self, protocol: int, documents: list) -> dict[str, Any]:
        """``{protocol, documents}`` — the era pins dissolve.

        The old cursor pin's claim ("everything before me predates
        historization") is ``ord < N``, structural under the dense ordinal;
        the old chain-head pin was a tick-row hash, a projection artifact a
        signed immutable record must not rest an integrity claim on
        (arrival law 1). A later cut that wants a tick anchor names an
        arrival coordinate, not a row hash.
        """
        return {"protocol": protocol, "documents": list(documents)}

    def adopt_lineage(self, lineage_id: str | None = None) -> dict[str, Any]:
        """Refused: an arrival store's identity is structural at ordinal 0.

        There is nothing to adopt — the log's genesis IS the identity, and
        foreign genesis records cannot exist above ordinal 0. Restamping the
        ``own_lineage`` projection marker from the log is projection repair,
        which :meth:`catch_up` does when the marker is absent and
        :func:`engine.arrival_projection.rederive_projections` does when it
        re-derives everything; deleting this ceremony would break the legacy
        modes that still need it. Refusal keeps both doors open.
        """
        raise ArrivalCanonicalUnsupported(
            "adopt is not a ceremony an arrival-canonical store has: "
            "identity is the arrival genesis at ordinal 0, structurally — "
            "there is nothing to choose between. If the own_lineage marker "
            "is missing, reopening the store restores it from the log "
            "(catch-up), and engine.arrival_projection.rederive_projections "
            "restores it alongside every other projection row."
        )

    def reanchor(self, *args: Any, **kwargs: Any):  # noqa: D102
        # PERMANENT, not deferred (cut B). The queued log-rewrite ceremony is
        # RETIRED: rewriting a log is not an operation in this model, and the
        # rowid-identity property the projections rest on is exactly what a
        # rewrite would destroy. The one case that could break re-derivation
        # is a truncated or rewritten log, and this is the method that would
        # have made it reachable.
        raise ArrivalCanonicalUnsupported(
            "reanchor is not an operation an arrival-canonical store has, and "
            "it is not a later slice's either: it would rewrite index rows "
            "while the arrival log kept the originals, so the index would "
            "stop being a function of the log. Rewriting a log is not an "
            "operation in this model."
        )


def ensure_arrival_index(canonical: Path) -> Path:
    """Materialize — and catch up — the sqlite index for an arrival log.

    The fresh-clone case: the log is the store, the derived ``.db`` is not
    tracked, so the first read finds no index. Opening an
    :class:`ArrivalStore` runs catch-up (an absent index builds forward from
    ordinal 0); closing immediately leaves no handle behind. A no-op when
    the log is missing or the index is already current
    (:func:`engine.jsonl_store._stamped_offset_current`, keyed on the
    arrival cursor).
    """
    canonical = Path(canonical)
    index = index_path_for(canonical)
    if not canonical.exists():
        return index
    if index.exists() and _stamped_offset_current(index, canonical, ARRIVAL_OFFSET_KEY):
        return index
    store: ArrivalStore[Any] = ArrivalStore(
        path=index,
        log_path=canonical,
        serialize=lambda d: d,
        deserialize=lambda d: d,
    )
    store.close()
    return index
