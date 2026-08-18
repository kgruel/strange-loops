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
The arrival record's ``body`` is the line codec's object for the committed
row, verbatim — ``payload`` rides as the stored TEXT string inside it, so
every existing fact signature and commitment hash survives the round trip,
and a later cut can rebuild the index by handing ``body`` straight back to
the codec. No second encoding exists to disagree with. The record's ``k``
is the row class (``fact`` / ``tick`` / ``batch``), never the fact's own
kind — a fact kind is data and rides inside ``body``, where it cannot
collide with the grammar's structural kinds (genesis, key introductions).
``observer``/``origin``/``at`` mirror the row's authorship columns (a tick
has no observer; its record carries the tick's name there, which is the
authorship a tick has).

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
from typing import Any, Generic, TypeVar

from .arrival import (
    GENESIS_KIND,
    KEY_INTRODUCTION_KIND,
    ArrivalLog,
    GenesisRefused,
    ResumeMark,
)
from .arrival_projection import has_rows
from .jsonl_codec import (
    records_from_object,
    serialize_batch,
    serialize_fact_row,
    serialize_tick_row,
)
from .jsonl_store import _as_int, _stamped_offset_current
from .residence import canonical_for, index_path_for
from .sqlite_store import (
    FACT_INSERT_SQL,
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

# Record classes this index consumes into rows, and the structural kinds it
# walks past. Anything else refuses: a kind this indexer does not know is
# not a kind it may silently drop. The row-class literals mirror the line
# codec's "t" discriminators (its sibling idiom); the structural kinds are
# the grammar's own constants.
_ROW_KINDS = frozenset(("fact", "tick", "batch"))
_STRUCTURAL_KINDS = frozenset((GENESIS_KIND, KEY_INTRODUCTION_KIND))

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
        # The mark the last ceremony-path reconcile verified — see
        # _sync_derived_state / _ceremony_persist.
        self._reconciled_mark: ResumeMark | None = None
        try:
            self._ensure_fact_signature_column()
            self._ensure_chain_columns()
            self._ensure_meta_table()
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
        """
        mark = self._read_mark()
        if self._log.size() == 0:
            if has_rows(self._db) or mark is not None:
                raise ArrivalCanonicalUnsupported(
                    f"{self._path} carries index state but there is no "
                    f"arrival log at {self._log.path} — an index without its "
                    "log cannot be reconciled; restore the log or open the "
                    "db as a plain sqlite store"
                )
            return "empty"

        if mark is None and has_rows(self._db):
            raise ArrivalCanonicalUnsupported(
                f"{self._path} holds rows but no arrival resume mark — "
                "re-deriving an existing index from the log is projection "
                "re-derivation, a later cut; open the db as a plain sqlite "
                "store, or start from an absent index"
            )

        resumed, records = self._log.walk_marked(mark)
        if mark is not None and resumed == 0:
            raise ArrivalCanonicalUnsupported(
                f"{self._path} carries an arrival resume mark the log at "
                f"{self._log.path} rejects — the index cannot be consumed "
                "forward, and re-deriving it is projection re-derivation, a "
                "later cut"
            )

        consumed = 0
        last_mark: ResumeMark | None = None
        try:
            for record, record_mark in records:
                self._index_record(record)
                consumed += 1
                last_mark = record_mark
        except BaseException:
            self._db.rollback()
            raise
        if last_mark is None:
            return "synced"
        self._stamp_mark(last_mark)
        self._db.commit()
        return "built" if mark is None else "tailed"

    def _index_record(self, record: dict) -> None:
        """Stage one record's rows into the index — verbatim, no mint
        machinery, no signer; signatures ride as stored in the body."""
        kind = record["k"]
        if kind in _STRUCTURAL_KINDS:
            return
        if kind not in _ROW_KINDS:
            raise ArrivalCanonicalUnsupported(
                f"record kind {kind!r} at ordinal {record['ord']} is not one "
                "this index knows how to consume — refusing rather than "
                "silently dropping it"
            )
        for t, row in records_from_object(record["body"]):
            try:
                self._db.execute(
                    FACT_INSERT_SQL if t == "fact" else TICK_INSERT_SQL, row
                )
            except Exception as exc:
                raise ArrivalCanonicalUnsupported(
                    f"the index at {self._path} refuses {t} {row[0]!r} from "
                    f"ordinal {record['ord']} ({exc}) — it holds state the "
                    "log does not account for, and resolving that is "
                    "projection re-derivation, a later cut"
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

    def _write(self, sql: str, row: tuple, serialize_row, is_fact: bool) -> str | None:
        """Stage the INSERT, make the record durable in the log, stamp, commit.

        The INSERT runs first, uncommitted, so a rejected row fails before a
        byte reaches the log and a refused write can never orphan a record.
        The record serializes the COMMITTED read-back row — the index and
        the log must derive-match. The record's arrival signature comes from
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
        # Codec pre-flight on the ASSEMBLED row, NOT dead work: sqlite's
        # column affinity coerces (e.g. a string ts commits as REAL), so the
        # committed-row serialize below would ACCEPT a row the codec refuses
        # — this is the gate that fails at the append site, where it is
        # attributable, instead of laundering the value.
        serialize_row(row)
        try:
            self._db.execute(sql, row)
            committed_row = self._committed_full_row(
                "facts" if is_fact else "ticks", row[0]
            )
            committed = committed_row[-1]  # signature is the last column
            body = json.loads(serialize_row(committed_row))
            record, mark = self._log.append_marked(
                "fact" if is_fact else "tick",
                body,
                observer=committed_row[3] if is_fact else committed_row[1],
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

    def _write_fact_row(self, row: tuple) -> str | None:
        return self._write(FACT_INSERT_SQL, row, serialize_fact_row, True)

    def _write_tick_row(self, row: tuple) -> str | None:
        return self._write(TICK_INSERT_SQL, row, serialize_tick_row, False)

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
        if len(rows) > 1:
            k, line = "batch", serialize_batch(rows)
        else:
            k, line = "fact", serialize_fact_row(rows[0])
        consumed = self._reconciled_mark
        _, mark = self._log.append_marked(
            k,
            json.loads(line),
            observer=rows[0][3],
            origin=rows[0][4],
            at=rows[0][2],
            signer=self._fact_signer,
            following=None if consumed is None else consumed.arrival_ordinal,
        )
        self._stamp_mark(mark)

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
        a later cut's verb; deleting this ceremony would break the legacy
        modes that still need it. Refusal now keeps both doors open.
        """
        raise ArrivalCanonicalUnsupported(
            "adopt is not a ceremony an arrival-canonical store has: "
            "identity is the arrival genesis at ordinal 0, structurally — "
            "there is nothing to choose between. If the own_lineage marker "
            "is missing, restoring it from the log is projection repair, a "
            "later cut."
        )

    def reanchor(self, *args: Any, **kwargs: Any):  # noqa: D102
        # Same scope pin as the log-canonical store: reanchor rewrites index
        # rows the log keeps the originals of.
        raise ArrivalCanonicalUnsupported(
            "reanchor is not wired for an arrival-canonical store: it would "
            "rewrite index rows while the arrival log kept the originals, so "
            "the index would stop being a function of the log."
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
