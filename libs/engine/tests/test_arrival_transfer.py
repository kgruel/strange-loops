"""The transfer half: replicate, export, and the §08-default portable import.

Slice 2 / WP2 of the arrival break, against backend-contract.html §08 and
`design:arrival-break-slice2-backend-contract` §D.2. The conformance vectors in
``spec/conformance/vectors/replicate/`` state exact replication in a
language-neutral form; this file holds everything a vector cannot:

* the cases whose refusal is this BACKEND's own family rather than one of the
  five ratified contract refusals — a malformed batch, a digest that does not
  recompute, a foreign lineage. A language-neutral vector naming
  ``AppendRejected`` would pin a Python class on a Go implementation, so those
  live here (`finding:slice2-wp1-refusal-set-gaps`).
* export and import, which are byte-level and file-level rather than
  record-level claims.
* the two §12 gates §D.2 names: export → import → export byte identity, and
  snapshot consistency while another writer appends.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from engine.arrival import (
    AppendRejected,
    ArrivalCorrupt,
    ArrivalError,
    ArrivalGrammarError,
    ArrivalLog,
    Entry,
    ForkedHeight,
    GenesisRefused,
    build_record,
    content_commitment,
    encode_record,
)
from engine.arrival_contract import (
    AtomicLimitExceeded,
    ExportedPrefix,
    Head,
    HeadMismatch,
    SameHeightFork,
)
from engine.arrival_file_backend import EXPORT_CODEC, FileLedger
from tests.conftest import STUB_KEY as _KEY
from tests.conftest import stub_sign as _sign


def _head(log: ArrivalLog) -> Head:
    record = log.head()
    return Head(
        lineage=record["lin"], ordinal=record["ord"], record_hash=record["rh"]
    )


def _mint(path: Path, *, lineage: str | None = None) -> ArrivalLog:
    return ArrivalLog.mint(
        path,
        observer="kyle",
        signer=_sign,
        key=_KEY,
        lineage=lineage,
        at=1750000000.0,
    )


def _grow(log: ArrivalLog, count: int, *, tag: str = "a") -> ArrivalLog:
    log.append_marked_many(
        [
            Entry(k="note", body={"i": i, "tag": tag}, observer="kyle", at=1750000100.0 + i)
            for i in range(count)
        ]
    )
    return log


def _signed_onto(log: ArrivalLog, body: dict, *, at: float = 1750000900.0) -> dict:
    """Append one SIGNED record and return it.

    ``append_marked_many`` builds every record with ``sig=None`` — deliberately,
    ``Entry`` has no signer field — so a signed record has to be assembled and
    carried in. That is also why the catch-up vectors carry signatures: they are
    the content an assigning path cannot reproduce.
    """
    head = log.head()
    record = build_record(
        lin=head["lin"],
        ordinal=head["ord"] + 1,
        prev=head["rh"],
        k="note",
        body=body,
        observer="kyle",
        origin="",
        at=at,
        sig=_sign("kyle", content_commitment("note", at, "kyle", "", body)),
    )
    log.append_record(record)
    return record


@pytest.fixture
def authority(tmp_path: Path) -> FileLedger:
    """A five-record authority whose tail is signed."""
    log = _grow(_mint(tmp_path / "authority.arrival"), 3)
    _signed_onto(log, {"tail": "signed"})
    return FileLedger(log)


# --- export ----------------------------------------------------------------


def test_an_export_reproduces_the_logs_own_prefix_bytes(authority):
    """The framing claim, checked rather than described.

    Each element is one record's line INCLUDING its newline, so joining them is
    the file. A reader can only rely on that if the export states it, which is
    what the manifest's ``framing`` field is for.
    """
    prefix = authority.export(through=authority.head(), codec=EXPORT_CODEC)
    assert b"".join(prefix.records) == authority._log.path.read_bytes()
    assert prefix.manifest["framing"] == "newline-terminated"


def test_an_export_streams_and_reads_nothing_until_it_is_drained(authority):
    """``records`` is a generator, the same way ``scan`` and ``walk`` are.

    Checked by asking for a head this log does NOT hold: constructing the
    export must succeed and draining it must refuse, which is only true if the
    work is deferred.
    """
    absent = Head(lineage=authority.head().lineage, ordinal=99, record_hash="f" * 64)
    prefix = authority.export(through=absent, codec=EXPORT_CODEC)
    with pytest.raises(HeadMismatch):
        list(prefix.records)


def test_an_export_manifest_carries_no_clock(authority):
    """Two exports of one head are equal, field for field.

    A manifest with a timestamp or a hostname in it would make
    export → import → export byte-identical-except-for-the-parts-that-move,
    which is not a byte-identity gate at all.
    """
    head = authority.head()
    first = authority.export(through=head, codec=EXPORT_CODEC)
    second = authority.export(through=head, codec=EXPORT_CODEC)
    assert first.manifest == second.manifest
    assert first.manifest["count"] == head.ordinal + 1
    assert first.manifest["through_record_hash"] == head.record_hash


def test_export_refuses_a_codec_this_backend_does_not_have(authority):
    """A caller bug against ``capabilities()``, not a contract refusal.

    The ratified refusal set has no member for "unsupported codec", and
    picking one would be the over-claim §12's report exists to prevent.
    """
    with pytest.raises(ValueError, match=EXPORT_CODEC):
        authority.export(through=authority.head(), codec="parquet-v9")
    assert authority.capabilities().export_codecs == (EXPORT_CODEC,)


def test_an_export_stops_at_the_captured_head_not_at_the_current_one(authority):
    """§06: an ordered prefix range and NO later record."""
    captured = Head(
        lineage=authority.head().lineage,
        ordinal=2,
        record_hash=authority.read(2)["rh"],
    )
    _grow(authority._log, 2, tag="later")
    lines = list(authority.export(through=captured, codec=EXPORT_CODEC).records)
    assert len(lines) == 3
    assert json.loads(lines[-1])["rh"] == captured.record_hash


# --- §12 gate: export -> import -> export is byte-identical ------------------


def test_export_import_export_is_byte_identical(authority, tmp_path):
    """backend-contract.html:598, and the replica's file is identical too.

    Two claims in one test on purpose: a copy that round-tripped the export
    format while storing something else would satisfy the weaker one.
    """
    head = authority.head()
    first = b"".join(authority.export(through=head, codec=EXPORT_CODEC).records)

    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    assert replica.import_prefix(
        authority.export(through=head, codec=EXPORT_CODEC)
    ) == head

    again = b"".join(replica.export(through=head, codec=EXPORT_CODEC).records)
    assert again == first
    assert (tmp_path / "replica.arrival").read_bytes() == authority._log.path.read_bytes()


def test_a_replica_preserves_a_carried_in_signature(authority, tmp_path):
    """The discriminator the catch-up vectors are built on.

    An implementation that rebuilt records instead of carrying them would drop
    the signature — ``Entry`` has no signer field — and every hash from that
    height on would change. Asserted directly so the property is not only
    implied by a byte comparison.
    """
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    replica.import_prefix(
        authority.export(through=authority.head(), codec=EXPORT_CODEC)
    )
    tail = replica.read(replica.head().ordinal)
    assert tail["sig"] == authority.read(authority.head().ordinal)["sig"]
    assert tail["body"] == {"tail": "signed"}


# --- §12 gate: snapshot consistency under a concurrent writer ---------------


def test_a_snapshot_holds_while_another_writer_appends(authority):
    """backend-contract.html:597 — the prefix, and no later record.

    The export is captured, then drained one record at a time while a second
    thread appends to the same log throughout. Readers take no lock, so this is
    a genuine race rather than a serialised sequence; what makes the answer
    stable is that the captured head bounds the walk.
    """
    captured = authority.head()
    expected = b"".join(
        authority.export(through=captured, codec=EXPORT_CODEC).records
    )

    stop = threading.Event()
    faults: list[BaseException] = []

    def appender() -> None:
        try:
            i = 0
            while not stop.is_set():
                authority._log.append(
                    "note", {"racing": i}, observer="kyle", at=1750001000.0 + i
                )
                i += 1
        except BaseException as exc:  # pragma: no cover - reported, not raised here
            faults.append(exc)

    writer = threading.Thread(target=appender)
    writer.start()
    try:
        drained = b""
        for line in authority.export(through=captured, codec=EXPORT_CODEC).records:
            drained += line
    finally:
        stop.set()
        writer.join(timeout=10)

    assert not faults, faults
    assert drained == expected
    assert authority.head().ordinal > captured.ordinal, (
        "the writer never got ahead, so this proved nothing"
    )


# --- import ----------------------------------------------------------------


def test_import_into_an_empty_replica_adopts_the_authoritys_genesis(authority, tmp_path):
    """Genesis is copied, never re-minted.

    A replica whose ordinal 0 differed from the authority's by a byte would be
    a different lineage wearing the same id, so the record lands exactly as
    offered.
    """
    replica_path = tmp_path / "replica.arrival"
    replica = FileLedger(ArrivalLog(replica_path))
    replica.import_prefix(authority.export(through=authority.head(), codec=EXPORT_CODEC))
    assert ArrivalLog(replica_path).genesis() == authority._log.genesis()


def test_import_appends_only_the_remainder_to_an_agreeing_target(authority, tmp_path):
    """§08: exact prefix agreement through the target head, then the remainder."""
    partial = Head(
        lineage=authority.head().lineage,
        ordinal=1,
        record_hash=authority.read(1)["rh"],
    )
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    replica.import_prefix(authority.export(through=partial, codec=EXPORT_CODEC))
    assert replica.head().ordinal == 1

    full = authority.head()
    assert replica.import_prefix(
        authority.export(through=full, codec=EXPORT_CODEC)
    ) == full
    assert (tmp_path / "replica.arrival").read_bytes() == authority._log.path.read_bytes()


def test_re_importing_the_same_prefix_changes_nothing(authority, tmp_path):
    """The idempotent case, and the negative control for the test below.

    Agreement runs all the way THROUGH the target's head and the remainder is
    empty, so there is nothing to do and nothing missing. This is the only
    shape of "already have it" that §08 licenses, and the refusal added beside
    it must not fire here.
    """
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    full = authority.head()
    replica.import_prefix(authority.export(through=full, codec=EXPORT_CODEC))
    before = (tmp_path / "replica.arrival").read_bytes()

    assert replica.import_prefix(
        authority.export(through=full, codec=EXPORT_CODEC)
    ) == full
    assert (tmp_path / "replica.arrival").read_bytes() == before


def test_import_refuses_a_prefix_that_ends_before_the_targets_head(authority, tmp_path):
    """§08 asks for agreement THROUGH the head; a short import cannot give it.

    The target holds ordinals 0-4 and the import is a valid, manifest-clean
    export captured at ordinal 1. Everything it does carry agrees — that is
    what makes this the dangerous case rather than an obvious one. Returning
    the target's head would claim agreement through ordinal 4 while ordinals
    2-4 were never compared against anything, which is a verdict this
    operation has no evidence for.
    """
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    full = authority.head()
    replica.import_prefix(authority.export(through=full, codec=EXPORT_CODEC))
    before = (tmp_path / "replica.arrival").read_bytes()

    short = Head(
        lineage=full.lineage, ordinal=1, record_hash=authority.read(1)["rh"]
    )
    with pytest.raises(HeadMismatch) as caught:
        replica.import_prefix(authority.export(through=short, codec=EXPORT_CODEC))

    message = str(caught.value)
    assert short.record_hash in message, "the refusal must name the import's head"
    assert full.record_hash in message, "the refusal must name the target's head"
    assert (tmp_path / "replica.arrival").read_bytes() == before
    assert replica.head() == full


def test_import_refuses_a_target_that_disagrees_about_its_own_prefix(tmp_path):
    """The §08 agreement gate, and it is a fork and not a stale head.

    The two logs share a genesis and diverge above it, which is the shape a
    real fork takes — a target that merely lagged would agree everywhere it
    overlapped.
    """
    lineage = "01M2TRANSFERTESTLINEAGE000"
    left = _grow(_mint(tmp_path / "left.arrival", lineage=lineage), 2, tag="left")
    right = _grow(_mint(tmp_path / "right.arrival", lineage=lineage), 2, tag="right")
    assert ArrivalLog(left.path).genesis() == ArrivalLog(right.path).genesis()

    target = FileLedger(right)
    before = right.path.read_bytes()
    with pytest.raises(SameHeightFork, match="ordinal 1"):
        target.import_prefix(
            FileLedger(left).export(through=_head(left), codec=EXPORT_CODEC)
        )
    assert right.path.read_bytes() == before


def test_import_refuses_a_codec_and_a_framing_it_does_not_read(authority, tmp_path):
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    real = authority.export(through=authority.head(), codec=EXPORT_CODEC)

    with pytest.raises(ValueError, match="codec"):
        replica.import_prefix(
            ExportedPrefix(
                head=real.head, codec="parquet-v9", records=iter([]), manifest={}
            )
        )
    with pytest.raises(ValueError, match="framing"):
        replica.import_prefix(
            ExportedPrefix(
                head=real.head,
                codec=EXPORT_CODEC,
                records=iter([]),
                manifest={**real.manifest, "framing": "length-prefixed"},
            )
        )
    assert not (tmp_path / "replica.arrival").exists()


@pytest.mark.parametrize(
    ("field", "value", "why"),
    [
        ("count", 99, "a count that does not match the records it describes"),
        ("through_ordinal", 99, "a captured ordinal the records do not reach"),
        ("through_record_hash", "f" * 64, "a captured hash the records do not carry"),
        ("lineage", "SOMETHING-ELSE", "a lineage the records do not belong to"),
        ("protocol", 99, "a grammar this backend does not read"),
    ],
)
def test_import_checks_every_manifest_claim_against_the_records(
    authority, tmp_path, field, value, why
):
    """A manifest travels with its bytes, so it is exactly as trustworthy.

    Every field re-derived and compared: a count that matched while the head
    did not would still be a corrupt export, so sampling one claim is not
    checking the manifest.
    """
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    real = authority.export(through=authority.head(), codec=EXPORT_CODEC)
    with pytest.raises(ArrivalCorrupt):
        replica.import_prefix(
            ExportedPrefix(
                head=real.head,
                codec=real.codec,
                records=real.records,
                manifest={**real.manifest, field: value},
            )
        )
    assert not (tmp_path / "replica.arrival").exists(), why


def test_import_refuses_a_suffix_dressed_as_a_prefix(authority, tmp_path):
    """A prefix runs from genesis. One that does not is a suffix, and
    importing a suffix is replication."""
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    real = authority.export(through=authority.head(), codec=EXPORT_CODEC)
    tail = list(real.records)[1:]
    with pytest.raises(ArrivalCorrupt, match="not 0"):
        replica.import_prefix(
            ExportedPrefix(
                head=real.head,
                codec=real.codec,
                records=iter(tail),
                manifest={**real.manifest, "count": len(tail)},
            )
        )


def test_import_refuses_a_record_whose_digest_does_not_recompute(authority, tmp_path):
    """Bytes that travelled are re-established, never assumed."""
    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    real = authority.export(through=authority.head(), codec=EXPORT_CODEC)
    lines = list(real.records)
    tampered = json.loads(lines[-1])
    tampered["body"] = {"tail": "TAMPERED"}
    lines[-1] = (json.dumps(tampered, separators=(",", ":")) + "\n").encode()

    with pytest.raises(ArrivalGrammarError):
        replica.import_prefix(
            ExportedPrefix(
                head=real.head,
                codec=real.codec,
                records=iter(lines),
                manifest=real.manifest,
            )
        )


# --- adopt_genesis ----------------------------------------------------------


def test_adopt_genesis_refuses_a_record_that_is_not_one(tmp_path):
    """The same structural gate a walk holds ordinal 0 to."""
    source = _grow(_mint(tmp_path / "source.arrival"), 1)
    with pytest.raises(GenesisRefused, match="not a genesis"):
        ArrivalLog.adopt_genesis(tmp_path / "new.arrival", source.read(1))
    assert not (tmp_path / "new.arrival").exists()


def test_adopt_genesis_refuses_to_publish_over_an_existing_log(tmp_path):
    """A lineage is opened once; publishing over a log would destroy a store."""
    existing = _mint(tmp_path / "s.arrival")
    before = existing.path.read_bytes()
    other = _mint(tmp_path / "other.arrival")
    with pytest.raises(GenesisRefused, match="already exists"):
        ArrivalLog.adopt_genesis(existing.path, other.genesis())
    assert existing.path.read_bytes() == before


def test_adopt_genesis_checks_the_supplied_digest_rather_than_trusting_it(tmp_path):
    source = _mint(tmp_path / "source.arrival")
    tampered = dict(source.genesis())
    tampered["observer"] = "someone-else"
    with pytest.raises(ArrivalGrammarError, match="rh"):
        ArrivalLog.adopt_genesis(tmp_path / "new.arrival", tampered)
    assert not (tmp_path / "new.arrival").exists()


# --- replicate: the refusals a vector may not name --------------------------


def test_replicate_refuses_an_empty_batch(authority):
    with pytest.raises(ValueError, match="empty replication"):
        authority.replicate(authority.head(), [])


def test_replicate_refuses_a_record_whose_supplied_digest_is_wrong(authority):
    """``rh`` supplied is CHECKED, never trusted — the posture that makes
    ``append_record`` the right primitive to compose replication from.

    The record sits at head + 1, where nothing is occupied, so the refusal can
    only come from the digest and not from the fork check one branch away.
    """
    head = authority.head()
    offered = build_record(
        lin=head.lineage,
        ordinal=head.ordinal + 1,
        prev=head.record_hash,
        k="note",
        body={"i": "wrong-digest"},
        observer="kyle",
        at=1750005000.0,
    )
    offered["rh"] = "f" * 64
    before = authority._log.path.read_bytes()
    with pytest.raises(ArrivalGrammarError, match="rh"):
        authority.replicate(None, [offered])
    assert authority._log.path.read_bytes() == before


def test_replicate_refuses_a_foreign_lineage_as_this_backends_own_fault(authority, tmp_path):
    """Not one of the five ratified refusals, and deliberately untranslated.

    Choosing a contract refusal for "this record belongs to another lineage"
    would be a verdict the evidence does not support
    (`finding:slice2-wp1-refusal-set-gaps`).
    """
    foreign = _mint(tmp_path / "foreign.arrival", lineage="01M2FOREIGNLINEAGE0000000")
    head = authority.head()
    stranger = build_record(
        lin=foreign.lineage(),
        ordinal=head.ordinal + 1,
        prev=head.record_hash,
        k="note",
        body={"from": "elsewhere"},
        observer="kyle",
        at=1750002000.0,
    )
    with pytest.raises(AppendRejected, match="lineage"):
        authority.replicate(None, [stranger])


def test_replicate_refuses_an_internally_inconsistent_batch_and_lands_none_of_it(
    authority, tmp_path
):
    """All or nothing: a batch is one logical group or it is not a batch.

    The bad record sits second, so a per-record appender would already have
    written the first one when it refused.
    """
    head = authority.head()
    good = build_record(
        lin=head.lineage,
        ordinal=head.ordinal + 1,
        prev=head.record_hash,
        k="note",
        body={"i": "good"},
        observer="kyle",
        at=1750002000.0,
    )
    skipped = build_record(
        lin=head.lineage,
        ordinal=head.ordinal + 3,  # a hole
        prev=good["rh"],
        k="note",
        body={"i": "skipped"},
        observer="kyle",
        at=1750002001.0,
    )
    before = authority._log.path.read_bytes()
    with pytest.raises(AppendRejected, match="ord"):
        authority.replicate(head, [good, skipped])
    assert authority._log.path.read_bytes() == before


def test_replicate_refuses_more_records_than_the_configured_atomic_limit(authority):
    """§04: refuse BEFORE mutation. A partially applied suffix is the one
    artifact a replica must never hold."""
    head = authority.head()
    records = []
    prev = head.record_hash
    for i in range(3):
        record = build_record(
            lin=head.lineage,
            ordinal=head.ordinal + 1 + i,
            prev=prev,
            k="note",
            body={"i": i},
            observer="kyle",
            at=1750003000.0 + i,
        )
        records.append(record)
        prev = record["rh"]

    limited = FileLedger(authority._log, max_atomic_records=2)
    before = authority._log.path.read_bytes()
    with pytest.raises(AtomicLimitExceeded, match="atomic limit"):
        limited.replicate(head, records)
    assert authority._log.path.read_bytes() == before
    assert limited.capabilities().max_atomic_records == 2

    # And the same batch under the limit lands, so the refusal is a limit and
    # not a blanket refusal.
    assert limited.replicate(head, records[:2]).after.ordinal == head.ordinal + 2


def test_an_unpinned_replication_is_still_a_replication(authority, tmp_path):
    """``expected=None`` drops the compare-and-swap, not the validation.

    F1 refuses a WEAKER pin, never the absence of one; an unpinned replicate
    still assigns nothing and still refuses a fork.
    """
    source_head = authority.head()
    record = build_record(
        lin=source_head.lineage,
        ordinal=source_head.ordinal + 1,
        prev=source_head.record_hash,
        k="note",
        body={"unpinned": True},
        observer="kyle",
        at=1750004000.0,
    )
    commit = authority.replicate(None, [record])
    assert commit.after.record_hash == record["rh"]
    assert authority.read(commit.after.ordinal) == record


def test_the_arrival_layer_raises_its_own_fork_type_not_the_contracts(tmp_path):
    """The adapter translates 1:1; the log below it never speaks contract.

    ``ForkedHeight`` is an ``ArrivalError`` and deliberately NOT an
    ``AppendRejected``: ``store.merge_store`` retries on that family, and a
    fork caught by a retry loop would spin rather than surface.
    """
    lineage = "01M2FORKTYPETESTLINEAGE00"
    left = _grow(_mint(tmp_path / "left.arrival", lineage=lineage), 2, tag="left")
    right = _grow(_mint(tmp_path / "right.arrival", lineage=lineage), 2, tag="right")

    with pytest.raises(ForkedHeight) as caught:
        right.append_records([left.read(1)])
    assert not isinstance(caught.value, AppendRejected)
    assert isinstance(caught.value, ArrivalError)


def test_append_records_refuses_an_empty_batch(tmp_path):
    log = _mint(tmp_path / "s.arrival")
    with pytest.raises(ArrivalError, match="no records"):
        log.append_records([])


def test_a_replicated_suffix_is_byte_identical_to_the_source_bytes(tmp_path):
    """The property the catch-up family exists to state, at the file level."""
    lineage = "01M2BYTEIDENTITYLINEAGE00"
    source = _grow(_mint(tmp_path / "source.arrival", lineage=lineage), 2)
    _signed_onto(source, {"tail": "signed"})

    replica = FileLedger(ArrivalLog(tmp_path / "replica.arrival"))
    partial = Head(lineage=lineage, ordinal=1, record_hash=source.read(1)["rh"])
    replica.import_prefix(
        FileLedger(source).export(through=partial, codec=EXPORT_CODEC)
    )
    replica.replicate(replica.head(), [source.read(2), source.read(3)])

    assert (tmp_path / "replica.arrival").read_bytes() == source.path.read_bytes()


def test_a_replicated_record_re_encodes_to_the_bytes_it_arrived_as(tmp_path):
    """One record, one line, unchanged — the claim without the file around it."""
    lineage = "01M2LINEIDENTITYLINEAGE00"
    source = _grow(_mint(tmp_path / "source.arrival", lineage=lineage), 1)
    offered = source.read(1)

    replica_log = ArrivalLog.adopt_genesis(
        tmp_path / "replica.arrival", source.genesis()
    )
    FileLedger(replica_log).replicate(None, [offered])
    assert replica_log.path.read_text().splitlines()[1] == encode_record(offered)
