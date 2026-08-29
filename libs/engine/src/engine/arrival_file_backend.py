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

**The transfer half (§08), and where its three verbs differ.** ``replicate``
inserts an exact suffix of pre-coordinated records and assigns nothing;
``export`` captures a head and re-encodes its complete prefix; ``import_prefix``
is the §08-DEFAULT importer and nothing more — a new empty replica, or a
non-empty target that agrees exactly through its own head, else it refuses. A
"merge" that re-coordinates content is admission into another lineage, which is
a different operation with different evidence behind it and is not here.

``import_prefix`` is deliberately NOT declared on
:class:`engine.arrival_contract.ArrivalLedger`: §08 describes portable import in
prose, the ratified op table gives it no row, and growing the Protocol is a
contract decision rather than an adapter's. It IS in
``LEDGER_MUTATIONS``, because the custody/reads separation must cover every op
that can change what a lineage holds whether the contract names it or not.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .arrival import (
    GRAMMAR_VERSION,
    ArrivalCorrupt,
    ArrivalLog,
    Entry,
    ForkedHeight,
    StaleHead,
    decode_record,
    encode_record,
)
from .arrival_contract import (
    AtomicLimitExceeded,
    Capabilities,
    Commit,
    DurabilityProfile,
    DurabilityReceipt,
    ExportedPrefix,
    Full,
    Head,
    HeadMismatch,
    Incremental,
    NotAuthority,
    Open,
    Profile,
    RecordDraft,
    SameHeightFork,
    VerificationLevel,
    VerifyScope,
    Watermark,
)
from .arrival_store import (
    ARRIVAL_LINEAGE_KEY,
    ARRIVAL_ORDINAL_KEY,
)
from .store_reader import StoreReader

__all__ = ["EXPORT_CODEC", "FileLedger", "FileQuery"]

# The one wire codec this backend exports and imports. Named after the grammar
# it is, and versioned separately from `GRAMMAR_VERSION` on purpose: the codec
# is what an export FILE claims about its own framing, and a future codec that
# packed the same records differently would leave the record grammar alone.
EXPORT_CODEC = "arrival-jsonl-v1"

# How the codec frames one record. A manifest field rather than a convention,
# because "each element is one record's line INCLUDING its newline" is what
# makes ``b"".join(prefix.records)`` byte-identical to the log's own prefix —
# a property a reader can only rely on if the export states it.
_FRAMING = "newline-terminated"


# What an append has established before it reports success. The mechanism is
# named because the profile alone does not tell an operator what to check:
# §05's callout is explicit that this contract is LOCAL POSIX storage, and
# that moving the same bytes onto NFS does not inherit it.
_DURABILITY = DurabilityReceipt(
    profile=DurabilityProfile.HOST,
    mechanism="advisory flock, one write, one fsync, on local POSIX storage",
)


def _decoded(prefix: ExportedPrefix) -> list[dict]:
    """The export's records, decoded and held to the grammar.

    :func:`engine.arrival.decode_record` is the gate, so a record whose ``rh``
    does not recompute never reaches the import — the bytes travelled, and
    anything that travelled has to be re-established rather than assumed.

    Framing is read from the manifest and ENFORCED: a codec that says its
    elements are newline-terminated and hands over one that is not has
    contradicted itself, and quietly accepting either shape would make
    ``b"".join(records)`` mean two different things.
    """
    framing = prefix.manifest.get("framing")
    if framing != _FRAMING:
        raise ValueError(
            f"this backend reads {_FRAMING!r} framing and nothing else, but "
            f"this export's manifest claims {framing!r}"
        )
    records: list[dict] = []
    for index, line in enumerate(prefix.records):
        if not line.endswith(b"\n"):
            raise ArrivalCorrupt(
                f"element {index} carries no newline, but the manifest claims "
                f"{_FRAMING!r} framing",
                index,
            )
        records.append(decode_record(line[:-1]))
    return records


def _refuse_disagreeing_manifest(
    prefix: ExportedPrefix, imported: Sequence[Mapping[str, Any]]
) -> None:
    """Re-derive every manifest claim from the records and compare.

    A manifest travels with the bytes it describes, so it is exactly as
    trustworthy as they are: checking it is the only thing that makes carrying
    one worth doing. Each claim is re-derived rather than sampled — a count
    that matched while the head did not would still be a corrupt export.

    Density is what makes this cheap: the prefix runs from ordinal 0 to the
    captured head with nothing missing, so ``count`` is arithmetic and the
    starting ordinal is a constant.
    """
    if not imported:
        raise ArrivalCorrupt(
            "this export holds no records — a prefix runs from genesis, so "
            "the smallest honest export is one record",
            0,
        )
    if prefix.manifest.get("protocol") != GRAMMAR_VERSION:
        raise ArrivalCorrupt(
            f"this export claims protocol {prefix.manifest.get('protocol')!r}, "
            f"but this backend reads grammar {GRAMMAR_VERSION}",
            0,
        )
    if imported[0]["ord"] != 0:
        raise ArrivalCorrupt(
            f"this export starts at ordinal {imported[0]['ord']}, not 0 — a "
            "prefix that does not start at genesis is a suffix, and importing "
            "one is replication, not import",
            imported[0]["ord"],
        )
    last = imported[-1]
    derived = Head(
        lineage=last["lin"], ordinal=last["ord"], record_hash=last["rh"]
    )
    if derived != prefix.head:
        raise ArrivalCorrupt(
            f"this export's records end at {derived}, but it claims to capture "
            f"{prefix.head}",
            last["ord"],
        )
    claimed = (
        prefix.manifest.get("lineage"),
        prefix.manifest.get("through_ordinal"),
        prefix.manifest.get("through_record_hash"),
        prefix.manifest.get("count"),
    )
    if claimed != (derived.lineage, derived.ordinal, derived.record_hash, len(imported)):
        raise ArrivalCorrupt(
            f"this export's manifest claims {claimed}, but its records give "
            f"{(derived.lineage, derived.ordinal, derived.record_hash, len(imported))}",
            last["ord"],
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

    Satisfies :class:`engine.arrival_contract.ArrivalLedger` in full, and
    offers one op beyond it — ``import_prefix``, which the Protocol
    deliberately does not declare (see the module docstring).

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

    def replicate(
        self, expected: Head | None, records: Sequence[Mapping[str, Any]]
    ) -> Commit:
        """Insert an exact suffix of pre-coordinated records (§08).

        Composition, not a second appender: the whole transition is
        :meth:`engine.arrival.ArrivalLog.append_records`, which is the batched
        form of the primitive that has had the right posture all along —
        append VALIDATES, it never assigns. Nothing here rehashes, re-signs,
        or renumbers, so the records that land are byte-for-byte the records
        that were offered, which is the one property replication exists to
        keep. The same lock, the same full-head compare-and-swap and the same
        single fsync as :meth:`append`, because they are literally the same
        code path under a different build.

        Two refusals, and they are different claims:

        * :class:`~engine.arrival_contract.SameHeightFork` — the log already
          holds a DIFFERENT record at a height this batch would fill. The two
          histories disagree, retrying cannot make them agree, and choosing
          between them would be admission into another lineage.
        * :class:`~engine.arrival_contract.HeadMismatch` — the head is not
          where this batch assumed, either because ``expected`` no longer
          describes it or because the batch is not the suffix that follows it.
          Re-read and recompute which records are missing.

        A batch whose ordinals disagree with each other, or whose supplied
        ``rh`` does not recompute, refuses as this backend's own
        ``AppendRejected``/``ArrivalGrammarError``: the ratified refusal set
        has no member for "this candidate is malformed", and picking one would
        be a verdict the evidence does not support
        (``finding:slice2-wp1-refusal-set-gaps``).
        """
        if not records:
            raise ValueError(
                "replicate was handed no records — an empty replication is a "
                "caller bug, not a no-op to absorb"
            )
        if (
            self._max_atomic_records is not None
            and len(records) > self._max_atomic_records
        ):
            raise AtomicLimitExceeded(
                f"{len(records)} records exceeds this backend's configured "
                f"atomic limit of {self._max_atomic_records} — refused before "
                "any mutation, because a partially applied suffix is the one "
                "artifact a replica must never hold"
            )
        try:
            landed, _mark = self._log.append_records(
                [dict(record) for record in records], following=expected
            )
        except ForkedHeight as exc:
            raise SameHeightFork(str(exc)) from exc
        except StaleHead as exc:
            # 1:1 from the CAS subclass only, for the reason `append` gives:
            # the parent AppendRejected also covers placement faults, and
            # mapping those to HeadMismatch would assert something about the
            # head that the fault does not say.
            raise HeadMismatch(str(exc)) from exc

        first, last = landed[0], landed[-1]
        return Commit(
            before=Head(
                lineage=first["lin"],
                ordinal=first["ord"] - 1,
                record_hash=first["prev"],
            ),
            records=tuple(landed),
            after=_head_of(last),
            durability=_DURABILITY,
        )

    def export(self, *, through: Head, codec: str) -> ExportedPrefix:
        """Re-encode the complete prefix behind a captured head (§08).

        Net-new over :meth:`scan` and
        :func:`engine.arrival.encode_record`, and it is deliberately thin:
        ``scan`` already refuses a head this log does not hold and already
        stops at the captured ordinal, so the export inherits both without
        restating either.

        **Streaming.** ``records`` is a generator, so nothing is materialised
        and nothing is read until it is drained — the same caveat
        :meth:`scan` carries, and the reason an export of a large lineage is
        runnable at all. Each element is one record's line INCLUDING its
        newline, so ``b"".join(...)`` reproduces the log's own prefix bytes
        exactly. The manifest says so rather than leaving it to be discovered.

        **The manifest carries no clock and no host.** Everything in it is
        derived from the captured head and the grammar, which is what makes
        export → import → export byte-identical rather than
        byte-identical-except-for-a-timestamp. ``count`` is
        ``through.ordinal + 1`` by density and needs no drain to compute — and
        the drain proves it, because a walk that found a gap would have
        refused before reaching the head.

        A codec this backend does not have is a caller bug against
        :meth:`capabilities`, not a contract refusal — the ratified set has no
        member for it, and inventing one would be the over-claim §12 exists to
        catch.
        """
        if codec != EXPORT_CODEC:
            raise ValueError(
                f"this backend exports {EXPORT_CODEC!r} and nothing else, but "
                f"{codec!r} was asked for — capabilities().export_codecs is "
                "the list to check against"
            )

        def lines() -> Iterator[bytes]:
            for record in self.scan(through=through):
                yield (encode_record(record) + "\n").encode("utf-8")

        return ExportedPrefix(
            head=through,
            codec=codec,
            records=lines(),
            manifest={
                "protocol": GRAMMAR_VERSION,
                "codec": codec,
                "framing": _FRAMING,
                "lineage": through.lineage,
                "through_ordinal": through.ordinal,
                "through_record_hash": through.record_hash,
                "count": through.ordinal + 1,
            },
        )

    def import_prefix(self, prefix: ExportedPrefix) -> Head:
        """The §08-default portable import, and nothing beyond it.

        Two targets and no third: a log that does not exist yet, or one whose
        every record agrees exactly with the import through its own head. Any
        other target REFUSES. There is no merge arm here — content that has to
        be re-coordinated to fit is being admitted into another lineage, and
        admission is a different operation.

        Returns the target's :class:`~engine.arrival_contract.Head` after the
        import, and not a ``Commit``: an import into an empty replica has no
        ``before`` to name, and manufacturing one would be the first lie a
        replica told about where it came from.

        **The manifest is checked, never trusted.** It travels with the bytes,
        so it is exactly as trustworthy as they are; every field is
        re-derived from the decoded records and compared. A manifest that
        disagrees with its own records is a corrupt export, and reporting the
        disagreement is the whole reason to carry one.

        **Replica is not authority** (§08's callout). This method copies
        records; it grants nothing. A store that then accepts independent
        writes has forked, byte-identical start or not, and no flag here
        prevents that — custody does.

        The verified remainder is materialised, because it is handed to one
        atomic :meth:`replicate`. That is the honest limit of a MINIMAL
        importer: an import too large to hold is a resumable-transfer design,
        and this is not one.
        """
        if prefix.codec != EXPORT_CODEC:
            raise ValueError(
                f"this backend imports {EXPORT_CODEC!r} and nothing else, but "
                f"this export claims codec {prefix.codec!r}"
            )
        imported = _decoded(prefix)
        _refuse_disagreeing_manifest(prefix, imported)

        if not self._log.exists():
            # A new empty replica. Genesis cannot be appended onto a head that
            # is not there, and it must not be re-minted either: a replica
            # whose ordinal 0 differed by one byte would be a different
            # lineage wearing the same id.
            log = ArrivalLog.adopt_genesis(self._log.path, imported[0])
            self._log = log
            head = _head_of(log.genesis())
            if len(imported) == 1:
                return head
            return self.replicate(head, imported[1:]).after

        head = self.head()
        self._refuse_disagreeing_prefix(imported, head)
        remainder = [
            record for record in imported if record["ord"] > head.ordinal
        ]
        if not remainder:
            # The import is a prefix of what this target already holds. Not a
            # failure and not a no-op to hide: nothing was missing.
            return head
        return self.replicate(head, remainder).after

    def _refuse_disagreeing_prefix(
        self, imported: Sequence[Mapping[str, Any]], head: Head
    ) -> None:
        """§08's exact-prefix-agreement gate for a non-empty target.

        Over :meth:`scan`, which is the read op that already establishes the
        target's prefix is intact — so this adds one comparison and no second
        traversal of its own. Position by position against the import, so the
        refusal names the ordinal the two disagree at rather than reporting
        that they differ somewhere.

        Distinct from the same-height fork :meth:`replicate` refuses: that one
        fires on an overlap it was HANDED, this one on the overlap it is about
        to SKIP. Both say the histories disagree at a height; skipping an
        overlap without checking it is how a replica silently acquires a
        prefix it never verified.
        """
        for mine, theirs in zip(self.scan(through=head), imported, strict=False):
            if mine["rh"] != theirs["rh"]:
                raise SameHeightFork(
                    f"ordinal {mine['ord']} of {self._log.path} holds rh "
                    f"{mine['rh']}, but the import holds rh {theirs['rh']} at "
                    f"ordinal {theirs['ord']} — this import is not a continuation "
                    "of this log's history. Importing into a non-empty target "
                    "requires exact prefix agreement through its head"
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

        Deployment tooling refuses an assignment whose required guarantees are
        absent, so an over-claim here is worse than a missing feature: it turns
        a refusal into a runtime failure.

        ``REPLICA`` joins ``AUTHORITY`` because :meth:`replicate` now exists —
        the profile names what a store may be ASKED to do, and an adapter that
        can consume pre-coordinated records without assigning any is what makes
        the replica role performable. ``ARCHIVE`` stays absent: nothing here
        offers a read-only sealed mode, and claiming one would be exactly the
        lie this report exists to make catchable.

        The codec tuple grows to what :meth:`export` will actually produce, and
        to nothing else. A test cross-checks both claims against the object.
        """
        return Capabilities(
            protocol_version=GRAMMAR_VERSION,
            profiles=frozenset({Profile.AUTHORITY, Profile.REPLICA}),
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
            export_codecs=(EXPORT_CODEC,),
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
