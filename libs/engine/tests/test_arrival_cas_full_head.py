"""F1: the append compare-and-swap pins the FULL head, at both sites.

``design:arrival-break-slice2-backend-contract`` SD-2. Before slice 2 both
append sites compared one field — the head's ordinal — which answers "has the
log grown?" and not the question a compare-and-swap is asked, which is "is
this still the same log?". A target truncated and rewritten to the same height
passes an ordinal compare, and the backend contract asks a store to detect
exactly that (backend-contract.html §11, rollback and same-height fork).

There are TWO sites and they are pinned separately here, because they are
separately reachable: :meth:`ArrivalLog.append_marked` is the ceremony path
(``ArrivalStore._ceremony_persist``) and :meth:`ArrivalLog.append_marked_many`
is the merge path (``store.merge_store``). Closing one and leaving the other
would put the weaker pin one method call away.

Also here, because they are the same subject: §12's executable gates for the
race (":592 — race two writers at one expected head; exactly one commit
wins") and for injected failure (":593 — inject a failure at every append
stage and prove no partial logical group is visible").
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from engine.arrival import (
    ArrivalError,
    ArrivalLog,
    Entry,
    StaleHead,
    build_record,
    encode_record,
)
from engine.arrival_contract import Head
from tests.conftest import STUB_KEY as _KEY
from tests.conftest import stub_sign as _sign


def _log(tmp_path: Path) -> ArrivalLog:
    return ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY
    )


def _head(log: ArrivalLog) -> Head:
    record = log.head()
    return Head(
        lineage=record["lin"], ordinal=record["ord"], record_hash=record["rh"]
    )


def _roll_back_to(path: Path, keep: int) -> None:
    """Cut the log back to ``keep`` records, in the bytes.

    A rollback as an administrator or a restored backup would produce one:
    the file is a valid shorter prefix afterwards, which is precisely why
    §11 says detecting it needs a head retained outside the store.
    """
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:keep]))


def _rewritten_to_the_same_height(tmp_path: Path) -> tuple[ArrivalLog, Head]:
    """A log rolled back and re-grown to the same ordinal with other content.

    Returns the log and the head that USED to be there. The returned head has
    the ordinal the log's head has right now and a different record hash —
    the one case an ordinal-only compare cannot see, and therefore the case
    that makes the full-head compare more than a rename.
    """
    log = _log(tmp_path)
    log.append("note", {"i": 1}, observer="kyle")
    superseded = _head(log)

    _roll_back_to(log.path, keep=1)
    log.append("note", {"i": 999}, observer="kyle")

    now = _head(log)
    assert now.ordinal == superseded.ordinal, "the heights must agree"
    assert now.record_hash != superseded.record_hash, "the records must differ"
    return log, superseded


# --- site A: append_marked (the ceremony path) ------------------------------


def test_site_a_refuses_a_head_rewritten_to_the_same_ordinal(tmp_path):
    """append_marked: same height, different record — refused.

    The discriminating case. An ordinal-only compare accepts this append;
    the full-head compare refuses it.
    """
    log, superseded = _rewritten_to_the_same_height(tmp_path)
    before = log.path.read_bytes()

    with pytest.raises(StaleHead):
        log.append_marked("note", {}, observer="kyle", following=superseded)

    assert log.path.read_bytes() == before, "a refused append writes nothing"


def test_site_a_refuses_a_head_from_another_lineage(tmp_path):
    """append_marked: right ordinal and hash, wrong lineage — refused.

    The second field an ordinal-only compare cannot see. A pin naming
    another lineage is not stale, it is about a different log.
    """
    log = _log(tmp_path)
    log.append("note", {"i": 1}, observer="kyle")
    head = _head(log)
    foreign = Head(
        lineage="01FOREIGNLINEAGE0000000000",
        ordinal=head.ordinal,
        record_hash=head.record_hash,
    )
    before = log.path.read_bytes()

    with pytest.raises(StaleHead):
        log.append_marked("note", {}, observer="kyle", following=foreign)

    assert log.path.read_bytes() == before


def test_site_a_refuses_when_a_record_arrived_since(tmp_path):
    """append_marked: the ordinary interloper, still refused."""
    log = _log(tmp_path)
    head = _head(log)
    log.append("note", {"i": 1}, observer="kyle")  # the interloper

    with pytest.raises(StaleHead, match="arrived since"):
        log.append_marked("note", {}, observer="kyle", following=head)


def test_site_a_accepts_the_current_head(tmp_path):
    """The pin is a compare, not a refusal: the true head is accepted."""
    log = _log(tmp_path)
    record, _ = log.append_marked(
        "note", {}, observer="kyle", following=_head(log)
    )
    assert record["ord"] == 1


# --- site B: append_marked_many (the merge path) ----------------------------


def test_site_b_refuses_a_head_rewritten_to_the_same_ordinal(tmp_path):
    """append_marked_many: same height, different record — refused.

    Site A's discriminating case, at the site a merge actually appends
    through. Closed here independently: the two methods do not share a
    compare, they each call one.
    """
    log, superseded = _rewritten_to_the_same_height(tmp_path)
    before = log.path.read_bytes()

    with pytest.raises(StaleHead):
        log.append_marked_many(
            [Entry(k="note", body={}, observer="kyle")], following=superseded
        )

    assert log.path.read_bytes() == before, "a refused append writes nothing"


def test_site_b_refuses_a_head_from_another_lineage(tmp_path):
    log = _log(tmp_path)
    log.append("note", {"i": 1}, observer="kyle")
    head = _head(log)
    foreign = Head(
        lineage="01FOREIGNLINEAGE0000000000",
        ordinal=head.ordinal,
        record_hash=head.record_hash,
    )
    before = log.path.read_bytes()

    with pytest.raises(StaleHead):
        log.append_marked_many(
            [Entry(k="note", body={}, observer="kyle")], following=foreign
        )

    assert log.path.read_bytes() == before


def test_site_b_refuses_when_a_record_arrived_since(tmp_path):
    log = _log(tmp_path)
    head = _head(log)
    log.append("note", {"i": 1}, observer="kyle")

    with pytest.raises(StaleHead, match="arrived since"):
        log.append_marked_many(
            [Entry(k="note", body={}, observer="kyle")], following=head
        )


def test_site_b_accepts_the_current_head(tmp_path):
    log = _log(tmp_path)
    records, _ = log.append_marked_many(
        [Entry(k="note", body={"i": i}, observer="kyle") for i in range(3)],
        following=_head(log),
    )
    assert [r["ord"] for r in records] == [1, 2, 3]


# --- the bare ordinal is refused, not widened -------------------------------


@pytest.mark.parametrize("site", ["append_marked", "append_marked_many"])
def test_a_bare_ordinal_pin_is_refused_at_both_sites(tmp_path, site):
    """Construction over detection: there is no weaker pin to reach for.

    Accepting an ordinal and widening it internally would mean the callee
    inventing the two fields the caller did not supply — a pin the callee
    completed is not a pin. The refusal is an ``ArrivalError`` and
    deliberately NOT an ``AppendRejected``: ``store.merge_store`` retries on
    ``AppendRejected``, and a caller's type error caught by that loop would
    spin for the whole attempt budget instead of surfacing.
    """
    log = _log(tmp_path)
    before = log.path.read_bytes()

    with pytest.raises(ArrivalError, match="bare ordinal") as caught:
        if site == "append_marked":
            log.append_marked("note", {}, observer="kyle", following=0)
        else:
            log.append_marked_many(
                [Entry(k="note", body={}, observer="kyle")], following=0
            )

    from engine.arrival import AppendRejected

    assert not isinstance(caught.value, AppendRejected)
    assert log.path.read_bytes() == before


@pytest.mark.parametrize("site", ["append_marked", "append_marked_many"])
def test_an_unpinned_append_stays_legal_at_both_sites(tmp_path, site):
    """F1 refuses a WEAKER pin, not the absence of one.

    ``following=None`` is a caller that is not claiming to know the head.
    That is a different statement from claiming to know it and being wrong,
    and nothing in F1 makes it illegal.
    """
    log = _log(tmp_path)
    if site == "append_marked":
        record, _ = log.append_marked("note", {}, observer="kyle")
    else:
        records, _ = log.append_marked_many(
            [Entry(k="note", body={}, observer="kyle")]
        )
        record = records[0]
    assert record["ord"] == 1


# --- §12 gate: race two writers at one expected head ------------------------


def test_two_writers_at_one_expected_head_and_exactly_one_wins(tmp_path):
    """backend-contract.html:592, deterministically.

    Both writers capture the same head; both then append pinned to it. The
    first lands, the second's pin no longer describes the log and it
    refuses. "Exactly one commit wins" is asserted on the log, not on the
    return values: one record arrived.
    """
    log = ArrivalLog(_log(tmp_path).path)
    expected = _head(log)

    writer_a = ArrivalLog(log.path)
    writer_b = ArrivalLog(log.path)

    writer_a.append_marked_many(
        [Entry(k="note", body={"w": "a"}, observer="kyle")], following=expected
    )
    with pytest.raises(StaleHead):
        writer_b.append_marked_many(
            [Entry(k="note", body={"w": "b"}, observer="kyle")],
            following=expected,
        )

    landed = [r for r in log.walk() if r["ord"] > 0]
    assert len(landed) == 1
    assert landed[0]["body"]["w"] == "a"


def test_a_real_race_of_many_writers_admits_exactly_one(tmp_path):
    """The same gate under genuine concurrency.

    Eight threads, one barrier, one expected head. The flock serialises them
    and the full-head compare refuses everyone who arrives after the winner,
    so the log grows by exactly one record no matter who gets there first.
    """
    log = ArrivalLog(_log(tmp_path).path)
    expected = _head(log)
    writers = 8
    barrier = threading.Barrier(writers)
    won: list[str] = []
    refused: list[str] = []
    lock = threading.Lock()

    def race(name: str) -> None:
        handle = ArrivalLog(log.path)
        barrier.wait()
        try:
            handle.append_marked_many(
                [Entry(k="note", body={"w": name}, observer="kyle")],
                following=expected,
            )
        except StaleHead:
            with lock:
                refused.append(name)
        else:
            with lock:
                won.append(name)

    threads = [
        threading.Thread(target=race, args=(str(i),)) for i in range(writers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(won) == 1, f"expected one winner, got {won}"
    assert len(refused) == writers - 1
    landed = [r for r in log.walk() if r["ord"] > 0]
    assert len(landed) == 1
    assert landed[0]["body"]["w"] == won[0]


# --- §12 gate: inject a failure at every append stage ------------------------
#
# What "logical group" means here, stated so the claim is not read wider than
# the evidence. For an arrival log the atomic unit is ONE RECORD: a ceremony
# carrying several rows becomes one `batch` record precisely so recovery can
# never expose half of it (`arrival_store.ArrivalStore._ceremony_persist`).
# `append_marked_many` puts SEVERAL records under one lock for a different
# reason — dedup correctness across concurrent mergers — and its documented
# recovery is "re-run the merge", which dedup makes idempotent. So the
# invariant proved below is: no partial RECORD is ever visible, and whatever
# prefix survives a failure is a dense, chaining, fully verifiable log. It is
# NOT a claim that a multi-record append is all-or-nothing on disk, which the
# design does not make either.


def _stage_failures():
    """(name, patch) for each stage of the append transition (§04's steps)."""

    def fence(monkeypatch):
        monkeypatch.setattr(
            ArrivalLog,
            "_locked_head",
            lambda self: (_ for _ in ()).throw(OSError("fence failed")),
        )

    def assign(monkeypatch):
        calls = {"n": 0}

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError("coordinate assignment failed")
            return build_record(**kwargs)

        monkeypatch.setattr("engine.arrival.build_record", flaky)

    def validate(monkeypatch):
        monkeypatch.setattr(
            ArrivalLog,
            "_check_follows",
            staticmethod(
                lambda record, head: (_ for _ in ()).throw(
                    OSError("validation failed")
                )
            ),
        )

    def encode(monkeypatch):
        calls = {"n": 0}

        def flaky(record):
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError("encode failed")
            return encode_record(record)

        monkeypatch.setattr("engine.arrival.encode_record", flaky)

    def durability(monkeypatch):
        monkeypatch.setattr(
            "engine.arrival.os.fsync",
            lambda fd: (_ for _ in ()).throw(OSError("fsync failed")),
        )

    return [
        ("fence", fence),
        ("assign", assign),
        ("validate", validate),
        ("encode", encode),
        ("durability", durability),
    ]


def _assert_walkable_dense_prefix(log: ArrivalLog, ceiling: int) -> int:
    """The log is a dense verified prefix of at most ``ceiling`` records.

    ``walk`` is the integrity statement — it re-decodes, recomputes every
    ``rh``, and refuses a gap, a repeat or a broken ``prev`` link — so the
    fact that it completes IS the "no partial record, no silent gap" claim.
    """
    records = list(log.walk())
    assert [r["ord"] for r in records] == list(range(len(records)))
    assert len(records) <= ceiling
    return len(records)


@pytest.mark.parametrize("stage, patch", _stage_failures(), ids=lambda v: v)
def test_a_failure_at_any_append_stage_exposes_no_partial_record(
    tmp_path, monkeypatch, stage, patch
):
    """backend-contract.html:593 — every stage, nothing partial visible."""
    log = _log(tmp_path)
    log.append("note", {"i": 0}, observer="kyle")
    before = log.path.read_bytes()
    entries = [Entry(k="note", body={"i": i}, observer="kyle") for i in (1, 2)]

    patch(monkeypatch)
    with pytest.raises(OSError):
        log.append_marked_many(entries, following=_head(log))
    monkeypatch.undo()

    reader = ArrivalLog(log.path)
    visible = _assert_walkable_dense_prefix(reader, ceiling=4)
    if stage == "durability":
        # The bytes reached the file and the fsync did not confirm them:
        # §05's "acknowledgment lost" outcome. The caller is told the result
        # is unknown, NOT that the append failed — so both records being
        # visible is correct, and what must hold is that neither is partial.
        assert visible == 4
    else:
        assert visible == 2, "no byte of the refused group may be visible"
        assert log.path.read_bytes() == before


def test_a_crash_at_any_byte_of_the_write_never_exposes_a_partial_record(
    tmp_path,
):
    """The write stage, injected at EVERY byte rather than at one point.

    A crash during the write is observationally a file truncated somewhere
    inside the appended region, so the honest injection is every such
    position. At each one the surviving log must still be a dense, fully
    verified prefix — a partial record is never yielded, because the reader
    stops at an unterminated line and the writer truncates it under the lock.
    """
    log = _log(tmp_path)
    log.append("note", {"i": 0}, observer="kyle")
    prefix = log.path.read_bytes()
    entries = [Entry(k="note", body={"i": i}, observer="kyle") for i in (1, 2)]
    log.append_marked_many(entries, following=_head(log))
    whole = log.path.read_bytes()

    for cut in range(len(prefix), len(whole) + 1):
        log.path.write_bytes(whole[:cut])
        reader = ArrivalLog(log.path)
        visible = _assert_walkable_dense_prefix(reader, ceiling=4)
        assert visible >= 2, "the pre-append prefix must always survive"
        # And the writer can always resume: truncating the torn tail under
        # the lock is what makes the interrupted append recoverable rather
        # than a store a human has to repair.
        ArrivalLog(log.path).truncate_torn_tail()
        assert _assert_walkable_dense_prefix(ArrivalLog(log.path), 4) == visible


def test_a_multi_row_ceremony_is_one_record_so_it_is_never_partial(tmp_path):
    """The group that MUST be atomic is atomic by construction.

    A ceremony carrying several rows becomes one ``batch`` record, so there
    is no byte position at which half a ceremony is visible — the record
    either terminates or it does not. This is why the gate above scopes its
    claim to the record: for the group that would actually be corrupted by a
    partial write, the record IS the group.
    """
    from engine.arrival_body import body_of_batch

    log = _log(tmp_path)
    rows = [
        ("01AAAAAAAAAAAAAAAAAAAAAAAA", "note", 1.0, "kyle", "", '{"i": 1}'),
        ("01BBBBBBBBBBBBBBBBBBBBBBBB", "note", 1.0, "kyle", "", '{"i": 2}'),
    ]
    log.append_marked(
        "batch", body_of_batch(rows), observer="kyle", at=1.0,
        following=_head(log),
    )

    whole = log.path.read_bytes()
    for cut in range(len(whole) + 1):
        log.path.write_bytes(whole[:cut])
        records = list(ArrivalLog(log.path).walk()) if cut else []
        ceremonies = [r for r in records if r["k"] == "batch"]
        # Zero or one, never a fragment carrying one of the two rows.
        assert len(ceremonies) in (0, 1)
        if ceremonies:
            assert len(ceremonies[0]["body"]["rows"]) == 2


# --- completing the pin: refuse, never fall back --------------------------
#
# The resume mark carries no record hash, so both F1 callers complete their
# pin by reading the record the mark names (`ArrivalLog.anchor`). When the log
# will not vouch for one, there is a fork in the road that the type system
# cannot see: refuse, or quietly pass `following=None`. The second is a silent
# downgrade to an UNPINNED append — the exact weakening F1 exists to prevent,
# and it would be invisible in a green suite because an unpinned append
# succeeds. So the branch is pinned here rather than argued in a docstring.


def _unanchorable(log: ArrivalLog):
    """A mark that is well-formed but that the log will not vouch for.

    The offset lands mid-record rather than on a boundary, so `_anchor_for`
    finds no record ending there and rejects. Chosen over a foreign lineage
    because it is the shape a real disagreement takes — an index whose
    recorded position the log cannot confirm.
    """
    from engine.arrival import ResumeMark

    return ResumeMark(
        arrival_lineage=log.lineage(), arrival_offset=3, arrival_ordinal=0
    )


def test_the_ceremony_refuses_an_unanchorable_mark_rather_than_unpinning(
    tmp_path,
):
    """ArrivalStore's pin completion (F1 caller 2 — report §2 D1)."""
    from atoms import Fact

    from engine.arrival_store import ArrivalCanonicalUnsupported, ArrivalStore

    log = _log(tmp_path)
    store = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=_sign,
    )
    try:
        with pytest.raises(ArrivalCanonicalUnsupported, match="does not "):
            store._pinned_head(_unanchorable(log))
        # And the refusal does not over-fire: no mark is still no pin, which
        # is a different statement from a mark the log rejects.
        assert store._pinned_head(None) is None
    finally:
        store.close()


def test_fsync_is_the_stage_the_durability_claim_rests_on(tmp_path):
    """A guard on the injection above: `os.fsync` is genuinely called.

    Without this, the `durability` stage could pass by patching something
    the append never reaches, and the gate would be asserting nothing.
    """
    log = _log(tmp_path)
    calls: list[int] = []
    real = os.fsync

    def counting(fd):
        calls.append(fd)
        return real(fd)

    import engine.arrival as arrival_module

    original = arrival_module.os.fsync
    arrival_module.os.fsync = counting
    try:
        log.append_marked_many(
            [Entry(k="note", body={}, observer="kyle")], following=_head(log)
        )
    finally:
        arrival_module.os.fsync = original
    assert calls, "append_marked_many must fsync before reporting success"
