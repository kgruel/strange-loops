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

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .arrival import (
    GRAMMAR_VERSION,
    ArrivalCorrupt,
    ArrivalLog,
    Entry,
    ForkedHeight,
    ResumeMark,
    StaleHead,
    decode_record,
    encode_record,
)
from .arrival_contract import (
    AtomicLimitExceeded,
    Capabilities,
    Commit,
    Continuation,
    DeclarationAnchor,
    DurabilityProfile,
    DurabilityReceipt,
    ExportedPrefix,
    Fact,
    FactCursor,
    FactPage,
    FactRequest,
    Full,
    Head,
    HeadMismatch,
    Incremental,
    InvalidContinuation,
    NotAuthority,
    NotSupported,
    Open,
    Profile,
    ProjectionAbsent,
    ProjectionBehind,
    ProjectionRequirement,
    QuerySnapshot,
    RecordDraft,
    SameHeightFork,
    SearchFieldSpec,
    SearchMatch,
    SearchPage,
    SearchRequest,
    SearchStale,
    Summary,
    SummaryRequest,
    Tick,
    TickRequest,
    VerificationLevel,
    VerifyScope,
    Watermark,
)
from .arrival_maintenance import MaintenanceAdvance, MaintenanceCapabilities
from .arrival_projection import (
    _ensure_index_schema,
    _meta_get,
    _meta_set,
    _stamp_mark,
    has_rows,
    licensed_own_lineage,
    rows_of_record,
)
from .arrival_search import SearchCoverage, SearchIndexBuild
from .file_projection_schema import (
    ARRIVAL_LINEAGE_KEY,
    ARRIVAL_OFFSET_KEY,
    ARRIVAL_ORDINAL_KEY,
    FACT_INSERT_SQL,
    TICK_INSERT_SQL,
    ArrivalCanonicalUnsupported,
)
from .store_reader import StoreReader

__all__ = [
    "EXPORT_CODEC",
    "FileLedger",
    "FileProjectionMaintenance",
    "FileQuery",
    "FileSearchMaintenance",
    "SearchIndexBuild",
    "SearchCoverage",
]

# The one wire codec this backend exports and imports. Named after the grammar
# it is, and versioned separately from `GRAMMAR_VERSION` on purpose: the codec
# is what an export FILE claims about its own framing, and a future codec that
# packed the same records differently would leave the record grammar alone.
EXPORT_CODEC = "arrival-jsonl-v1"


def file_projection_path(location: Path | str) -> Path:
    """Choose a derived pathname without interpreting the ledger's format.

    Retain the established sibling for conventional log names. Other explicit
    file locators get a distinct sidecar; a .db spelling is still an Arrival
    ledger and must never be opened as its own SQLite projection.
    """
    path = Path(location)
    if path.suffix.lower() in (".arrival", ".jsonl"):
        return path.with_suffix(".db")
    return path.with_name(path.name + ".projection.db")

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
        entries = [
            Entry(
                k=draft.kind,
                body=dict(draft.body),
                observer=draft.observer,
                origin=draft.origin,
                at=draft.authored_at,
                signature=draft.signature,
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
                yield (encode_record(dict(record)) + "\n").encode("utf-8")

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
            # The import reaches exactly this target's head and agrees with it
            # the whole way. Nothing was missing — not a failure, and not a
            # no-op to hide. An import that stopped SHORT of the head never
            # gets here; it refuses above.
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

        **An import that ends BEFORE the target's head refuses.** §08 asks for
        agreement THROUGH the head, and a prefix that stops short structurally
        cannot establish that — there is nothing to compare the records above
        it against. Reporting success would be a verdict this operation has no
        evidence for: it would say "this target agrees with the import through
        its head" while never having looked at the heights in between. The
        length is therefore checked FIRST and explicitly, rather than left to a
        zip that would silently stop at the shorter side.
        """
        # Dense from 0 (the manifest check establishes both), so the target's
        # prefix is exactly this many records and the import must cover it.
        overlap = head.ordinal + 1
        if len(imported) < overlap:
            captured = imported[-1]
            raise HeadMismatch(
                f"this import captures head ({captured['lin']}, "
                f"{captured['ord']}, {captured['rh']}), which is behind "
                f"{self._log.path}'s head ({head.lineage}, {head.ordinal}, "
                f"{head.record_hash}) — §08 requires exact prefix agreement "
                "THROUGH the target's head, and an import that stops short "
                "cannot establish it. Export again at or past the target's head"
            )

        for mine, theirs in zip(
            self.scan(through=head), imported[:overlap], strict=True
        ):
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
            assert through is not None
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
        was asked to judge. (§06 states that as a contract MUST as of
        ``decision:design/arrival-slice2-contract-text`` ruling 1; this
        adapter held it before the ruling, because the alternative is
        reporting an agreement it just manufactured.)

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
            raise NotSupported(
                "the file adapter offers OPEN and FULL verification only — a "
                "verified suffix walk starts from a resume mark's byte "
                "offset, and a Head does not carry one. capabilities() "
                "reports the two levels it actually has"
            )

        if not isinstance(scope, Full):
            raise TypeError(f"not a verification scope: {scope!r}")

        # Grammar, density, lineage and the hash chain for the complete named
        # prefix. `walk` is consumed through that head, then stopped: Full(H)
        # makes no claim about a later concurrently appended or corrupted tail.
        found: Mapping[str, Any] | None = None
        for record in self._log.walk():
            if record["ord"] == scope.through.ordinal:
                found = record
                break
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


def _snapshot_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Read projection metadata on the same transaction as its rows."""
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else row[0]


class _AbsentFileQuerySnapshot:
    """An honest allow-behind snapshot where no projection exists yet."""

    represented: Watermark | None = None
    view_generation: str | None = None
    declaration_anchor = DeclarationAnchor(own_lineage=None, genesis=None)

    def facts(self, request: FactRequest) -> FactPage:
        return FactPage(items=(), cursor=None, truncated=False, order=request.order)

    def ticks(self, request: TickRequest) -> tuple[Tick, ...]:
        return ()

    def summary(self, request: SummaryRequest) -> Summary:
        return Summary(
            fact_total=0, tick_total=0, signed_count=0, unsigned_count=0,
            fact_kinds={}, tick_names={},
        )

    def search(self, request: SearchRequest) -> SearchPage:
        raise NotSupported("the file query snapshot has no search coverage")

    def close(self) -> None:
        return None


class _FileQuerySnapshot:
    """One SQLite read transaction, bounded to a captured Arrival prefix.

    The snapshot deliberately works below ``StoreReader``: that class's public
    page API has no captured-head bound.  The legacy reader remains available
    on :class:`FileQuery`; this private implementation is the new portable
    surface and never exposes its connection.
    """

    def __init__(
        self,
        path: Path,
        *,
        captured_head: Head,
        requirement: ProjectionRequirement,
        continuation: Continuation | None,
    ) -> None:
        self._path = path
        self._captured_head = captured_head
        self._conn = sqlite3.connect(
            f"{path.absolute().as_uri()}?mode=ro", uri=True
        )
        self._conn.execute("PRAGMA query_only=ON")
        self._conn.execute("BEGIN DEFERRED")
        self._closed = False
        try:
            self._fact_signature_column = self._has_column("facts", "signature")
            self._tick_chain_columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(ticks)")
            }
            lineage = _snapshot_meta(self._conn, ARRIVAL_LINEAGE_KEY)
            ordinal = _snapshot_meta(self._conn, ARRIVAL_ORDINAL_KEY)
            if lineage is None or ordinal is None:
                raise ProjectionAbsent(f"{path} has no complete projection watermark")
            watermark = Watermark(lineage=lineage, ordinal=int(ordinal))
            if watermark.lineage != captured_head.lineage:
                raise NotAuthority(
                    f"projection at {path} represents {watermark.lineage}, not "
                    f"captured lineage {captured_head.lineage}"
                )
            if continuation is not None:
                if continuation.captured_head != captured_head:
                    raise InvalidContinuation(
                        "continuation captured head differs from this read"
                    )
                if continuation.projected_through.lineage != captured_head.lineage:
                    raise InvalidContinuation(
                        "continuation represented another lineage"
                    )
                if watermark.ordinal < continuation.projected_through.ordinal:
                    raise InvalidContinuation(
                        "projection no longer reaches the continuation prefix"
                    )
                if (
                    requirement is ProjectionRequirement.CURRENT
                    and continuation.projected_through.ordinal < captured_head.ordinal
                ):
                    raise ProjectionBehind(
                        f"continuation prefix ends at "
                        f"{continuation.projected_through.ordinal}, but the "
                        f"captured head is {captured_head.ordinal}"
                    )
                bound = continuation.projected_through.ordinal
            elif watermark.ordinal < captured_head.ordinal:
                if requirement is ProjectionRequirement.CURRENT:
                    raise ProjectionBehind(
                        f"projection at {path} ends at {watermark.ordinal}, but "
                        f"the captured head is {captured_head.ordinal}"
                    )
                bound = watermark.ordinal
            else:
                # A watermark beyond H may be a normal append/catch-up after H
                # was captured. The consumer validates its membership and
                # clamps the externally reported basis to H.
                bound = captured_head.ordinal
            self._bound = Watermark(lineage=captured_head.lineage, ordinal=bound)
            self._observed_watermark = watermark
            self._declaration_anchor = self._read_declaration_anchor()
            self._continuation = continuation
            self._view_generation = self._generation(bound)
            if (
                continuation is not None
                and continuation.view_generation != self._view_generation
            ):
                raise InvalidContinuation(
                    "projection view changed since this continuation was issued"
                )
        except BaseException:
            self.close()
            raise

    @property
    def represented(self) -> Watermark:
        """The actual watermark read in this transaction, before any clamp."""
        return self._observed_watermark

    @property
    def view_generation(self) -> str:
        return self._view_generation

    @property
    def observed_watermark(self) -> Watermark:
        """The actual projection mark, retained for coordinator validation."""
        return self._observed_watermark

    @property
    def declaration_anchor(self) -> DeclarationAnchor:
        return self._declaration_anchor

    def _read_declaration_anchor(self) -> DeclarationAnchor:
        """Read the marker and its exact genesis without inferring identity."""
        own_lineage = _snapshot_meta(self._conn, "own_lineage")
        if own_lineage is None:
            return DeclarationAnchor(own_lineage=None, genesis=None)
        try:
            row = self._conn.execute(
                "SELECT " + self._fact_select() + " FROM facts "
                "WHERE id = ? AND kind = '_decl.genesis'",
                (own_lineage,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise ProjectionAbsent(
                f"{self._path} cannot read declaration identity: {exc}"
            ) from exc
        return DeclarationAnchor(
            own_lineage=own_lineage,
            genesis=None if row is None else self._fact(row),
        )

    def _has_column(self, table: str, column: str) -> bool:
        columns = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
        return column in columns

    def _fact_select(self) -> str:
        columns = "id, kind, ts, observer, origin, payload, arrival_ordinal, arrival_seq"
        return columns + (", signature" if self._fact_signature_column else "")

    def _tick_select(self) -> str:
        columns = [
            "id", "name", "ts", "since", "origin", "payload",
            "arrival_ordinal", "arrival_seq",
        ]
        for column in ("prev_hash", "window_start", "fact_cursor", "window_hash", "signature"):
            columns.append(column if column in self._tick_chain_columns else f"NULL AS {column}")
        return ", ".join(columns)

    def _generation(self, bound: int) -> str:
        """Opaque identity for this file projection through ``bound``.

        SQLite offers no durable projection-generation token. A digest of the
        snapshot's schema, declaration identity, and complete bounded row
        content makes a conservative token: maintenance or row changes
        invalidate a resume even when its ledger prefix remains available.
        """
        digest = hashlib.sha256()
        schema_version = self._conn.execute("PRAGMA schema_version").fetchone()[0]
        genesis = self._declaration_anchor.genesis
        anchor = {
            "own_lineage": self._declaration_anchor.own_lineage,
            "genesis": None
            if genesis is None
            else {
                "id": genesis.id,
                "kind": genesis.kind,
                "ts": genesis.ts,
                "observer": genesis.observer,
                "origin": genesis.origin,
                "payload": genesis.payload,
                "arrival_ordinal": genesis.arrival_ordinal,
                "arrival_seq": genesis.arrival_seq,
            },
        }
        digest.update(
            f"schema:{schema_version}:bound:{bound}:".encode()
        )
        digest.update(json.dumps(anchor, sort_keys=True, separators=(",", ":")).encode())
        for table, columns in (
            (
                "facts",
                self._fact_select(),
            ),
            (
                "ticks",
                self._tick_select(),
            ),
        ):
            try:
                rows = self._conn.execute(
                    f"SELECT {columns} FROM {table} WHERE arrival_ordinal <= ? "
                    "ORDER BY arrival_ordinal, arrival_seq",
                    (bound,),
                )
            except sqlite3.OperationalError as exc:
                raise ProjectionAbsent(
                    f"{self._path} cannot answer projected {table}: {exc}"
                ) from exc
            digest.update(table.encode())
            for row in rows:
                digest.update(
                    json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode()
                )
                digest.update(b"\0")
        return f"file-projection-v1:{digest.hexdigest()}"

    @staticmethod
    def _fact(row: tuple[Any, ...]) -> Fact:
        return Fact(
            id=row[0], kind=row[1], ts=float(row[2]), observer=row[3], origin=row[4],
            payload=json.loads(row[5]), arrival_ordinal=int(row[6]), arrival_seq=int(row[7]),
            payload_text=row[5], signature=row[8] if len(row) > 8 else None,
        )

    @staticmethod
    def _tick(row: tuple[Any, ...]) -> Tick:
        return Tick(
            id=row[0],
            name=row[1],
            ts=float(row[2]),
            since=None if row[3] is None else float(row[3]),
            origin=row[4],
            payload=json.loads(row[5]),
            arrival_ordinal=int(row[6]),
            arrival_seq=int(row[7]),
            payload_text=row[5],
            prev_hash=row[8],
            window_start=row[9],
            fact_cursor=row[10],
            window_hash=row[11],
            signature=row[12],
        )

    def facts(self, request: FactRequest) -> FactPage:
        if request.order not in ("newest", "oldest"):
            raise ValueError(f"facts order must be 'newest' or 'oldest', got {request.order!r}")
        if request.limit is not None and request.limit < 1:
            raise ValueError("facts limit must be >= 1 or None")
        if self._continuation is not None and request != self._continuation.request:
            raise InvalidContinuation("continuation request does not match this facts request")

        clauses = ["arrival_ordinal <= ?"]
        params: list[Any] = [self._bound.ordinal]
        if request.kind is not None:
            from .sql_util import kind_subtree_predicate

            kind_sql, kind_params = kind_subtree_predicate(request.kind)
            clauses.append(kind_sql)
            params.extend(kind_params)
        if request.observer is not None:
            if "/" in request.observer:
                clauses.append("(observer = ? OR observer = ?)")
                params.extend((request.observer, request.observer.rsplit("/", 1)[1]))
            else:
                tail = "/" + request.observer
                clauses.append("(observer = ? OR substr(observer, -?, ?) = ?)")
                params.extend((request.observer, len(tail), len(tail), tail))
        if not request.include_internal:
            clauses.append("kind NOT GLOB '_decl.*'")
        if self._continuation is not None:
            cursor = self._continuation.cursor
            # A page is a hard row bound, so resume at the complete receipt
            # coordinate.  One packed Arrival record can contribute rows to
            # several pages; custody remains atomic at the ledger layer.
            if request.order == "newest":
                clauses.append(
                    "(arrival_ordinal < ? OR "
                    "(arrival_ordinal = ? AND (arrival_seq < ? OR "
                    "(arrival_seq = ? AND id < ?))))"
                )
            else:
                clauses.append(
                    "(arrival_ordinal > ? OR "
                    "(arrival_ordinal = ? AND (arrival_seq > ? OR "
                    "(arrival_seq = ? AND id > ?))))"
                )
            params.extend(
                (
                    cursor.arrival_ordinal,
                    cursor.arrival_ordinal,
                    cursor.arrival_seq,
                    cursor.arrival_seq,
                    cursor.fact_id,
                )
            )
        if request.fact_id is not None:
            # Preserve the established lookup rule: an exact visible ID wins
            # even when other IDs extend it. Only when no exact row survives
            # this request's bound, filters, and cursor is the value a prefix.
            exact_sql = (
                "SELECT "
                + self._fact_select()
                + " FROM facts WHERE "
                + " AND ".join((*clauses, "id = ?"))
                + " LIMIT 1"
            )
            exact = self._conn.execute(
                exact_sql, (*params, request.fact_id)
            ).fetchone()
            if exact is not None:
                return FactPage(
                    items=(self._fact(exact),),
                    cursor=None,
                    truncated=False,
                    order=request.order,
                )
            # IDs are arbitrary strings. Compare their UTF-8 bytes literally
            # so Unicode, NUL, and LIKE/GLOB metacharacters remain ordinary ID
            # content rather than depending on a sentinel alphabet or pattern
            # escaping convention.
            clauses.append(
                "substr(CAST(id AS BLOB), 1, length(CAST(? AS BLOB))) "
                "= CAST(? AS BLOB)"
            )
            params.extend((request.fact_id, request.fact_id))

        direction = "DESC" if request.order == "newest" else "ASC"
        sql = (
            "SELECT " + self._fact_select() + " FROM facts WHERE " + " AND ".join(clauses) +
            f" ORDER BY arrival_ordinal {direction}, arrival_seq {direction}, id {direction}"
        )
        if request.limit is None:
            rows = self._conn.execute(sql, params).fetchall()
            return FactPage(
                items=tuple(self._fact(row) for row in rows), cursor=None,
                truncated=False, order=request.order,
            )

        # Fetch one look-ahead row.  Unlike ledger/export operations, a query
        # page does not preserve a whole Arrival record: ``limit`` is a strict
        # maximum number of projected fact rows.
        rows = self._conn.execute(sql + " LIMIT ?", (*params, request.limit + 1)).fetchall()
        more = len(rows) > request.limit
        page_rows = rows[:request.limit]
        cursor = None
        if more:
            last = page_rows[-1]
            cursor = FactCursor(int(last[6]), int(last[7]), last[0])
        return FactPage(
            items=tuple(self._fact(row) for row in page_rows), cursor=cursor,
            truncated=more, order=request.order,
        )

    def ticks(self, request: TickRequest) -> tuple[Tick, ...]:
        clauses = ["arrival_ordinal <= ?", "ts >= ?", "ts <= ?"]
        params: list[Any] = [self._bound.ordinal, request.since, request.until]
        if request.name is not None:
            clauses.append("name = ?")
            params.append(request.name)
        rows = self._conn.execute(
            "SELECT " + self._tick_select() + " FROM ticks WHERE "
            + " AND ".join(clauses)
            + " ORDER BY ts, arrival_ordinal, arrival_seq",
            params,
        ).fetchall()
        return tuple(self._tick(row) for row in rows)

    def summary(self, request: SummaryRequest) -> Summary:
        internal = "" if request.include_internal else " AND kind NOT GLOB '_decl.*'"
        fact_total = self._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE arrival_ordinal <= ?" + internal,
            (self._bound.ordinal,),
        ).fetchone()[0]
        tick_total = self._conn.execute(
            "SELECT COUNT(*) FROM ticks WHERE arrival_ordinal <= ?",
            (self._bound.ordinal,),
        ).fetchone()[0]
        fact_rows = self._conn.execute(
            "SELECT kind, COUNT(*), MIN(ts), MAX(ts) FROM facts "
            "WHERE arrival_ordinal <= ?" + internal + " GROUP BY kind",
            (self._bound.ordinal,),
        ).fetchall()
        tick_rows = self._conn.execute(
            "SELECT name, COUNT(*), MIN(ts), MAX(ts) FROM ticks "
            "WHERE arrival_ordinal <= ? GROUP BY name",
            (self._bound.ordinal,),
        ).fetchall()
        signed_count = 0
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(facts)")}
        if "signature" in columns:
            signed_count = int(self._conn.execute(
                "SELECT COUNT(signature) FROM facts WHERE arrival_ordinal <= ?" + internal,
                (self._bound.ordinal,),
            ).fetchone()[0])
        return Summary(
            fact_total=int(fact_total), tick_total=int(tick_total),
            signed_count=signed_count, unsigned_count=int(fact_total) - signed_count,
            fact_kinds={
                row[0]: {"count": row[1], "earliest": row[2], "latest": row[3]}
                for row in fact_rows
            },
            tick_names={
                row[0]: {"count": row[1], "earliest": row[2], "latest": row[3]}
                for row in tick_rows
            },
        )

    def _search_coverage(self) -> tuple[Head, str, str] | None:
        try:
            rows = self._conn.execute(
                "SELECT key, value FROM arrival_fts_state"
            ).fetchall()
        except sqlite3.OperationalError:
            return None
        state = {str(key): str(value) for key, value in rows}
        try:
            head = Head(
                state["lineage"], int(state["ordinal"]), state["record_hash"]
            )
            fields_hash = state["fields_hash"]
            schema_token = state["schema_version"]
        except (KeyError, ValueError):
            return None
        actual_schema = str(self._conn.execute("PRAGMA schema_version").fetchone()[0])
        if schema_token != actual_schema:
            return None
        return head, fields_hash, schema_token

    def search(self, request: SearchRequest) -> SearchPage:
        """Run FTS5 only when its exact corpus is this snapshot's head."""
        if request.limit < 1:
            raise ValueError("search limit must be >= 1")
        coverage = self._search_coverage()
        if coverage is None:
            raise SearchStale("file search coverage is absent or schema-invalid")
        ranking_through, fields_hash, _schema_token = coverage
        if ranking_through != self._captured_head:
            raise SearchStale(
                "file search corpus does not exactly match this captured head"
            )
        if fields_hash != request.expected_fields_hash:
            raise SearchStale(
                "file search coverage was built for different declared fields"
            )

        clauses = [
            "arrival_facts_fts MATCH ?",
            "f.arrival_ordinal <= ?",
        ]
        params: list[Any] = [request.expression, self._bound.ordinal]
        if request.kind is not None:
            from .sql_util import kind_subtree_predicate

            kind_sql, kind_params = kind_subtree_predicate(request.kind, "f.kind")
            clauses.append(kind_sql)
            params.extend(kind_params)
        if request.observer is not None:
            clauses.append("f.observer = ?")
            params.append(request.observer)
        if request.since is not None:
            clauses.append("f.ts >= ?")
            params.append(request.since)
        if request.until is not None:
            clauses.append("f.ts <= ?")
            params.append(request.until)
        if not request.include_internal:
            clauses.append("f.kind NOT GLOB '_decl.*'")
        where = " AND ".join(clauses)
        joined = (
            " FROM arrival_facts_fts JOIN facts f "
            "ON f.id = arrival_facts_fts.fact_id WHERE " + where
        )
        total = int(self._conn.execute("SELECT COUNT(*)" + joined, params).fetchone()[0])
        rows = self._conn.execute(
            "SELECT " + self._fact_select() + ", "
            "bm25(arrival_facts_fts), "
            "snippet(arrival_facts_fts, 0, '[', ']', '…', 16)"
            + joined
            + " ORDER BY bm25(arrival_facts_fts), f.arrival_ordinal DESC, "
            "f.arrival_seq DESC, f.id DESC LIMIT ?",
            (*params, request.limit + 1),
        ).fetchall()
        truncated = len(rows) > request.limit
        matches = tuple(
            SearchMatch(
                fact=self._fact(row[:-2]), rank=float(row[-2]), snippet=row[-1]
            )
            for row in rows[:request.limit]
        )
        return SearchPage(
            matches=matches,
            total_matches=total,
            truncated=truncated,
            ranking="sqlite-fts5-bm25",
            ranking_through=ranking_through,
            fields_hash=fields_hash,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._conn.rollback()
        finally:
            self._conn.close()


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

    **The reader is built on first use, not at construction** (slice 3 §0.4).
    It used to be built eagerly, and ``StoreReader`` refuses a path that does
    not exist — so a store whose projection had never been materialised could
    not be opened through the registry AT ALL, even though its ledger half was
    perfectly openable. That blocked ``mint`` through the registry, which is
    the path slice 4's sidecar takes to get its bootstrap receipt, and it sat
    against the ratified F2 carve-out, which explicitly anticipates an absent
    projection ("materialising a projection that does not yet exist is not
    repair"). Deferring the construction is the whole fix: **opening** stops
    requiring a projection, while **asking for rows** still refuses honestly
    with the same ``FileNotFoundError`` from the same place. Nothing here
    creates an index — permitted is not required, and creating one on the way
    to a read would be the adapter deciding a materialisation policy that
    belongs to whoever asked.
    """

    def __init__(self, index_path: Path | str) -> None:
        self._path = Path(index_path)
        self._reader: StoreReader | None = None

    @property
    def reader(self) -> StoreReader:
        """The row-shaped read surface, built on first access and then held.

        Held rather than rebuilt per call, unlike :func:`_meta`'s connection:
        that one is re-opened every time because a cached watermark would be a
        stale claim about freshness, which is the one thing a watermark must
        never be. A row reader has no such obligation — it answers about rows,
        not about how far it has consumed — so one handle per query object is
        the same lifetime it had when this was an attribute.
        """
        if self._reader is None:
            self._reader = StoreReader(self._path)
        return self._reader

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

    def open_snapshot(
        self,
        *,
        captured_head: Head,
        requirement: ProjectionRequirement,
        continuation: Continuation | None = None,
    ) -> QuerySnapshot:
        """Open a read-only SQLite snapshot bounded by ``captured_head``.

        No projection is created or repaired here. A missing index is an
        explicit current-read refusal, or an empty allow-behind snapshot that
        carries no represented watermark for diagnostics.
        """
        if not self._path.exists():
            if requirement is ProjectionRequirement.CURRENT:
                raise ProjectionAbsent(f"{self._path} does not exist")
            return _AbsentFileQuerySnapshot()
        return _FileQuerySnapshot(
            self._path,
            captured_head=captured_head,
            requirement=requirement,
            continuation=continuation,
        )

    def close(self) -> None:
        """Close the read handle this query built, if it ever built one.

        Closing must not be the thing that CONSTRUCTS a reader — a query opened
        over an absent projection and closed without being read would then
        raise from ``close()``, turning the lazy fix into a refusal moved to a
        stranger place. So this consults the field rather than the property.
        """
        if self._reader is not None:
            self._reader.close()
            self._reader = None


class FileProjectionMaintenance:
    """Explicit, bounded catch-up for the file adapter's SQLite projection.

    Construction performs no I/O. ``catch_up`` validates the requested full
    head against the log before opening a write transaction, then re-reads the
    projection mark under ``BEGIN IMMEDIATE`` so concurrent maintainers
    serialize on the projection itself. Existing rows and identity markers are
    never discarded or replaced.
    """

    def __init__(self, log_path: Path | str, index_path: Path | str) -> None:
        self._log = ArrivalLog(log_path)
        self._path = Path(index_path)
        self._closed = False

    def capabilities(self) -> MaintenanceCapabilities:
        return MaintenanceCapabilities(catch_up=True, rebuild=False)

    @staticmethod
    def _tables(conn: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }

    @staticmethod
    def _read_mark(conn: sqlite3.Connection) -> ResumeMark | None:
        values = (
            _meta_get(conn, ARRIVAL_LINEAGE_KEY),
            _meta_get(conn, ARRIVAL_OFFSET_KEY),
            _meta_get(conn, ARRIVAL_ORDINAL_KEY),
        )
        if values == (None, None, None):
            return None
        if any(value is None for value in values):
            raise ArrivalCanonicalUnsupported(
                "projection carries a partial Arrival resume mark"
            )
        lineage, raw_offset, raw_ordinal = values
        assert raw_offset is not None and raw_ordinal is not None
        try:
            offset = int(raw_offset)
            ordinal = int(raw_ordinal)
        except (TypeError, ValueError) as exc:
            raise ArrivalCanonicalUnsupported(
                "projection carries a non-integer Arrival resume mark"
            ) from exc
        if not isinstance(lineage, str) or not lineage or offset <= 0 or ordinal < 0:
            raise ArrivalCanonicalUnsupported(
                "projection carries an invalid Arrival resume mark"
            )
        return ResumeMark(lineage, offset, ordinal)

    def _validate_target(self, through: Head) -> None:
        record = self._log.read(through.ordinal)
        if (
            record["lin"] != through.lineage
            or record["ord"] != through.ordinal
            or record["rh"] != through.record_hash
        ):
            raise HeadMismatch(
                "projection maintenance target is not the full head at its coordinate"
            )

    def _validate_existing(
        self, conn: sqlite3.Connection
    ) -> tuple[ResumeMark | None, str | None]:
        required = {"facts", "ticks", "store_meta"}
        tables = self._tables(conn)
        if not tables:
            # sqlite may leave a zero-schema file after a rolled-back first
            # materialization. It contains no projection evidence to recover
            # or overwrite and is equivalent to an absent derived artifact.
            return None, None
        missing = required - tables
        if missing:
            raise ArrivalCanonicalUnsupported(
                f"existing projection lacks required tables: {sorted(missing)}"
            )
        mark = self._read_mark(conn)
        rows_present = has_rows(conn)
        if mark is None and rows_present:
            raise ArrivalCanonicalUnsupported(
                "projection holds rows without an Arrival resume mark"
            )
        if mark is not None:
            anchor = self._log.anchor(mark)
            if anchor is None:
                raise ArrivalCanonicalUnsupported(
                    "projection resume mark is not a verified log boundary"
                )
            if _meta_get(conn, "coordinate_axis") != "arrival":
                raise ArrivalCanonicalUnsupported(
                    "represented projection does not declare the Arrival coordinate axis"
                )
        return mark, _meta_get(conn, "own_lineage")

    def _validate_identity(self, marker: str | None, lineage: str) -> None:
        if marker is not None and marker != lineage:
            raise ArrivalCanonicalUnsupported(
                f"projection own_lineage {marker!r} differs from log lineage {lineage!r}"
            )

    def _insert_record(self, conn: sqlite3.Connection, record: dict[str, Any]) -> None:
        for sequence, (kind, row) in enumerate(rows_of_record(record)):
            try:
                conn.execute(
                    FACT_INSERT_SQL if kind == "fact" else TICK_INSERT_SQL,
                    (*row, record["ord"], sequence),
                )
            except Exception as exc:
                raise ArrivalCanonicalUnsupported(
                    f"projection refuses {kind} {row[0]!r} from ordinal "
                    f"{record['ord']}; existing state is not a consumable prefix"
                ) from exc

    def catch_up(self, through: Head) -> MaintenanceAdvance:
        if self._closed:
            raise RuntimeError("projection maintenance handle is closed")
        self._validate_target(through)

        existed = self._path.exists()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # A competing maintainer owns a normal serialization turn, not an
        # immediate failure. Keep the wait finite so operational lock loss is
        # still reported through ProjectionSyncError with observed evidence.
        conn = sqlite3.connect(str(self._path), timeout=30.0)
        conn.isolation_level = None
        try:
            if existed:
                mark, marker = self._validate_existing(conn)
                self._validate_identity(marker, through.lineage)
            else:
                mark, marker = None, None

            # The shared schema helper owns its commits, so schema setup must
            # complete before the explicit row/watermark transaction begins.
            # It is idempotent derived structure; projection content and its
            # resume mark remain one atomic transaction below.
            _ensure_index_schema(conn, self._log)
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Revalidate all evidence after acquiring the adapter's write
                # lock. Another maintainer may have advanced or exposed a
                # conflict between the initial observation and this turn.
                mark, marker = self._validate_existing(conn)
                self._validate_identity(marker, through.lineage)
                before = (
                    None
                    if mark is None
                    else Watermark(mark.arrival_lineage, mark.arrival_ordinal)
                )

                changed = False
                last_mark = mark
                if mark is None or mark.arrival_ordinal < through.ordinal:
                    resumed, records = self._log.walk_marked(mark)
                    if mark is not None and resumed == 0:
                        raise ArrivalCanonicalUnsupported(
                            "projection resume mark was refused during verified traversal"
                        )
                    for record, record_mark in records:
                        if record["ord"] > through.ordinal:
                            break
                        if (
                            record["ord"] == through.ordinal
                            and record["rh"] != through.record_hash
                        ):
                            raise HeadMismatch(
                                "log changed at the maintenance target after full "
                                "verification"
                            )
                        self._insert_record(conn, record)
                        last_mark = record_mark
                        changed = True
                    if last_mark is None or last_mark.arrival_ordinal < through.ordinal:
                        raise HeadMismatch(
                            "verified traversal ended before the maintenance target"
                        )

                if marker is None:
                    licensed = licensed_own_lineage(conn, through.lineage)
                    if licensed is not None:
                        _meta_set(conn, "own_lineage", licensed)
                        changed = True
                if last_mark is None:
                    raise HeadMismatch("maintenance established no projection mark")
                if changed or mark != last_mark:
                    _stamp_mark(conn, last_mark)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

            after = Watermark(last_mark.arrival_lineage, last_mark.arrival_ordinal)
            return MaintenanceAdvance(before=before, after=after, changed=changed)
        finally:
            conn.close()

    def close(self) -> None:
        self._closed = True


class FileSearchMaintenance:
    """Explicit full-prefix FTS5 builder; never reached from a read snapshot."""

    def __init__(self, log_path: Path | str, index_path: Path | str) -> None:
        self._log = ArrivalLog(log_path)
        self._path = Path(index_path)
        self._closed = False

    def _coverage(self, conn: sqlite3.Connection) -> SearchCoverage | None:
        try:
            values = dict(conn.execute("SELECT key, value FROM arrival_fts_state"))
            return SearchCoverage(
                Head(values["lineage"], int(values["ordinal"]), values["record_hash"]),
                values["fields_hash"],
                values["schema_version"],
            )
        except (sqlite3.Error, KeyError, ValueError):
            return None

    def coverage(self) -> SearchCoverage | None:
        if not self._path.exists():
            return None
        conn = sqlite3.connect(str(self._path))
        try:
            return self._coverage(conn)
        finally:
            conn.close()

    def build(self, through: Head, spec: SearchFieldSpec) -> SearchIndexBuild:
        if self._closed:
            raise RuntimeError("search maintenance handle is closed")
        record = self._log.read(through.ordinal)
        if (record["lin"], record["ord"], record["rh"]) != (
            through.lineage, through.ordinal, through.record_hash
        ):
            raise HeadMismatch("search target no longer names this file prefix")
        if not self._path.exists():
            raise ProjectionAbsent("cannot build search before the projection exists")
        conn = sqlite3.connect(str(self._path), timeout=30.0)
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                lineage = _meta_get(conn, ARRIVAL_LINEAGE_KEY)
                ordinal = _meta_get(conn, ARRIVAL_ORDINAL_KEY)
                if lineage is None or ordinal is None:
                    raise ProjectionAbsent(
                        "cannot build search before the projection watermark exists"
                    )
                watermark = Watermark(str(lineage), int(str(ordinal)))
                if watermark.lineage != through.lineage or watermark.ordinal < through.ordinal:
                    raise ProjectionBehind("projection does not reach the search target")
                before = self._coverage(conn)
                conn.execute("DROP TABLE IF EXISTS arrival_facts_fts")
                conn.execute("DROP TABLE IF EXISTS arrival_fts_state")
                conn.execute(
                    "CREATE VIRTUAL TABLE arrival_facts_fts USING fts5("
                    "text_content, fact_id UNINDEXED)"
                )
                conn.execute(
                    "CREATE TABLE arrival_fts_state (key TEXT PRIMARY KEY, value TEXT)"
                )
                rows = conn.execute(
                    "SELECT id, kind, payload FROM facts WHERE arrival_ordinal <= ? "
                    "ORDER BY arrival_ordinal, arrival_seq, id", (through.ordinal,)
                ).fetchall()
                from .search_fields import extract_field_text

                for fact_id, kind, payload_text in rows:
                    fields = spec.fields_by_kind.get(kind, ())
                    if not fields:
                        continue
                    try:
                        payload = json.loads(payload_text)
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise ArrivalCanonicalUnsupported(
                            f"projected fact {fact_id!r} has invalid payload text"
                        ) from exc
                    text = " ".join(extract_field_text(payload, field) for field in fields)
                    if text.strip():
                        conn.execute(
                            "INSERT INTO arrival_facts_fts(text_content, fact_id) VALUES (?, ?)",
                            (text, fact_id),
                        )
                schema_version = str(conn.execute("PRAGMA schema_version").fetchone()[0])
                state = {
                    "lineage": through.lineage,
                    "ordinal": str(through.ordinal),
                    "record_hash": through.record_hash,
                    "fields_hash": spec.fields_hash,
                    "normalization_version": spec.normalization_version,
                    "schema_version": schema_version,
                }
                conn.executemany(
                    "INSERT INTO arrival_fts_state(key, value) VALUES (?, ?)", state.items()
                )
                conn.commit()
                after = SearchCoverage(through, spec.fields_hash, schema_version)
                return SearchIndexBuild(
                    before=before,
                    after=after,
                    changed=before != after,
                )
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    def close(self) -> None:
        self._closed = True
