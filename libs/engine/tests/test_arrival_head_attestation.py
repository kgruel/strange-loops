"""The witness minimum — the record, the journal, and the comparison.

Slice 3 / WP1 (``design:arrival-break-slice3-witness-minimum`` §§A-C).

Every test here runs against a temporary state root. The module resolves its
home from ``$XDG_STATE_HOME`` at call time and the fixture below redirects it
for the whole module, so no test can reach the developer's real journals — a
suite that wrote head observations into ``~/.local/state/loops`` would be
corrupting the very memory the design exists to protect.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.arrival_contract import ContractRefusal, Head
from engine.arrival_head_attestation import (
    AbsentStoreOutcome,
    AttestationRefusal,
    HeadAttestation,
    HeadFork,
    HeadLowerBound,
    HeadRewrite,
    HeadRollback,
    IndeterminateComparison,
    JournalEquivocation,
    JournalUnreadable,
    Kind,
    Level,
    LineageReplaced,
    Outcome,
    StoreLost,
    UnsafeLineageName,
    append_entry,
    bindings_path,
    bound_lineage,
    compare,
    compare_absent_store,
    heads_dir,
    journal_path,
    parse_journal_lines,
    read_journal,
    record_binding,
    refusal_for,
    state_root,
    unaccounted_heads,
)

HEADER = json.dumps(
    {"v": 1, "type": "arrival-head-observation", "protocol": 1, "wire": 1}
)
LINEAGE = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
OTHER_LINEAGE = "01BX5ZZKBKACTAV9WEVGEMMVRZ"


@pytest.fixture(autouse=True)
def _isolated_state_root(tmp_path, monkeypatch):
    """Point the state root at a temporary directory, for every test here.

    Autouse rather than per-test: one forgotten opt-in is one test writing to
    the real ``~/.local/state/loops``, and that failure would be invisible
    until it had already happened.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


def head(ordinal: int, digest: str = "a", lineage: str = LINEAGE) -> Head:
    """A head whose hash is a recognizable 64-hex string."""
    return Head(lineage=lineage, ordinal=ordinal, record_hash=digest * 64)


def observation(
    ordinal: int,
    digest: str = "a",
    *,
    kind: Kind = Kind.ADVANCE,
    level: Level = Level.COMMIT,
    lineage: str = LINEAGE,
    note: str = "",
) -> HeadAttestation:
    return HeadAttestation(
        head=head(ordinal, digest, lineage),
        kind=kind,
        level=level,
        observed_at=1787779020.0,
        note=note,
    )


# ---------------------------------------------------------------------------
# The classifier: every row (§C.1)
# ---------------------------------------------------------------------------


def test_no_memory_is_first_contact():
    """Nothing remembered, so nothing was proven — and the label is permanent."""
    assert compare(None, head(7), None) is Outcome.FIRST_CONTACT


def test_identical_head_is_unchanged():
    known = observation(7)
    assert compare(known, head(7), None) is Outcome.UNCHANGED


def test_unchanged_never_consults_the_evidence():
    """The dominant case must not pay for evidence it cannot use.

    ``at_known`` deliberately contradicts the remembered head here. If the
    unchanged arm consulted it, this would classify a rewrite.
    """
    known = observation(7)
    assert compare(known, head(7), head(7, "f")) is Outcome.UNCHANGED


def test_higher_ordinal_with_matching_record_at_the_known_ordinal_advances():
    known = observation(7)
    assert compare(known, head(9), known.head) is Outcome.ADVANCED


def test_lower_ordinal_is_rollback():
    """A store may not present a head below the one this machine accepted."""
    known = observation(9)
    assert compare(known, head(7), None) is Outcome.ROLLBACK


def test_same_ordinal_with_a_different_record_is_a_fork():
    known = observation(7, "a")
    assert compare(known, head(7, "b"), None) is Outcome.SAME_HEIGHT_FORK


def test_higher_ordinal_with_a_different_record_at_the_known_ordinal_is_rewrite():
    """Height is not evidence of continuity — this is that failure, caught."""
    known = observation(7, "a")
    assert compare(known, head(9), head(7, "b")) is Outcome.REWRITE


def test_higher_ordinal_with_no_vouched_record_at_the_known_ordinal_is_rewrite():
    """A walk that answers nothing about *K* has not established descent."""
    known = observation(7)
    assert compare(known, head(9), None) is Outcome.REWRITE


def test_a_different_lineage_is_replacement():
    known = observation(7)
    presented = head(9, "a", lineage=OTHER_LINEAGE)
    assert compare(known, presented, None) is Outcome.LINEAGE_REPLACED


def test_lineage_is_judged_before_any_ordinal_arithmetic():
    """Heights across two lineages are two unrelated number lines.

    A lower ordinal in a foreign lineage is replacement, not rollback: if the
    guard order were reversed this would answer ``rollback`` and an operator
    would go looking for a backup of a lineage that was never involved.
    """
    known = observation(9)
    presented = head(2, "a", lineage=OTHER_LINEAGE)
    assert compare(known, presented, None) is Outcome.LINEAGE_REPLACED


def test_every_outcome_has_a_stable_string_the_vectors_can_pin():
    """The values are the contract; WP2's vectors pin these, not the type."""
    assert {outcome.value for outcome in Outcome} == {
        "first-contact",
        "unchanged",
        "advanced",
        "rollback",
        "same-height-fork",
        "rewrite",
        "lineage-replaced",
    }


# ---------------------------------------------------------------------------
# The refusal family (§C.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "refusal"),
    [
        (Outcome.ROLLBACK, HeadRollback),
        (Outcome.SAME_HEIGHT_FORK, HeadFork),
        (Outcome.REWRITE, HeadRewrite),
        (Outcome.LINEAGE_REPLACED, LineageReplaced),
        (AbsentStoreOutcome.STORE_LOST, StoreLost),
    ],
)
def test_each_refusing_outcome_names_its_refusal(outcome, refusal):
    assert refusal_for(outcome) is refusal


@pytest.mark.parametrize(
    "outcome",
    [
        Outcome.FIRST_CONTACT,
        Outcome.UNCHANGED,
        Outcome.ADVANCED,
        AbsentStoreOutcome.PRE_GENESIS,
    ],
)
def test_proceeding_outcomes_name_no_refusal(outcome):
    assert refusal_for(outcome) is None


def test_the_refusal_root_is_outside_the_contract_root():
    """Arbiter ruling 1, held as a test rather than as review vigilance.

    Rollback, fork, rewrite and replacement are witness-protocol conditions;
    ``backend-contract.html`` names none of them. Joining ``ContractRefusal``
    would assert that every conforming backend owes these refusals, and only a
    contract-text line can make that claim.
    """
    assert not issubclass(AttestationRefusal, ContractRefusal)
    for refusal in (
        HeadRollback,
        HeadFork,
        HeadRewrite,
        LineageReplaced,
        StoreLost,
        JournalEquivocation,
        JournalUnreadable,
        UnsafeLineageName,
    ):
        assert issubclass(refusal, AttestationRefusal)
        assert not issubclass(refusal, ContractRefusal)


def test_the_fork_refusal_is_not_the_contract_s_same_height_fork():
    """Same ratified state name, different operation, different type."""
    from engine.arrival_contract import SameHeightFork

    assert HeadFork is not SameHeightFork
    assert not issubclass(HeadFork, SameHeightFork)
    assert Outcome.SAME_HEIGHT_FORK.value == "same-height-fork"


# ---------------------------------------------------------------------------
# Where the journal lives (§A.3)
# ---------------------------------------------------------------------------


def test_the_state_root_honors_the_environment(_isolated_state_root):
    assert state_root() == _isolated_state_root / "loops"
    assert heads_dir() == _isolated_state_root / "loops" / "heads"


def test_the_state_root_falls_back_to_local_state(monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/tester")))
    assert state_root() == Path("/home/tester/.local/state/loops")


def test_the_state_root_is_not_the_config_root(monkeypatch, _isolated_state_root):
    """The live config-level stores are IN the config root.

    A memory kept there would share a restore boundary with the stores it
    witnesses, which is the failure the home was chosen to close.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(_isolated_state_root / "config"))
    assert (_isolated_state_root / "config") not in state_root().parents


def test_a_lineage_with_a_slash_refuses_to_resolve_a_path():
    """The refusal is a location claim, not a verdict about the store."""
    with pytest.raises(UnsafeLineageName) as caught:
        journal_path("../../etc/passwd")
    assert "../../etc/passwd" in str(caught.value)


@pytest.mark.parametrize(
    "lineage",
    [
        "",
        ".",
        "..",
        ".hidden",
        "a/b",
        "a\\b",
        "a\x00b",
        "with space",
        "x" * 200,
        "bindings",
        "BINDINGS",
    ],
)
def test_unsafe_lineage_names_refuse(lineage):
    """``bindings`` included: the transitional file already owns that name.

    Case-folded, because the filesystems this runs on are commonly
    case-insensitive and ``BINDINGS`` would collide just as hard.
    """
    with pytest.raises(UnsafeLineageName):
        journal_path(lineage)


def test_a_ulid_lineage_resolves():
    assert journal_path(LINEAGE) == heads_dir() / f"{LINEAGE}.jsonl"


def test_the_journal_is_keyed_by_lineage_not_by_location():
    """The same lineage seen at two locations finds one memory.

    Path-keying would manufacture a fresh first contact per worktree and per
    copy — silent re-acceptance on the most ordinary operation there is.
    """
    append_entry(
        HeadAttestation(
            head=head(4),
            kind=Kind.BOOTSTRAP,
            level=Level.MINT,
            observed_at=1.0,
            location="/a/project.arrival",
        )
    )
    append_entry(
        HeadAttestation(
            head=head(5),
            kind=Kind.ADVANCE,
            level=Level.COMMIT,
            observed_at=2.0,
            location="/somewhere/else/project.arrival",
        )
    )
    result = read_journal(LINEAGE)
    assert len(result.entries) == 2
    assert result.established_head() is not None
    assert result.established_head().head == head(5)


# ---------------------------------------------------------------------------
# Serialization (§B.3)
# ---------------------------------------------------------------------------


def test_a_new_journal_opens_with_a_header_naming_what_it_is():
    append_entry(observation(0, kind=Kind.BOOTSTRAP, level=Level.MINT))
    lines = journal_path(LINEAGE).read_text().splitlines()
    assert json.loads(lines[0]) == {
        "v": 1,
        "type": "arrival-head-observation",
        "protocol": 1,
        "wire": 1,
    }


def test_the_serialized_type_is_never_bare_attestation():
    """That vocabulary already means signed row receipts in this codebase."""
    append_entry(observation(0))
    header = json.loads(journal_path(LINEAGE).read_text().splitlines()[0])
    assert header["type"] == "arrival-head-observation"


def test_an_entry_carries_the_head_kind_level_and_time_and_nothing_signed():
    append_entry(
        HeadAttestation(
            head=head(3, "c"),
            kind=Kind.ADVANCE,
            level=Level.DESCENDANT,
            observed_at=1787779020.0,
            location="/tmp/project.arrival",
        )
    )
    entry = json.loads(journal_path(LINEAGE).read_text().splitlines()[1])
    assert entry == {
        "v": 1,
        "kind": "advance",
        "level": "descendant",
        "lineage": LINEAGE,
        "ordinal": 3,
        "record_hash": "c" * 64,
        "observed_at": 1787779020.0,
        "location": "/tmp/project.arrival",
    }
    for absent in ("sig", "issuer", "key_id", "previous", "attestation_id"):
        assert absent not in entry
    for corroboration in ("fact_count", "tick_count", "counts"):
        assert corroboration not in entry


def test_a_create_race_does_not_overwrite_the_other_writers_entry():
    """The creating writer must not land its bytes at offset zero.

    Two writers reach an absent journal. A wins the exclusive create; B loses
    it, opens for append, and lands a complete entry in the still-empty file.
    If A's descriptor sat at offset zero it would write its header and entry
    over B's — and the journal would have silently forgotten a head. A later
    restore to A's ordinal would then classify unchanged, which is the failure
    the maximum-ordinal rule exists to close, arriving through the write path.

    The interleave is forced by letting B complete a whole append inside A's
    write call, while A still holds the descriptor it created.
    """
    real_write = os.write
    racing = []

    def write_after_the_other_writer_lands(handle, payload):
        if not racing:
            racing.append(True)
            append_entry(observation(9))  # B, start to finish
        return real_write(handle, payload)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "write", write_after_the_other_writer_lands)
        append_entry(observation(4, kind=Kind.BOOTSTRAP, level=Level.MINT))

    result = read_journal(LINEAGE)
    assert sorted(entry.head.ordinal for entry in result.entries) == [4, 9]
    assert result.established_head() is not None
    assert result.established_head().head.ordinal == 9


def test_a_torn_tail_does_not_glue_itself_to_the_next_entry():
    """A crash costs the newest observation, and must not cost the next one.

    Appending straight onto a fragment with no trailing newline would
    concatenate the next entry into it — one unreadable line, with the new
    entry's bytes lost inside. The guard keeps the fragment its own line.

    Without the guard the fragment and the ordinal-5 entry would be one line,
    so BOTH observations would be lost rather than just the torn one. This is
    a bytes-level assertion: it is what the guard actually does, and the read
    policy above is a separate decision layered on top of it.
    """
    append_entry(observation(4))
    with journal_path(LINEAGE).open("a") as handle:
        handle.write('{"v":1,"kind":"adv')  # crash mid-append
    append_entry(observation(5))

    lines = journal_path(LINEAGE).read_text().splitlines()
    assert lines[2] == '{"v":1,"kind":"adv'
    assert json.loads(lines[3])["ordinal"] == 5

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 5


def test_a_short_write_still_lands_the_whole_line():
    """A short write would be a torn line this process inflicted on itself."""
    real_write = os.write

    def one_byte_at_a_time(handle, payload):
        return real_write(handle, payload[:1])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "write", one_byte_at_a_time)
        append_entry(observation(4))

    result = read_journal(LINEAGE)
    assert result.established_head() is not None
    assert result.established_head().head == head(4)


def test_the_header_is_written_once_however_many_entries_land():
    for ordinal in range(4):
        append_entry(observation(ordinal))
    lines = journal_path(LINEAGE).read_text().splitlines()
    headers = [line for line in lines if "type" in json.loads(line)]
    assert len(headers) == 1
    assert len(lines) == 5


# ---------------------------------------------------------------------------
# Read rule 1: the maximum-ordinal entry, not the last line
# ---------------------------------------------------------------------------


def test_the_known_head_is_the_maximum_ordinal_not_the_last_line():
    """Two writers journal out of order; last-line semantics would read K=5.

    The arrival lock serializes their *appends*, not their journal writes: A
    commits 5, B commits 6 and journals it, A journals 5 last. A genuine
    restore back to 5 would then classify unchanged.
    """
    append_entry(observation(6))
    append_entry(observation(5))
    result = read_journal(LINEAGE)
    assert result.entries[-1].head.ordinal == 5
    assert result.established_head() is not None
    assert result.established_head().head.ordinal == 6


def test_out_of_order_journal_writes_still_catch_a_restore():
    """The consequence the read rule exists for, stated end to end."""
    append_entry(observation(6))
    append_entry(observation(5))
    known = read_journal(LINEAGE).established_head()
    assert compare(known, head(5), None) is Outcome.ROLLBACK


def test_duplicate_entries_at_one_ordinal_are_harmless():
    append_entry(observation(6))
    append_entry(observation(6))
    result = read_journal(LINEAGE)
    assert result.established_head() is not None
    assert result.established_head().head == head(6)


# ---------------------------------------------------------------------------
# Read rule 2: journal-internal equivocation
# ---------------------------------------------------------------------------


def test_two_records_at_the_maximum_ordinal_refuse():
    """The journal holds two incompatible histories and may not choose."""
    append_entry(observation(6, "a"))
    append_entry(observation(6, "b"))
    with pytest.raises(JournalEquivocation) as caught:
        read_journal(LINEAGE)
    assert "6" in str(caught.value)


def test_disagreement_below_the_maximum_ordinal_is_not_equivocation():
    """Only the head is a claim; older entries at odds are ordinary history."""
    append_entry(observation(6, "a"))
    append_entry(observation(6, "b"))
    append_entry(observation(7, "c"))
    result = read_journal(LINEAGE)
    assert result.established_head() is not None
    assert result.established_head().head == head(7, "c")


# ---------------------------------------------------------------------------
# Read rule 0: trust-epoch scoping — the deadlock the design's own review caught
# ---------------------------------------------------------------------------


def _journal_with_a_reset() -> None:
    """Ordinals 90-100 accepted, then an operator accepts a restore to 90."""
    for ordinal in range(90, 101):
        append_entry(observation(ordinal))
    append_entry(
        observation(
            90,
            kind=Kind.TRUST_RESET,
            level=Level.FULL,
            note="restored from archive; abandoned head was ordinal 100",
        )
    )


def test_after_a_trust_reset_the_known_head_is_the_reset_head():
    """Unscoped, K would read 100 and every open would refuse forever.

    The abandoned entries at 91-100 still hold the maximum ordinal. Scoping
    the read to the current epoch is what lets the ceremony take effect.
    """
    _journal_with_a_reset()
    result = read_journal(LINEAGE)
    assert result.established_head() is not None
    assert result.established_head().head.ordinal == 90
    assert result.established_head().kind is Kind.TRUST_RESET


def test_after_a_trust_reset_the_restored_store_opens_unchanged():
    """The deadlock, stated as the behavior an operator would see."""
    _journal_with_a_reset()
    known = read_journal(LINEAGE).established_head()
    assert compare(known, head(90), None) is Outcome.UNCHANGED


def test_the_epoch_includes_the_reset_entry_itself():
    """Scoping it out would leave a just-reset journal with an empty epoch.

    K would be None, the next open would classify first contact, and the
    ceremony would have bought silent re-acceptance instead of a refusal —
    the deadlock's mirror image.
    """
    _journal_with_a_reset()
    result = read_journal(LINEAGE)
    assert len(result.epoch) == 1
    assert result.epoch[0].kind is Kind.TRUST_RESET
    assert result.established_head() is not None


def test_pre_reset_entries_are_retained_as_evidence():
    """The gap is recorded, not erased — that is the point of the ceremony."""
    _journal_with_a_reset()
    result = read_journal(LINEAGE)
    assert len(result.entries) == 12
    assert [entry.head.ordinal for entry in result.entries[:11]] == list(
        range(90, 101)
    )
    assert "abandoned head was ordinal 100" in result.entries[-1].note


def test_a_journal_with_no_reset_has_the_whole_history_as_its_epoch():
    for ordinal in range(3):
        append_entry(observation(ordinal))
    result = read_journal(LINEAGE)
    assert result.epoch == result.entries


def test_only_the_latest_reset_opens_the_current_epoch():
    append_entry(observation(5))
    append_entry(observation(3, kind=Kind.TRUST_RESET, level=Level.FULL))
    append_entry(observation(4))
    append_entry(observation(2, kind=Kind.TRUST_RESET, level=Level.FULL))
    result = read_journal(LINEAGE)
    assert [entry.head.ordinal for entry in result.epoch] == [2]
    assert result.established_head() is not None
    assert result.established_head().head.ordinal == 2


def test_equivocation_is_scoped_to_the_current_epoch():
    """Two histories the operator already adjudicated are not a live conflict."""
    append_entry(observation(6, "a"))
    append_entry(observation(6, "b"))
    append_entry(observation(4, kind=Kind.TRUST_RESET, level=Level.FULL))
    result = read_journal(LINEAGE)
    assert result.established_head() is not None
    assert result.established_head().head == head(4)


# ---------------------------------------------------------------------------
# The audit's all-journaled-heads check (§C.4)
# ---------------------------------------------------------------------------


def test_the_audit_check_names_a_head_the_store_no_longer_accounts_for():
    """An advance accepted on partial evidence is re-examined later."""
    epoch = (observation(4, "a"), observation(5, "b"))
    present = {4: head(4, "z"), 5: head(5, "b")}
    unaccounted = unaccounted_heads(epoch, present.get)
    assert [entry.head.ordinal for entry in unaccounted] == [4]


def test_the_audit_check_passes_when_every_journaled_head_is_still_there():
    epoch = (observation(4, "a"), observation(5, "b"))
    present = {4: head(4, "a"), 5: head(5, "b")}
    assert unaccounted_heads(epoch, present.get) == ()


def test_the_audit_check_does_not_fail_on_pre_reset_entries():
    """A restored store cannot contain the abandoned heads, and never will.

    Auditing against them would fail permanently and train an operator to
    ignore the audit — worse than not running one.
    """
    _journal_with_a_reset()
    result = read_journal(LINEAGE)
    restored = {ordinal: head(ordinal) for ordinal in range(90, 91)}
    assert unaccounted_heads(result.epoch, restored.get) == ()
    assert unaccounted_heads(result.entries, restored.get) != ()


# ---------------------------------------------------------------------------
# Torn tails, damage, and forward compatibility
# ---------------------------------------------------------------------------


def test_a_torn_final_line_is_tolerated_and_reported():
    """A crash mid-append costs at most the newest observation.

    Tolerated, but the head it leaves is a bound rather than a head — the
    fragment carries no information about the ordinal it was recording.
    """
    append_entry(observation(4))
    with journal_path(LINEAGE).open("a") as handle:
        handle.write('{"v":1,"kind":"advance","level":"comm')
    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 4
    assert len(result.skipped) == 1
    assert "does not parse" in result.skipped[0]


def test_damage_anywhere_is_tolerated_and_reported():
    """Position carries no meaning, so the read rule does not consult it.

    The earlier design refused damage above the last line, reasoning that
    skipping could silently lower K. It can — but refusing was the wrong
    answer to it, and the loss is carried in the result type instead.
    """
    append_entry(observation(4))
    append_entry(observation(5))
    lines = journal_path(LINEAGE).read_text().splitlines()
    lines[1] = "{not json"
    journal_path(LINEAGE).write_text("\n".join(lines) + "\n")
    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 5
    assert "line 2" in result.skipped[0]


def test_an_incomplete_read_cannot_be_asked_for_a_comparable_head():
    """The cheap unchanged shortcut is unobtainable, not merely discouraged."""
    append_entry(observation(4))
    with journal_path(LINEAGE).open("a") as handle:
        handle.write("{not json\n")
    result = read_journal(LINEAGE)
    with pytest.raises(IndeterminateComparison) as caught:
        result.established_head()
    assert "at or above ordinal 4" in str(caught.value)


def test_an_incomplete_read_cannot_classify_a_restore_as_unchanged():
    """The out-of-order case that refuted the ascending-ordinal invariant.

    Writers journal out of order — the arrival lock serializes their appends,
    not their journal writes — so the epoch maximum can sit above a later
    line. Damage the line holding it, and the surviving maximum is 91 while
    the truth is 92. A store presenting 91 after a genuine restore would
    classify unchanged against a plain K; against a bound it cannot be
    classified at all, which is the honest answer.

    See ``finding:s3wp1-epoch-ordinals-do-not-ascend-in-file-order``.
    """
    append_entry(observation(90, kind=Kind.TRUST_RESET, level=Level.FULL))
    append_entry(observation(92))  # writer B journals first
    append_entry(observation(91))  # writer A journals last

    assert read_journal(LINEAGE).established_head().head.ordinal == 92

    lines = journal_path(LINEAGE).read_text().splitlines()
    lines[2] = "{torn"  # the line holding the epoch maximum
    journal_path(LINEAGE).write_text("\n".join(lines) + "\n")

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 91
    assert 91 in [entry.head.ordinal for entry in result.entries]
    with pytest.raises(IndeterminateComparison):
        result.established_head()


def test_a_bound_still_answers_rollback_soundly():
    """The one comparison a lower bound can make: below the bound is below K."""
    append_entry(observation(90))
    append_entry(observation(91))
    with journal_path(LINEAGE).open("a") as handle:
        handle.write("{torn\n")
    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert compare(result.known.at_least, head(5), None) is Outcome.ROLLBACK


def test_the_deadlock_scenario_opens_cleanly_now():
    """A crash, a commit, and every later open — the escalation, gone.

    Under the refusal this sequence bricked the journal permanently: the
    fragment became mid-file the moment anything followed it. Now the opens
    proceed, reporting the loss.
    """
    append_entry(observation(4))
    with journal_path(LINEAGE).open("a") as handle:
        handle.write('{"v":1,"kind":"adv')  # crash mid-append
    for ordinal in range(5, 9):
        append_entry(observation(ordinal))  # ordinary commits, long after
    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 8
    assert len(result.skipped) == 1


def test_entries_with_no_header_are_structural_damage():
    """The header states how the hashes derive; without it a comparison is
    not a weaker answer, it is a meaningless one."""
    append_entry(observation(4))
    lines = journal_path(LINEAGE).read_text().splitlines()
    journal_path(LINEAGE).write_text("\n".join(lines[1:]) + "\n")
    with pytest.raises(JournalUnreadable) as caught:
        read_journal(LINEAGE)
    assert "no header" in str(caught.value)


def test_an_empty_journal_is_not_headerless_damage():
    """No entries, no claim — nothing for a missing header to invalidate."""
    assert parse_journal_lines([]).established_head() is None


def test_a_creator_that_crashed_before_its_header_does_not_strand_the_journal():
    """An empty existing file gets the header from whoever appends next."""
    journal_path(LINEAGE).parent.mkdir(parents=True, exist_ok=True)
    journal_path(LINEAGE).touch()  # creator won the create, then died
    append_entry(observation(4))
    result = read_journal(LINEAGE)
    assert result.established_head() is not None
    assert result.established_head().head.ordinal == 4


def test_an_entry_from_a_later_build_is_skipped_and_reported_not_refused():
    """A later build's journal must not make this one refuse to compare.

    Degrading to a shorter view of the same history is honest; refusing
    outright would brick every older build against a journal it shares.
    """
    append_entry(observation(4))
    with journal_path(LINEAGE).open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "v": 1,
                    "kind": "checkpoint-from-the-future",
                    "level": "full",
                    "lineage": LINEAGE,
                    "ordinal": 9,
                    "record_hash": "d" * 64,
                    "observed_at": 3.0,
                }
            )
            + "\n"
        )
        handle.write(json.dumps({"v": 99, "kind": "advance"}) + "\n")
    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 4
    assert len(result.skipped) == 2


def test_unknown_fields_are_ignored_on_read():
    """Append-only means they are preserved on disk by construction."""
    result = parse_journal_lines(
        [
            HEADER,
            json.dumps(
                {
                    "v": 1,
                    "kind": "advance",
                    "level": "commit",
                    "lineage": LINEAGE,
                    "ordinal": 4,
                    "record_hash": "a" * 64,
                    "observed_at": 1.0,
                    "a_field_from_2027": {"nested": True},
                }
            ),
        ]
    )
    assert result.established_head() is not None
    assert result.established_head().head == head(4)
    assert result.skipped == ()


def test_a_second_header_from_a_create_race_is_not_damage():
    """Two writers can each win the exclusive create on different filesystems."""
    result = parse_journal_lines(
        [
            json.dumps({"v": 1, "type": "arrival-head-observation"}),
            json.dumps({"v": 1, "type": "arrival-head-observation"}),
            json.dumps(
                {
                    "v": 1,
                    "kind": "advance",
                    "level": "commit",
                    "lineage": LINEAGE,
                    "ordinal": 4,
                    "record_hash": "a" * 64,
                    "observed_at": 1.0,
                }
            ),
        ]
    )
    assert result.established_head() is not None
    assert result.skipped == ()


def test_an_entry_with_a_non_integer_ordinal_is_not_read():
    result = parse_journal_lines(
        [
            json.dumps(
                {
                    "v": 1,
                    "kind": "advance",
                    "level": "commit",
                    "lineage": LINEAGE,
                    "ordinal": "4",
                    "record_hash": "a" * 64,
                    "observed_at": 1.0,
                }
            )
        ]
    )
    assert result.established_head() is None
    assert result.skipped != ()


# ---------------------------------------------------------------------------
# Absent journal, and the bootstrap receipt (§B.2, §C.3)
# ---------------------------------------------------------------------------


def test_an_absent_journal_reads_empty_rather_than_raising():
    """An absent journal is first contact, not a fault."""
    result = read_journal(LINEAGE)
    assert result.established_head() is None
    assert result.entries == ()
    assert compare(result.established_head(), head(0), None) is Outcome.FIRST_CONTACT


def test_the_bootstrap_receipt_is_the_first_entry_and_survives_every_advance():
    """A single overwritten value would have erased what slice 6 exits on."""
    append_entry(observation(0, kind=Kind.BOOTSTRAP, level=Level.MINT))
    for ordinal in range(1, 5):
        append_entry(observation(ordinal))
    result = read_journal(LINEAGE)
    assert result.bootstrap is not None
    assert result.bootstrap.kind is Kind.BOOTSTRAP
    assert result.bootstrap.level is Level.MINT


def test_a_journal_that_began_at_first_contact_says_so_permanently():
    """It can never be read as proof of anything before it."""
    append_entry(observation(4, kind=Kind.BOOTSTRAP, level=Level.FIRST_CONTACT))
    for ordinal in range(5, 9):
        append_entry(observation(ordinal))
    append_entry(observation(3, kind=Kind.TRUST_RESET, level=Level.FULL))
    result = read_journal(LINEAGE)
    assert result.bootstrap is not None
    assert result.bootstrap.level is Level.FIRST_CONTACT


# ---------------------------------------------------------------------------
# The store-absent split (§D.4)
# ---------------------------------------------------------------------------


def test_no_log_and_no_memory_is_pre_genesis():
    """Refusing here would make minting impossible."""
    assert compare_absent_store(None) is AbsentStoreOutcome.PRE_GENESIS
    assert refusal_for(AbsentStoreOutcome.PRE_GENESIS) is None


def test_no_log_but_a_remembered_head_refuses():
    """A fresh genesis where ordinal 4217 is remembered is a replacement.

    The witness proves what was lost, not its contents — and it must never
    permit a silent re-mint under a remembered lineage.
    """
    append_entry(observation(4217))
    known = read_journal(LINEAGE).established_head()
    assert compare_absent_store(known) is AbsentStoreOutcome.STORE_LOST
    assert refusal_for(AbsentStoreOutcome.STORE_LOST) is StoreLost


def test_the_store_absent_split_is_not_folded_into_the_seven_rows():
    """``compare`` has exactly seven rows and WP2's vectors pin those."""
    assert not set(AbsentStoreOutcome) & set(Outcome)
    assert {outcome.value for outcome in AbsentStoreOutcome} == {
        "pre-genesis",
        "store-lost",
    }


# ---------------------------------------------------------------------------
# The transitional binding (§A.6) — DELETE IN SLICE 5 with the module's section
# ---------------------------------------------------------------------------


def test_a_binding_remembers_which_lineage_a_location_presented():
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    assert bound_lineage("/a/project.arrival") == LINEAGE
    assert bound_lineage("/b/project.arrival") is None


def test_the_newest_binding_for_a_location_wins():
    """Wholesale replacement: a new lineage at a location that had another."""
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    record_binding("/a/project.arrival", OTHER_LINEAGE, 2.0)
    assert bound_lineage("/a/project.arrival") == OTHER_LINEAGE


def test_the_binding_closes_the_wholesale_replacement_hole():
    """Lineage-keying alone would classify this first contact and accept it."""
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    append_entry(observation(9))
    expected = bound_lineage("/a/project.arrival")
    assert expected is not None
    known = read_journal(expected).established_head()
    presented = head(0, "z", lineage=OTHER_LINEAGE)
    assert compare(known, presented, None) is Outcome.LINEAGE_REPLACED


def test_the_bindings_file_lives_beside_the_journals():
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    assert bindings_path() == heads_dir() / "bindings.jsonl"
    assert bindings_path().exists()


def test_a_malformed_binding_line_is_skipped_not_refused():
    """A missing binding degrades to first contact, which it never guaranteed."""
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    with bindings_path().open("a") as handle:
        handle.write("{not json\n")
    assert bound_lineage("/a/project.arrival") == LINEAGE


def test_the_transitional_binding_carries_its_deletion_marker():
    """The residue sweep is written where slice 5 will find it.

    Registry precedent: a transitional arm states its own deletion, so the
    sweep is an obligation in the source rather than a memory somebody has.
    """
    source = Path(
        "libs/engine/src/engine/arrival_head_attestation.py"
    )
    repo_root = Path(__file__).resolve().parents[3]
    text = (repo_root / source).read_text()
    assert "DELETE IN SLICE 5" in text
    assert "residue sweep" in text


# ---------------------------------------------------------------------------
# The import-closure ratchet (§B.1)
# ---------------------------------------------------------------------------


def test_reading_a_head_journal_does_not_drag_the_adapter_in():
    """The journal must stay readable when the store it witnesses cannot open.

    A module that dragged the file codec and sqlite3 behind it would tie its
    own readability to the health of the thing it is judging — which is the
    whole reason this is stdlib plus the contract.
    """
    source = (
        "import sys\n"
        "import engine.arrival_head_attestation as m\n"
        "assert 'sqlite3' not in sys.modules, 'sqlite3 was imported'\n"
        "assert 'engine.arrival' not in sys.modules, 'the adapter was imported'\n"
        "m.parse_journal_lines([])\n"
        "assert 'sqlite3' not in sys.modules, 'reading imported sqlite3'\n"
        "assert 'engine.arrival' not in sys.modules, 'reading imported the adapter'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
