"""The slice-0 empirical gate (§3.5 of the arrival record-grammar design fact).

Six properties, exercised with **real operating-system processes** wherever
concurrency or a crash is the subject. Threads would not do: they share a file
descriptor table and a GIL, so they pass a test a fork fails, and the whole
point of these six is that the concurrency contract has never been exercised.

Test 1 is the gate. If it does not run as separate processes, slice 0 is not
gated.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from engine.arrival import (
    AppendRejected,
    ArrivalCorrupt,
    ArrivalLog,
    GenesisRefused,
    ResumeMark,
    build_record,
    encode_record,
    record_hash,
)

WRITERS = 4
APPENDS = 250


def _sign(observer: str, commitment: str) -> str:
    return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()


def _mint(tmp_path, name: str = "alcove") -> ArrivalLog:
    return ArrivalLog.mint(tmp_path / f"{name}.arrival", observer="kyle", signer=_sign)


def _run(script: str, *args: str, tmp_path, name: str = "worker") -> subprocess.Popen:
    """Launch a real process running ``script`` against this test's venv."""
    path = tmp_path / f"{name}.py"
    path.write_text(textwrap.dedent(script))
    return subprocess.Popen(
        [sys.executable, str(path), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _verify_by_hand(log: ArrivalLog, expected_count: int) -> None:
    """Re-derive every invariant from the bytes, without using ``walk``.

    ``walk`` is what most of the module's own error paths run through, so
    checking the file with it would let one bug hide another. Here the file
    is decoded as plain JSON and every rule is restated.
    """
    raw = log.path.read_bytes()
    assert raw.endswith(b"\n"), "the log does not end on a record boundary"
    lines = raw[:-1].split(b"\n")
    assert len(lines) == expected_count, f"{len(lines)} records, expected {expected_count}"

    prev = None
    lineage = None
    for ordinal, line in enumerate(lines):
        record = json.loads(line)
        assert record["ord"] == ordinal, f"ord {record['ord']} at position {ordinal}"
        if ordinal == 0:
            lineage = record["lin"]
            assert record["prev"] is None
        else:
            assert record["lin"] == lineage
        assert record["prev"] == prev, f"prev broken at ordinal {ordinal}"
        assert record["rh"] == record_hash(record), f"rh broken at ordinal {ordinal}"
        prev = record["rh"]


# ---------------------------------------------------------------------------
# 1. Concurrent append, dense ordinals — THE GATE
# ---------------------------------------------------------------------------

_APPEND_WORKER = """
    import sys
    from engine.arrival import ArrivalLog

    path, count, tag = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    log = ArrivalLog(path)
    for i in range(count):
        # No retry on purpose. The lock is supposed to make every append
        # succeed first time; a rejection here means the head was read
        # outside the critical section, and the worker must fail loudly
        # rather than paper over it.
        log.append("note", {"w": tag, "i": i}, observer=tag)
    """


def test_gate_concurrent_append_keeps_ordinals_dense(tmp_path):
    """Four processes × 250 appends each against one log.

    Exactly N×M+1 records, every line decodes, ordinals run 0..N×M with no
    gap and no repeat, every ``prev`` matches its predecessor's ``rh``, and
    every ``rh`` recomputes. This is the test the whole design exists to
    pass.
    """
    log = _mint(tmp_path)
    workers = [
        _run(_APPEND_WORKER, str(log.path), str(APPENDS), f"w{n}",
             tmp_path=tmp_path, name=f"append{n}")
        for n in range(WRITERS)
    ]
    for n, worker in enumerate(workers):
        out, err = worker.communicate(timeout=600)
        assert worker.returncode == 0, f"writer {n} failed:\n{out}\n{err}"

    _verify_by_hand(log, WRITERS * APPENDS + 1)

    # And the module's own walk agrees with the hand check.
    walked = list(log.walk())
    assert [r["ord"] for r in walked] == list(range(WRITERS * APPENDS + 1))
    # Every writer's appends all landed, and none landed twice.
    from collections import Counter

    tally = Counter(r["body"]["w"] for r in walked[1:])
    assert tally == {f"w{n}": APPENDS for n in range(WRITERS)}


# ---------------------------------------------------------------------------
# 2. Torn tail from a real kill
# ---------------------------------------------------------------------------

_CAPPED_WORKER = """
    import resource, sys
    from engine.arrival import ArrivalLog

    # A hard file-size cap turns one append into a genuine SHORT WRITE: the
    # kernel writes bytes up to the cap and then refuses the rest, killing
    # the process (SIGXFSZ where that is the default action, EFBIG where it
    # is not). Either way this is a real process interrupted partway through
    # a real append, leaving real partial bytes at the tail.
    path, cap = sys.argv[1], int(sys.argv[2])
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    log = ArrivalLog(path)
    log.append("bulk", {"blob": "x" * (4 * 1024 * 1024)}, observer="kyle")
    print("SURVIVED")  # the cap did not bite — the test asserts against this
    """

_SIGKILL_WORKER = """
    import sys
    from engine.arrival import ArrivalLog

    path = sys.argv[1]
    log = ArrivalLog(path)
    blob = "x" * (2 * 1024 * 1024)
    log.append("bulk", {"blob": blob, "n": -1}, observer="kyle")
    print("READY", flush=True)
    n = 0
    while True:
        log.append("bulk", {"blob": blob, "n": n}, observer="kyle")
        n += 1
    """

_PARTIAL_BYTES = 100_000


def test_gate_torn_tail_from_a_real_crash_truncates_exactly_the_partial_bytes(tmp_path):
    """A writer killed partway through a 4MB append leaves a partial record;
    the next open under the lock cuts exactly those bytes and no more."""
    log = _mint(tmp_path)
    cap = log.path.stat().st_size + _PARTIAL_BYTES
    worker = _run(_CAPPED_WORKER, str(log.path), str(cap), tmp_path=tmp_path, name="capped")
    out, err = worker.communicate(timeout=120)
    assert worker.returncode != 0, f"the file-size cap did not bite: {out}{err}"

    torn = log.path.read_bytes()
    assert not torn.endswith(b"\n"), "the append was not interrupted mid-record"

    # The partial record is the bytes after the last complete one.
    cut_point = torn.rfind(b"\n") + 1
    partial = len(torn) - cut_point
    assert partial > 0
    prefix = torn[:cut_point]

    # The reader does NOT truncate and does not choke on the tail.
    before = log.path.read_bytes()
    assert list(log.walk())  # the complete prefix reads fine
    assert log.path.read_bytes() == before, "the read path truncated"

    # The next open under the lock cuts exactly those bytes and no more.
    assert log.truncate_torn_tail() == partial
    assert log.path.read_bytes() == prefix

    # The surviving prefix is intact and append-able.
    head = log.head()
    log.append("note", {"after": "the tear"}, observer="kyle")
    assert log.head()["ord"] == head["ord"] + 1
    _verify_by_hand(log, head["ord"] + 2)


def test_a_real_sigkill_cannot_tear_an_append(tmp_path):
    """An empirical result worth pinning, not an absent test.

    §3.5 asks for a torn tail from a SIGKILL. Repeated real kills against a
    real writer never produce one, and the reason is structural: an append
    puts the whole record on disk in ONE ``write`` syscall, and a regular-file
    write is not interruptible by a signal — the kernel completes it in full
    or the process dies before it starts. So a process crash always leaves
    the log on a record boundary.

    That does NOT retire the torn-tail handling. A power cut can still leave
    a partial record (the fsync never completed), and so can a short write —
    which is how the test above produces one. It does mean the torn tail is a
    durability condition rather than a crash condition, and this test is what
    will notice if that ever stops being true.
    """
    log = _mint(tmp_path)
    for attempt in range(8):
        worker = _run(_SIGKILL_WORKER, str(log.path), tmp_path=tmp_path,
                      name=f"sigkill{attempt}")
        assert worker.stdout.readline().strip() == "READY"
        time.sleep(0.005 + 0.004 * attempt)
        worker.send_signal(signal.SIGKILL)
        worker.wait(timeout=60)
        raw = log.path.read_bytes()
        assert raw.endswith(b"\n"), (
            "a SIGKILL tore an append — the single-write assumption above no "
            "longer holds, and the torn-tail path is now reachable from a crash"
        )
    # Whatever the kills did land, the log is still a valid arrival log.
    assert list(log.walk())


def test_a_torn_tail_is_truncated_by_the_next_append_before_it_writes(tmp_path):
    """Truncation is the appender's first act under the lock, so an ordinary
    append recovers a torn log without a separate ceremony."""
    log = _mint(tmp_path)
    log.append("note", {}, observer="kyle")
    with log.path.open("ab") as fh:
        fh.write(b'{"v":1,"lin":"partial')
    log.append("note", {"after": True}, observer="kyle")
    _verify_by_hand(log, 3)


# ---------------------------------------------------------------------------
# 3. Corrupt interior refuses
# ---------------------------------------------------------------------------


def _seeded(tmp_path, n: int = 4) -> ArrivalLog:
    log = _mint(tmp_path)
    for i in range(n):
        log.append("note", {"i": i}, observer="kyle")
    return log


def _rewrite(log: ArrivalLog, ordinal: int, mutate) -> None:
    lines = log.path.read_bytes()[:-1].split(b"\n")
    lines[ordinal] = mutate(lines[ordinal])
    log.path.write_bytes(b"\n".join(lines) + b"\n")


def test_gate_corrupt_interior_body_refuses_naming_the_ordinal(tmp_path):
    log = _seeded(tmp_path)
    _rewrite(log, 2, lambda line: line.replace(b'{"i":1}', b'{"i":9}'))

    before = log.path.read_bytes()
    with pytest.raises(ArrivalCorrupt) as caught:
        list(log.walk())
    assert caught.value.ordinal == 2
    assert "ordinal 2" in str(caught.value)
    assert log.path.read_bytes() == before, "corruption must never truncate"


def test_gate_corrupt_interior_broken_prev_refuses_naming_the_ordinal(tmp_path):
    log = _seeded(tmp_path)

    def rechain(line: bytes) -> bytes:
        record = json.loads(line)
        record["prev"] = "d" * 64
        record["rh"] = record_hash(record)  # rh recomputes; only the link is wrong
        return encode_record(record).encode()

    _rewrite(log, 3, rechain)
    before = log.path.read_bytes()
    with pytest.raises(ArrivalCorrupt) as caught:
        list(log.walk())
    assert caught.value.ordinal == 3
    assert "prev names" in str(caught.value)
    assert log.path.read_bytes() == before


def test_gate_corrupt_interior_duplicate_ordinal_refuses(tmp_path):
    log = _seeded(tmp_path)

    def duplicate(line: bytes) -> bytes:
        record = json.loads(line)
        record["ord"] = 2  # the record before it already claims 2
        record["rh"] = record_hash(record)
        return encode_record(record).encode()

    _rewrite(log, 3, duplicate)
    before = log.path.read_bytes()
    with pytest.raises(ArrivalCorrupt) as caught:
        list(log.walk())
    assert caught.value.ordinal == 3
    assert "ordinal succession broken" in str(caught.value)
    assert log.path.read_bytes() == before


def test_gate_a_gap_in_the_ordinals_refuses(tmp_path):
    """A gap is corruption for the same reason a repeat is: neither is a
    state an appender can produce."""
    log = _seeded(tmp_path)
    raw = log.path.read_bytes()[:-1].split(b"\n")
    del raw[2]
    log.path.write_bytes(b"\n".join(raw) + b"\n")
    with pytest.raises(ArrivalCorrupt) as caught:
        list(log.walk())
    assert caught.value.ordinal == 2


def test_gate_a_foreign_lineage_in_the_interior_refuses(tmp_path):
    log = _seeded(tmp_path)

    def relineage(line: bytes) -> bytes:
        record = json.loads(line)
        record["lin"] = "SOMEONE-ELSES-LINEAGE"
        record["rh"] = record_hash(record)
        return encode_record(record).encode()

    _rewrite(log, 2, relineage)
    with pytest.raises(ArrivalCorrupt, match="lineage"):
        list(log.walk())


# ---------------------------------------------------------------------------
# 3b. Placement — the genesis kind belongs at ordinal 0 and nowhere else
#
# Review round 1, findings F1 and F2. Both were asymmetries rather than
# missing ideas: the genesis rules existed but only on the `genesis()` path,
# and the "a lineage is opened once" rule existed only in `mint`'s O_EXCL. A
# forged file walked clean, and a second genesis could be appended into the
# interior of a real one. The rule now lives in one validator that every
# path calls.
# ---------------------------------------------------------------------------


def _forge(path, records: list[dict]) -> ArrivalLog:
    """Write a log byte by byte, bypassing every append-side check.

    Forging is the point: these tests are about what a reader does with a
    file the writer never produced.
    """
    path.write_bytes(b"".join(encode_record(r).encode() + b"\n" for r in records))
    return ArrivalLog(path)


def _genesis_record(lin: str = "FORGED-LINEAGE", *, sig: str | None = "sig:x", **over) -> dict:
    fields = {
        "lin": lin, "ordinal": 0, "prev": None, "k": "genesis",
        "body": {"protocol": 1, "lineage": lin}, "observer": "kyle",
        "origin": "", "at": 1.0, "sig": sig,
    }
    fields.update(over)
    return build_record(**fields)


def test_walk_refuses_an_unsigned_genesis(tmp_path):
    """F1. A signature is what makes genesis the lineage's attestation root;
    a walk that trusted position 0 without judging it read a forged one
    clean."""
    log = _forge(tmp_path / "forged.arrival", [_genesis_record(sig=None)])
    with pytest.raises(ArrivalCorrupt) as caught:
        list(log.walk())
    assert caught.value.ordinal == 0
    assert "no signature" in str(caught.value)


def test_walk_refuses_a_genesis_that_is_not_self_naming(tmp_path):
    """F1. The lineage a genesis opens is the one its own coordinate carries;
    a body claiming a different one is a hijack attempt, not a typo."""
    log = _forge(
        tmp_path / "forged.arrival",
        [_genesis_record("MINE", body={"protocol": 1, "lineage": "THEIRS"})],
    )
    with pytest.raises(ArrivalCorrupt) as caught:
        list(log.walk())
    assert caught.value.ordinal == 0
    assert "not self-naming" in str(caught.value)


def test_read_and_head_inherit_the_genesis_rules(tmp_path):
    """Both reach their answer through the walk, so neither needs its own
    copy of the rule — but both must actually refuse."""
    log = _forge(tmp_path / "forged.arrival", [_genesis_record(sig=None)])
    with pytest.raises(ArrivalCorrupt, match="no signature"):
        log.read(0)
    with pytest.raises(ArrivalCorrupt, match="no signature"):
        log.head()


def test_append_refuses_the_genesis_kind_at_an_interior_ordinal(tmp_path):
    """F2. A lineage is opened once. `mint`'s O_EXCL says so for the file;
    this says so for the records inside it."""
    log = _mint(tmp_path)
    before = log.path.read_bytes()
    with pytest.raises(AppendRejected, match="belongs at ordinal 0"):
        log.append("genesis", {"protocol": 1, "lineage": log.lineage()},
                   observer="kyle", signer=_sign)
    assert log.path.read_bytes() == before, "a rejected append must write nothing"


def test_append_record_refuses_the_genesis_kind_at_an_interior_ordinal(tmp_path):
    """F2. Both append paths funnel through one check, so neither is a way
    around the other."""
    log = _mint(tmp_path)
    head = log.head()
    candidate = build_record(
        lin=head["lin"], ordinal=1, prev=head["rh"], k="genesis",
        body={"protocol": 1, "lineage": head["lin"]}, observer="kyle", sig="sig:x",
    )
    with pytest.raises(AppendRejected, match="belongs at ordinal 0"):
        log.append_record(candidate)


def test_walk_refuses_a_hand_written_interior_genesis(tmp_path):
    """F2, the other direction: the append check catches a caller, this
    catches a file someone wrote around the append path entirely."""
    log = _seeded(tmp_path)

    def to_genesis(line: bytes) -> bytes:
        record = json.loads(line)
        record["k"] = "genesis"
        record["rh"] = record_hash(record)
        return encode_record(record).encode()

    _rewrite(log, 2, to_genesis)
    with pytest.raises(ArrivalCorrupt) as caught:
        list(log.walk())
    assert caught.value.ordinal == 2
    assert "belongs at ordinal 0" in str(caught.value)


def test_the_resume_path_also_refuses_an_interior_genesis(tmp_path):
    """F2. The tail walk enforces the same placement rule as the full walk —
    otherwise resuming past the forgery is a way around it."""
    log = _seeded(tmp_path)

    def to_genesis(line: bytes) -> bytes:
        record = json.loads(line)
        record["k"] = "genesis"
        record["rh"] = record_hash(record)
        return encode_record(record).encode()

    # Re-chain ordinals 2..4 so ONLY the kind is wrong — the forgery must not
    # be caught by the prev check standing in for the placement check.
    _rechain_from(log, 2, {2: to_genesis})
    mark = _mark_after(log, 1)
    _ordinal, records = log.walk_from(mark)
    with pytest.raises(ArrivalCorrupt) as caught:
        list(records)
    assert caught.value.ordinal == 2
    assert "belongs at ordinal 0" in str(caught.value)


def _rechain_from(log: ArrivalLog, start: int, mutations: dict) -> None:
    """Rewrite ordinals ``start``.. with ``mutations`` applied, re-linking
    ``prev`` and ``rh`` so the chain stays internally consistent.

    Without this a forged record is caught by the broken ``prev`` it leaves
    behind, and the test would pass whether or not the check it names
    exists.
    """
    lines = log.path.read_bytes()[:-1].split(b"\n")
    prev = json.loads(lines[start - 1])["rh"]
    for ordinal in range(start, len(lines)):
        raw = lines[ordinal]
        if ordinal in mutations:
            raw = mutations[ordinal](raw)
        record = json.loads(raw)
        record["prev"] = prev
        record["rh"] = record_hash(record)
        lines[ordinal] = encode_record(record).encode()
        prev = record["rh"]
    log.path.write_bytes(b"\n".join(lines) + b"\n")


# ---------------------------------------------------------------------------
# 4. Genesis race
# ---------------------------------------------------------------------------

_GENESIS_WORKER = """
    import hashlib, sys
    from engine.arrival import ArrivalLog, GenesisRefused

    def sign(observer, commitment):
        return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()

    try:
        ArrivalLog.mint(sys.argv[1], observer="kyle", signer=sign)
    except GenesisRefused as exc:
        print("REFUSED", exc)
        sys.exit(3)
    print("MINTED")
    """


def test_gate_two_processes_racing_genesis_produce_exactly_one_log(tmp_path):
    path = tmp_path / "raced.arrival"
    racers = [
        _run(_GENESIS_WORKER, str(path), tmp_path=tmp_path, name=f"genesis{n}")
        for n in range(2)
    ]
    results = [racer.communicate(timeout=60) for racer in racers]
    codes = [racer.returncode for racer in racers]

    assert sorted(codes) == [0, 3], f"expected one win and one refusal, got {codes}: {results}"
    assert path.exists()
    assert not (tmp_path / "raced.arrival.tmp").exists(), "staging survived the race"
    # One genesis, and it reads as one.
    log = ArrivalLog(path)
    assert [r["ord"] for r in log.walk()] == [0]
    assert log.genesis()["lin"] == log.lineage()


def test_a_failed_mint_leaves_no_staging_behind(tmp_path):
    with pytest.raises(GenesisRefused):
        ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=lambda o, c: None)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# 5. Resume mark validation
# ---------------------------------------------------------------------------


def _mark_after(log: ArrivalLog, ordinal: int) -> ResumeMark:
    """A valid mark just past the record at ``ordinal``."""
    raw = log.path.read_bytes()
    offset = 0
    for _ in range(ordinal + 1):
        offset = raw.index(b"\n", offset) + 1
    return ResumeMark(log.lineage(), offset, ordinal)


def test_a_valid_resume_mark_resumes_where_it_says(tmp_path):
    log = _seeded(tmp_path)
    mark = _mark_after(log, 2)
    ordinal, records = log.walk_from(mark)
    assert ordinal == 3
    assert [r["ord"] for r in records] == [3, 4]


def test_a_mark_at_the_head_resumes_with_nothing_left(tmp_path):
    log = _seeded(tmp_path)
    ordinal, records = log.walk_from(_mark_after(log, 4))
    assert (ordinal, list(records)) == (5, [])


@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda m, log: ResumeMark("A-DIFFERENT-LINEAGE", m.arrival_offset, m.arrival_ordinal),
         "a mark about a different file"),
        (lambda m, log: ResumeMark(m.arrival_lineage, m.arrival_offset - 5, m.arrival_ordinal),
         "an offset mid-record"),
        (lambda m, log: ResumeMark(
            m.arrival_lineage, log.path.stat().st_size + 1, m.arrival_ordinal),
         "an offset past EOF"),
        (lambda m, log: ResumeMark(m.arrival_lineage, -1, m.arrival_ordinal),
         "a negative offset — metadata that cannot be true"),
        (lambda m, log: ResumeMark(m.arrival_lineage, m.arrival_offset, m.arrival_ordinal + 1),
         "an ordinal disagreeing with the record at the offset"),
    ],
)
def test_gate_an_invalid_resume_mark_is_rejected_and_the_reader_restarts(
    tmp_path, mutate, why
):
    """Rejection is silent and costs a re-read, never data — which is why a
    mark may be discarded where a corrupt record may not."""
    log = _seeded(tmp_path)
    bad = mutate(_mark_after(log, 2), log)
    assert log.resume_offset(bad) == 0, why
    ordinal, records = log.walk_from(bad)
    assert ordinal == 0
    assert [r["ord"] for r in records] == [0, 1, 2, 3, 4]


def test_gate_an_anchor_carrying_a_foreign_lineage_is_rejected(tmp_path):
    """F4, the sharpest of round 1.

    The mark's own lineage was checked against the genesis, but the RECORD
    the mark points at was not — and the tail walk then took its lineage
    expectation from that record. So a crafted interior record carrying a
    foreign lineage, with a recomputing ``rh`` so it decodes clean, became
    the authority for verifying everything after it: the attacker's lineage
    substituted for the log's, silently, on the resume path only.

    Here ordinals 2..4 are re-chained onto a foreign lineage, which is what
    a spliced tail actually looks like. The mark is honest about the log's
    lineage and honest about the ordinal — only the anchor is foreign.
    """
    log = _seeded(tmp_path)
    real = log.lineage()
    foreign = "SOMEONE-ELSES-LINEAGE"

    def relineage(line: bytes) -> bytes:
        record = json.loads(line)
        record["lin"] = foreign
        return encode_record(dict(record, rh=record_hash(record))).encode()

    _rechain_from(log, 2, dict.fromkeys((2, 3, 4), relineage))
    mark = _mark_after(log, 2)
    assert mark.arrival_lineage == real  # the mark itself is not the forgery
    assert json.loads(log.path.read_bytes().split(b"\n")[2])["lin"] == foreign

    # The mark is discarded and the reader restarts from 0 ...
    assert log.resume_offset(mark) == 0
    ordinal, records = log.walk_from(mark)
    assert ordinal == 0
    # ... where the honest walk surfaces the splice instead of resuming past it.
    with pytest.raises(ArrivalCorrupt) as caught:
        list(records)
    assert caught.value.ordinal == 2
    assert foreign in str(caught.value)


# ---------------------------------------------------------------------------
# 5b. Adopting a record as an AUTHORITY
#
# Review round 2. Round 1 fixed "the anchor's LINEAGE is trusted without
# checking"; round 2 found the same residual shape twice more — the anchor's
# PLACEMENT and the head's placement, both trusted without checking. The
# defect was never that the walk is broken: the consumed walk refuses all of
# these files correctly. It is that the eager O(1) paths, which adopt an
# existing on-disk record as a premise and derive from it, skipped the
# validation the read path performs on the way past. These tests build the
# hostile file and drive the real entry point, rather than unit-testing the
# validator.
# ---------------------------------------------------------------------------


def test_a_mark_anchored_on_an_interior_genesis_is_discarded(tmp_path):
    """F1-R2. A record the walk refuses must not be a legal place to resume
    from, or the resume path consumes straight past the corruption."""
    log = _seeded(tmp_path)

    def to_genesis(line: bytes) -> bytes:
        record = json.loads(line)
        record["k"] = "genesis"
        record["rh"] = record_hash(record)
        return encode_record(record).encode()

    _rechain_from(log, 1, {1: to_genesis})
    mark = _mark_after(log, 1)  # anchored ON the forged record

    # The consumed walk refuses it — the read path was never the defect.
    with pytest.raises(ArrivalCorrupt) as walked:
        list(log.walk())
    assert walked.value.ordinal == 1

    # And the resume path no longer offers a way around that refusal.
    assert log.resume_offset(mark) == 0
    ordinal, records = log.walk_from(mark)
    assert ordinal == 0
    with pytest.raises(ArrivalCorrupt) as caught:
        list(records)
    assert caught.value.ordinal == 1
    assert "belongs at ordinal 0" in str(caught.value)


def test_append_refuses_a_log_whose_genesis_is_unsigned(tmp_path):
    """F2-R2. A tampered log that keeps accepting appends is worse than a
    refused write: honest-looking records piling onto a forged genesis is
    what makes the forgery hard to see later."""
    log = _forge(tmp_path / "forged.arrival", [_genesis_record("FORGED", sig=None)])
    before = log.path.read_bytes()
    with pytest.raises(GenesisRefused, match="no signature"):
        log.append("note", {"i": 0}, observer="kyle")
    assert log.path.read_bytes() == before, "a refused append must write nothing"


def test_append_refuses_a_log_whose_genesis_is_not_self_naming(tmp_path):
    """F2-R2, same adoption site: the head is validated against a genesis
    that must itself be valid."""
    log = _forge(
        tmp_path / "forged.arrival",
        [_genesis_record("MINE", body={"protocol": 1, "lineage": "THEIRS"})],
    )
    before = log.path.read_bytes()
    with pytest.raises(GenesisRefused, match="not self-naming"):
        log.append("note", {"i": 0}, observer="kyle")
    assert log.path.read_bytes() == before


def test_append_refuses_a_tail_re_chained_onto_a_foreign_lineage(tmp_path):
    """The append-side sibling of round 1's F4, found by the general form
    rather than by review.

    The candidate copies its lineage FROM the head, and `_check_follows`
    compares the candidate to the head — so a head that had been re-chained
    onto a foreign lineage was never compared to the genesis, and the log
    would happily keep growing under the attacker's lineage.
    """
    log = _seeded(tmp_path)
    foreign = "SOMEONE-ELSES-LINEAGE"

    def relineage(line: bytes) -> bytes:
        record = json.loads(line)
        record["lin"] = foreign
        return encode_record(dict(record, rh=record_hash(record))).encode()

    _rechain_from(log, 3, dict.fromkeys((3, 4), relineage))
    before = log.path.read_bytes()
    with pytest.raises(ArrivalCorrupt) as caught:
        log.append("note", {"i": 99}, observer="kyle")
    assert foreign in str(caught.value)
    assert log.path.read_bytes() == before, "a refused append must write nothing"


def test_append_refuses_a_tail_that_claims_to_be_a_genesis(tmp_path):
    """The head is held to the same placement rule as everything else."""
    log = _seeded(tmp_path)

    def to_genesis(line: bytes) -> bytes:
        record = json.loads(line)
        record["k"] = "genesis"
        return encode_record(dict(record, rh=record_hash(record))).encode()

    _rechain_from(log, 4, {4: to_genesis})
    before = log.path.read_bytes()
    with pytest.raises(ArrivalCorrupt, match="belongs at ordinal 0"):
        log.append("note", {"i": 99}, observer="kyle")
    assert log.path.read_bytes() == before


def test_walk_is_a_generator_and_validates_nothing_until_consumed(tmp_path):
    """Pinned because "I called walk and it did not raise" is a natural and
    wrong way to read this code — it is why one round-2 probe first looked
    like a walk defect when the walk was correct."""
    log = _forge(tmp_path / "forged.arrival", [_genesis_record(sig=None)])
    log.walk()  # no exception: nothing has been pulled yet
    with pytest.raises(ArrivalCorrupt):
        list(log.walk())


def test_no_mark_at_all_starts_from_ordinal_zero(tmp_path):
    log = _seeded(tmp_path)
    ordinal, records = log.walk_from(None)
    assert (ordinal, [r["ord"] for r in records]) == (0, [0, 1, 2, 3, 4])


def test_the_resume_mark_is_checkable_against_the_log_alone(tmp_path):
    """No projection is consulted — the property that lets a later slice
    rebuild projections from nothing."""
    log = _seeded(tmp_path)
    mark = _mark_after(log, 3)
    assert log.resume_offset(mark) == mark.arrival_offset
    assert sorted(p.name for p in tmp_path.iterdir()) == ["alcove.arrival", "alcove.arrival.lock"]


# ---------------------------------------------------------------------------
# 6. Reader during live appends
# ---------------------------------------------------------------------------


def test_gate_a_reader_never_sees_a_partial_record_and_never_truncates(tmp_path):
    """Reads take no lock, so the reader must treat an unterminated tail as
    possibly in flight rather than torn.

    What this test can and cannot show, stated rather than assumed. Because
    an append reaches disk in one write syscall (see
    :func:`test_a_real_sigkill_cannot_tear_an_append`), a concurrent reader
    on this platform never actually observes a partial record — so the
    "never sees a partial record" half is confirmed here rather than
    stressed. What this test does exercise for real is that an unlocked
    reader running against live writers always sees a dense, intact prefix
    and never shortens the file.

    The other half — that a reader handed an unterminated tail leaves it
    alone instead of consuming or cutting it — is deterministic and lives in
    :func:`test_the_read_path_leaves_a_torn_tail_alone`, which plants the
    partial bytes rather than hoping to catch them.
    """
    log = _mint(tmp_path)
    writers = [
        _run(_APPEND_WORKER, str(log.path), "120", f"w{n}",
             tmp_path=tmp_path, name=f"live{n}")
        for n in range(2)
    ]

    observations = []
    failures: list[BaseException] = []
    stop = threading.Event()

    def read_loop() -> None:
        try:
            while not stop.is_set():
                size = log.path.stat().st_size
                walked = [r["ord"] for r in log.walk()]
                # Dense from 0, every time, however far the writers have got.
                assert walked == list(range(len(walked))), walked
                # The reader must not have shortened the file.
                assert log.path.stat().st_size >= size
                observations.append(len(walked))
        except BaseException as exc:  # surfaced on the main thread below
            failures.append(exc)

    reader = threading.Thread(target=read_loop)
    reader.start()
    for n, writer in enumerate(writers):
        out, err = writer.communicate(timeout=300)
        assert writer.returncode == 0, f"writer {n} failed:\n{out}\n{err}"
    stop.set()
    reader.join(timeout=60)

    assert not failures, failures[0]
    assert len(observations) > 1, "the reader never got a look at a live log"
    assert observations != sorted(observations, reverse=True)  # it saw growth
    _verify_by_hand(log, 2 * 120 + 1)


def test_the_read_path_leaves_a_torn_tail_alone(tmp_path):
    """The asymmetry stated once: only the writer, holding the lock, may
    conclude a tail is torn."""
    log = _seeded(tmp_path, 2)
    with log.path.open("ab") as fh:
        fh.write(b'{"v":1,"lin":"in-flight')
    before = log.path.read_bytes()

    assert [r["ord"] for r in log.walk()] == [0, 1, 2]
    assert log.head()["ord"] == 2
    assert log.path.read_bytes() == before, "the read path truncated a tail"


def test_the_lock_lives_beside_the_log_and_survives_a_crashed_holder(tmp_path):
    """flock is released when the holding process dies — a crashed writer
    must not wedge the store."""
    log = _seeded(tmp_path, 1)
    holder = _run(
        """
        import fcntl, sys, time
        fh = open(sys.argv[1], "ab")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        print("HELD", flush=True)
        time.sleep(300)
        """,
        str(log.lock_path), tmp_path=tmp_path, name="holder",
    )
    assert holder.stdout.readline().strip() == "HELD"
    os.kill(holder.pid, signal.SIGKILL)
    holder.wait(timeout=30)

    log.append("note", {"after": "the crash"}, observer="kyle")
    assert log.head()["ord"] == 2
