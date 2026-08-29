"""arrival_file_backend — the file adapter for the storage-neutral contract.

Slice 2 of the arrival break (``design:arrival-break-slice2-backend-contract``
§A.2). backend-contract.html §09 puts it plainly: "The current ArrivalLog
becomes an adapter." This module is that adapter, and it is a WRAPPER — it
adds no storage behaviour, moves no code out of :mod:`engine.arrival`, and does
not modify :class:`engine.arrival_store.ArrivalStore`. Everything below either
delegates or translates, which is what keeps the fourteen arrival test files
answering about the same code they answered about before.

Two halves, and the split is the contract's (§03), not a convenience:

* :class:`FileLedger` wraps :class:`engine.arrival.ArrivalLog` — the custody
  half, everything that can change what the lineage holds.
* :class:`FileQuery` wraps the PROJECTION — the sqlite index, reached through
  the read-only :class:`engine.store_reader.StoreReader` and nothing else.

The separation is enforced by construction rather than by discipline:
:class:`FileQuery` takes an index PATH and builds its own read handle, so there
is no constructor parameter through which a ledger could be handed in, and no
attribute on a query instance from which an append could be reached. A unit
test pins it (``test_arrival_contract.py``). Deliberately a test and not a
numbered architecture rule — one adapter is not yet a pattern, and the second
backend is where such a rule would earn its keep.

**What this adapter does not implement yet, stated rather than stubbed.**
``replicate`` and ``export`` are declared on
:class:`engine.arrival_contract.ArrivalLedger` and are absent here; WP2 builds
them. :meth:`FileLedger.capabilities` matches that exactly — no Replica
profile, no export codecs — because a capability report that advertised an
operation the adapter does not have is the false claim §12's conformance suite
exists to catch. An ``NotImplementedError`` stub would be the same lie with a
traceback attached, plus residue for WP2 to sweep.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .arrival import (
    GRAMMAR_VERSION,
    ArrivalLog,
    Entry,
    StaleHead,
)
from .arrival_contract import (
    AtomicLimitExceeded,
    Capabilities,
    Commit,
    DurabilityProfile,
    DurabilityReceipt,
    Full,
    Head,
    HeadMismatch,
    Incremental,
    NotAuthority,
    Open,
    Profile,
    RecordDraft,
    VerificationLevel,
    VerifyScope,
    Watermark,
)
from .arrival_store import (
    ARRIVAL_LINEAGE_KEY,
    ARRIVAL_ORDINAL_KEY,
)
from .store_reader import StoreReader

__all__ = ["FileLedger", "FileQuery"]


# What an append has established before it reports success. The mechanism is
# named because the profile alone does not tell an operator what to check:
# §05's callout is explicit that this contract is LOCAL POSIX storage, and
# that moving the same bytes onto NFS does not inherit it.
_DURABILITY = DurabilityReceipt(
    profile=DurabilityProfile.HOST,
    mechanism="advisory flock, one write, one fsync, on local POSIX storage",
)


def _head_of(record: Mapping[str, Any]) -> Head:
    """A record's coordinate as a contract :class:`Head`.

    The one place the wire field names meet the neutral type. Keeping it to
    one function is what lets the rest of this module talk in ``Head`` and
    the log keep talking in records.
    """
    return Head(
        lineage=record["lin"], ordinal=record["ord"], record_hash=record["rh"]
    )


class FileLedger:
    """Custody over one ``.arrival`` log, in the contract's vocabulary.

    Satisfies :class:`engine.arrival_contract.ArrivalLedger` apart from
    ``replicate`` and ``export``, which are WP2's — see the module docstring.

    **Which verification level each operation invokes** (§06 requires a
    backend to say): :meth:`read`, :meth:`scan` and :meth:`head` all reach
    their answer through :meth:`engine.arrival.ArrivalLog.walk`, so they
    invoke FULL — the log's read path establishes that everything before a
    coordinate is intact before it will name what is at it. Only
    :meth:`verify` with an :class:`~engine.arrival_contract.Open` scope is
    cheap. That is a property of this backend, not of the contract; a backend
    with stored head metadata would answer :meth:`head` at OPEN.
    """

    def __init__(
        self, log: ArrivalLog, *, max_atomic_records: int | None = None
    ) -> None:
        """``max_atomic_records`` is None for "no configured limit".

        Different from a limit of one: §04 requires every backend to support
        one record and lets it advertise more. The file append holds the
        whole group under one lock and one fsync with no limit of its own, so
        an unset limit is the honest default — but a deployment that wants
        one gets a refusal that fires BEFORE any mutation, which is what §04
        asks for and what §12's configured-limit gate exercises.
        """
        self._log = log
        self._max_atomic_records = max_atomic_records

    # -- custody -----------------------------------------------------------

    def mint(self, options: Mapping[str, Any]) -> Head:
        """Exclusively create one signed genesis and return head 0.

        ``options`` are adapter-interpreted, the same way §02's ``location``
        is: this backend forwards them to
        :meth:`engine.arrival.ArrivalLog.mint`, which needs an observer, a
        signer and the founding public key.

        A second mint raises ``GenesisRefused`` — a backend exception, not a
        contract refusal, because the ratified refusal set has no member for
        "already minted". Passing it through is the honest option; the
        alternative is choosing one of the five and claiming something the
        evidence does not support.
        """
        log = ArrivalLog.mint(self._log.path, **dict(options))
        self._log = log
        return _head_of(log.genesis())

    def append(
        self, expected: Head | None, drafts: Sequence[RecordDraft]
    ) -> Commit:
        """Compare the full head, then assign and commit — indivisibly (§04).

        The whole transition is :meth:`ArrivalLog.append_marked_many`: the
        fence, the full-head compare (F1), coordinate assignment, one write
        and one fsync. Nothing is re-implemented here, which is the point —
        the append fence is ``flock``-based and per-open-file-description,
        and a second appender beside it would be a second way to be wrong.

        ``before`` is derived rather than re-read: the first record's
        ``prev`` IS the predecessor's record hash and its ordinal minus one
        IS the predecessor's ordinal, so the head the append actually landed
        on is known exactly, without a second trip past a log another writer
        is free to extend.
        """
        if not drafts:
            raise ValueError(
                "append was handed no drafts — an empty append is a caller "
                "bug, not a no-op to absorb"
            )
        if (
            self._max_atomic_records is not None
            and len(drafts) > self._max_atomic_records
        ):
            raise AtomicLimitExceeded(
                f"{len(drafts)} records exceeds this backend's configured "
                f"atomic limit of {self._max_atomic_records} — refused before "
                "any mutation, because splitting the request across "
                "transactions would turn one logical group into several"
            )
        for draft in drafts:
            if draft.signature is not None:
                raise NotImplementedError(
                    "this adapter's append builds unsigned records: its wrap "
                    "target, ArrivalLog.append_marked_many, assigns no "
                    "signature, and Entry deliberately carries no signer "
                    "field. A record that must arrive with an authored "
                    "signature goes through the ceremony path, which injects "
                    "a signer, or arrives pre-coordinated through replicate"
                )

        entries = [
            Entry(
                k=draft.kind,
                body=dict(draft.body),
                observer=draft.observer,
                origin=draft.origin,
                at=draft.authored_at,
            )
            for draft in drafts
        ]
        try:
            records, _mark = self._log.append_marked_many(
                entries, following=expected
            )
        except StaleHead as exc:
            # 1:1, and only from the CAS subclass. The parent AppendRejected
            # is also raised for placement faults in a carried-in candidate,
            # and mapping those to HeadMismatch would assert something about
            # the head that the fault does not say.
            raise HeadMismatch(str(exc)) from exc

        first, last = records[0], records[-1]
        return Commit(
            before=Head(
                lineage=first["lin"],
                ordinal=first["ord"] - 1,
                record_hash=first["prev"],
            ),
            records=tuple(records),
            after=_head_of(last),
            durability=_DURABILITY,
        )

    # -- reads through the ledger ------------------------------------------

    def head(self, lineage: str | None = None) -> Head:
        """The currently complete head.

        Absence and corruption surface as this backend's own
        ``GenesisRefused`` / ``ArrivalCorrupt`` — see :meth:`mint` for why
        they are not translated. A ``lineage`` that is not this log's IS one
        of the ratified refusals: asking a ledger about a lineage it does not
        hold is an operation it may not perform.
        """
        record = self._log.head()
        if lineage is not None and record["lin"] != lineage:
            raise NotAuthority(
                f"{self._log.path} holds lineage {record['lin']}, not the "
                f"requested {lineage} — this ledger is not that lineage's "
                "authority, and opening a path never makes it one"
            )
        return _head_of(record)

    def head_at(self, watermark: Watermark) -> Head:
        """The full head a projection's watermark names.

        The resolution §07 needs and the query half cannot perform: a
        watermark is a coordinate, and only the ledger holds the record whose
        hash completes it. It answers or it refuses — a watermark the log
        will not vouch for is a disagreement between projection and ledger,
        and answering it with a manufactured head would hide exactly that.
        """
        record = self._log.read(watermark.ordinal)
        if record["lin"] != watermark.lineage:
            raise NotAuthority(
                f"the projection reports lineage {watermark.lineage}, but "
                f"{self._log.path} holds {record['lin']} — the projection is "
                "not a projection of this log"
            )
        return _head_of(record)

    def read(self, coordinate: int) -> Mapping[str, Any]:
        """The exact record, after establishing its membership in the lineage.

        Membership is not a lookup: the walk that reaches the coordinate has
        verified that everything before it chains, because a record whose
        predecessors do not chain is not at the coordinate it claims.
        """
        return self._log.read(coordinate)

    def scan(
        self, *, after: int | None = None, through: Head | None = None
    ) -> Iterator[Mapping[str, Any]]:
        """An ordered, consistent prefix range and no later record (§06).

        ``through`` is a CAPTURED head, and capturing is what makes the range
        a snapshot: the record found at that ordinal must be the one the
        caller captured, or the prefix it is asking for is not the prefix
        this log has. Absence before the captured head is corruption and not
        end of stream, so a walk that ends early refuses rather than
        returning short.

        **This is a generator, so calling it checks nothing** — the same
        caveat :meth:`engine.arrival.ArrivalLog.walk` carries, and for the
        same reason. Every check below runs as records are pulled.
        """
        floor = -1 if after is None else after
        reached = through is None
        for record in self._log.walk():
            if through is not None and record["ord"] == through.ordinal:
                if (
                    record["lin"] != through.lineage
                    or record["rh"] != through.record_hash
                ):
                    raise HeadMismatch(
                        f"ordinal {through.ordinal} of {self._log.path} holds "
                        f"{record['lin']}/{record['rh']}, not the captured "
                        f"{through.lineage}/{through.record_hash} — the "
                        "snapshot this scan was asked for is not this log's"
                    )
                reached = True
            if record["ord"] > floor:
                yield record
            if through is not None and record["ord"] >= through.ordinal:
                break
        if not reached:
            raise HeadMismatch(
                f"{self._log.path} ends before ordinal {through.ordinal} — "
                "absence before a captured head is corruption, not end of "
                "stream"
            )

    def verify(self, scope: VerifyScope) -> Head:
        """Verify through a named head; return the head the claim covers.

        **Verification reports; it never repairs.** Nothing here takes the
        append lock, and the lock is the only thing that licenses truncating
        a torn tail — so no path through this method can rewrite the log it
        was asked to judge. (Whether that is a contract MUST is the F2
        addendum Kyle rules on at the slice-2 gate; this adapter holds it
        either way, because the alternative is reporting an agreement it just
        manufactured.)

        ``Incremental`` is NOT offered, and :meth:`capabilities` says so. A
        verified suffix walk has to start somewhere, and this backend starts
        one from a resume mark's byte offset — which a :class:`Head` does not
        carry. Finding the checkpoint's position would mean walking to it,
        making "incremental" the same work as ``Full`` under a name that
        promises less. An honest absent level beats a level that lies about
        its cost.
        """
        if isinstance(scope, Open):
            # Genesis and the adopted head record — §06's Open level exactly.
            # `_tail_record` and not the public `head()`: `head()` reaches its
            # answer through a full walk, which would make this level a Full
            # verification wearing an Open label. Reading the tail validates
            # the genesis and the head record it adopts, and truncates
            # nothing (that lives behind the lock, which this never takes).
            self._log.genesis()
            return _head_of(self._log._tail_record())

        if isinstance(scope, Incremental):
            raise NotImplementedError(
                "the file adapter offers OPEN and FULL verification only — a "
                "verified suffix walk starts from a resume mark's byte "
                "offset, and a Head does not carry one. capabilities() "
                "reports the two levels it actually has"
            )

        if not isinstance(scope, Full):
            raise TypeError(f"not a verification scope: {scope!r}")

        # Grammar, density, lineage and the hash chain for the complete
        # prefix — `walk` IS that statement, and it is consumed to the end
        # here rather than returned, because a generator nobody drains
        # verifies nothing.
        found: Mapping[str, Any] | None = None
        for record in self._log.walk():
            if record["ord"] == scope.through.ordinal:
                found = record
        if found is None:
            raise HeadMismatch(
                f"{self._log.path} holds no record at ordinal "
                f"{scope.through.ordinal} — the head this verification was "
                "asked about is not in this log"
            )
        head = _head_of(found)
        if head != scope.through:
            raise HeadMismatch(
                f"ordinal {scope.through.ordinal} verifies as {head}, not the "
                f"claimed {scope.through}"
            )
        return head

    def capabilities(self) -> Capabilities:
        """What this backend actually offers — no more (§12).

        ``AUTHORITY`` alone, and no export codecs, because ``replicate`` and
        ``export`` are WP2's. Deployment tooling refuses an assignment whose
        required guarantees are absent, so an over-claim here is worse than a
        missing feature: it turns a refusal into a runtime failure.
        """
        return Capabilities(
            protocol_version=GRAMMAR_VERSION,
            profiles=frozenset({Profile.AUTHORITY}),
            durability=DurabilityProfile.HOST,
            verification_levels=frozenset(
                {VerificationLevel.OPEN, VerificationLevel.FULL}
            ),
            writer_concurrency=(
                "multi-process on one host, advisory flock; LOCAL POSIX "
                "storage only — a store on NFS or another network filesystem "
                "is out of contract"
            ),
            snapshot=(
                "captured-head prefix; readers take no lock and see only "
                "newline-terminated records, so an append in flight is "
                "invisible rather than partial"
            ),
            watermark=(
                "the projection reports a (lineage, ordinal) coordinate; the "
                "ledger attests the head at it"
            ),
            max_atomic_records=self._max_atomic_records,
            idempotency_keys=False,
            export_codecs=(),
            limits=(),
        )


def _meta(index_path: Path, key: str) -> str | None:
    """One ``store_meta`` value, through a connection that cannot write.

    Opened per call rather than held: the watermark advances as the
    projection consumes, so a cached answer would be a stale claim about
    freshness, which is the one thing a watermark must never be. Read-only by
    URI, so this path cannot repair what it is reporting on even by accident.
    """
    if not index_path.exists():
        return None
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None  # no store_meta table: an index that has never consumed
    finally:
        conn.close()
    return None if row is None else row[0]


class FileQuery:
    """Reads over the projection, with no route back into custody.

    Constructed from an index PATH, and it builds its own read handle. That
    is the separation stated as construction rather than as discipline:
    there is no parameter through which an :class:`ArrivalLog` or an
    ``ArrivalStore`` could be passed in, so there is no instance from which
    an append could be reached — including by a future edit that adds a
    convenience the author did not think through. The reader it builds is
    :class:`engine.store_reader.StoreReader`, whose connection is opened
    ``PRAGMA query_only=ON``.

    :attr:`reader` is the row-shaped read surface, deliberately left as this
    backend's own rather than declared on
    :class:`engine.arrival_contract.ArrivalQuery`. One adapter is not a
    pattern, and a neutral spelling of "give me the facts" invented against a
    single implementation would be an invention, not a contract.
    """

    def __init__(self, index_path: Path | str) -> None:
        self._path = Path(index_path)
        self.reader = StoreReader(self._path)

    def lineage(self) -> str | None:
        """The lineage this projection represents, or None when it holds none.

        §07: query results report the lineage they actually represent. A
        fresh index that has consumed nothing represents no lineage, and
        saying so is different from guessing at the log's.
        """
        return _meta(self._path, ARRIVAL_LINEAGE_KEY)

    def projected_through(self) -> Watermark | None:
        """How much of the lineage this projection accounts for (§07).

        A :class:`~engine.arrival_contract.Watermark` and not a ``Head``:
        this projection stores a coordinate, not a record hash — see the
        Watermark docstring, and ``finding:slice2-wp1-projection-has-no-head
        -hash`` for why closing that gap is not WP1's to invent. Resolving it
        to a verified head is :meth:`FileLedger.head_at`.

        Both fields or nothing. A partial mark is not a position.
        """
        lineage = _meta(self._path, ARRIVAL_LINEAGE_KEY)
        ordinal = _meta(self._path, ARRIVAL_ORDINAL_KEY)
        if lineage is None or ordinal is None:
            return None
        return Watermark(lineage=lineage, ordinal=int(ordinal))

    def close(self) -> None:
        """Close the read handle this query built."""
        self.reader.close()
