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
    BindingsUnreadable,
    EstablishedHead,
    HeadAttestation,
    HeadFork,
    HeadLowerBound,
    HeadRewrite,
    HeadRollback,
    HeadUnreadable,
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
    entry_identity,
    heads_dir,
    journal_path,
    last_entry,
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
    """Two entries at one ordinal with one head never equivocate.

    That is the rule, and it is unchanged. What changed is which duplicates
    reach it: a BYTE-IDENTICAL line is now a literal re-assertion and is
    skipped, so the pair that survives to the equivocation check is one whose
    entries agree on the head while differing somewhere in the line — the
    ordinary case, since ``observed_at`` comes from the clock and two genuine
    appends do not share an instant.
    """
    append_entry(observation(6))
    append_entry(
        HeadAttestation(
            head=head(6),
            kind=Kind.ADVANCE,
            level=Level.COMMIT,
            observed_at=1787779021.0,  # a second later: a different line
        )
    )
    result = read_journal(LINEAGE)
    assert result.skipped == ()
    assert result.established_head() is not None
    assert result.established_head().head == head(6)


def test_a_byte_identical_duplicate_is_skipped_as_a_re_assertion():
    """The same head twice in the same bytes is one observation, not two."""
    append_entry(observation(6))
    append_entry(observation(6))
    result = read_journal(LINEAGE)
    assert any("byte-identical" in note for note in result.skipped), result.skipped
    # RECORDED, and weightless: the skipped line's content is a line this read
    # already counted, so nothing about the accepted head is unknown.
    assert isinstance(result.known, EstablishedHead)
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


def append_reset(
    ordinal: int,
    digest: str = "a",
    *,
    level: Level = Level.FULL,
    lineage: str = LINEAGE,
    note: str = "",
) -> HeadAttestation:
    """Append a trust reset BOUND to the entry it follows.

    A reset now names the entry it was appended after, so a replayed copy
    cannot satisfy the binding anywhere else. These tests construct resets by
    hand rather than through the seam's producer, so they bind them the same
    way the producer does — an unbound reset is not a valid reset and would be
    a fixture asserting behavior no writer can produce.
    """
    previous = last_entry(lineage)
    entry = HeadAttestation(
        head=head(ordinal, digest, lineage),
        kind=Kind.TRUST_RESET,
        level=level,
        observed_at=1787779020.0,
        note=note,
        follows=(0, "") if previous is None else (
            previous[0],
            entry_identity(previous[1]),
        ),
    )
    append_entry(entry)
    return entry


def _journal_with_a_reset() -> None:
    """Ordinals 90-100 accepted, then an operator accepts a restore to 90."""
    for ordinal in range(90, 101):
        append_entry(observation(ordinal))
    append_reset(
        90, note="restored from archive; abandoned head was ordinal 100"
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
    append_reset(3)
    append_entry(observation(4))
    append_reset(2)
    result = read_journal(LINEAGE)
    assert [entry.head.ordinal for entry in result.epoch] == [2]
    assert result.established_head() is not None
    assert result.established_head().head.ordinal == 2


def test_equivocation_is_scoped_to_the_current_epoch():
    """Two histories the operator already adjudicated are not a live conflict."""
    append_entry(observation(6, "a"))
    append_entry(observation(6, "b"))
    append_reset(4)
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
    append_reset(90)
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


def test_entries_with_no_header_are_tolerated_as_a_weakened_claim():
    """A bound, not a refusal — the entries are still evidence.

    Losing the header loses the protocol and wire versions these hashes
    derive under, which is exactly what a lower bound is for. Refusing the
    whole file would be a verdict where a weakened claim is available, which
    is the error `HeadUnreadable` was added to correct.
    """
    append_entry(observation(4))
    append_entry(observation(5))
    lines = journal_path(LINEAGE).read_text().splitlines()
    journal_path(LINEAGE).write_text("\n".join(lines[1:]) + "\n")

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 5
    assert any("header: absent" in note for note in result.skipped)
    assert compare(result.known.at_least, head(2), None) is Outcome.ROLLBACK
    with pytest.raises(IndeterminateComparison):
        result.established_head()


def test_the_refusal_names_an_incomplete_read_not_unreadable_lines():
    """A missing header weakens the claim with every entry perfectly readable.

    The refusal message used to say the journal "has unreadable lines", which
    is false here and was the eighth instance of prose naming one cause of the
    weakened state as though it were the definition. The term is "incomplete
    read" — about what the read LACKS, not about why — so a new cause joins it
    without new vocabulary.
    """
    append_entry(observation(4))
    lines = journal_path(LINEAGE).read_text().splitlines()
    journal_path(LINEAGE).write_text("\n".join(lines[1:]) + "\n")

    result = read_journal(LINEAGE)
    with pytest.raises(IndeterminateComparison) as caught:
        result.established_head()
    message = str(caught.value)
    assert "incomplete" in message
    assert "unreadable lines" not in message
    assert "header: absent" in message


def test_a_header_carrying_its_own_kind_does_not_refuse_the_file():
    """A later build's header with a `kind` of its own — sol's demonstration.

    Requiring the type marker AND the absence of `kind` made this an
    uncontracted version-skew refusal of the whole journal. It is now an
    ambiguous line: skipped, reported, and the surrounding entries still read.
    """
    append_entry(observation(4))
    append_entry(observation(5))
    with journal_path(LINEAGE).open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "v": 1,
                    "type": "arrival-head-observation",
                    "kind": "header-v2",
                    "extra": 1,
                }
            )
            + "\n"
        )
    append_entry(observation(6))

    result = read_journal(LINEAGE)
    assert [entry.head.ordinal for entry in result.entries] == [4, 5, 6]
    assert any("both the journal type marker" in n for n in result.skipped)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 6
    with pytest.raises(IndeterminateComparison):
        result.established_head()


def test_a_type_bearing_entry_is_never_absorbed_as_a_header():
    """The mirror hazard, pinned.

    Keying on the type string alone would swallow this whole — an entry that
    happens to carry the marker, absorbed silently, which is the kindless-dict
    failure from the other side. It must be skipped and reported instead.
    """
    entry_carrying_the_marker = json.dumps(
        {
            "v": 1,
            "type": "arrival-head-observation",
            "kind": "advance",
            "level": "commit",
            "lineage": LINEAGE,
            "ordinal": 9999,
            "record_hash": "e" * 64,
            "observed_at": 1.0,
        }
    )
    result = parse_journal_lines([HEADER, entry_carrying_the_marker])

    assert result.entries == ()
    assert any("both the journal type marker" in n for n in result.skipped)
    assert isinstance(result.known, HeadUnreadable)
    with pytest.raises(IndeterminateComparison):
        result.established_head()


def test_a_journal_that_cannot_be_read_as_text_at_all_refuses():
    """What still triggers JournalUnreadable, and why it is the only thing.

    Every structural condition the parser meets now yields a weakened claim
    instead of a verdict. What remains is the case where there is nothing to
    parse: the journal is there and cannot be read at all. Raised as a
    refusal rather than let out as a builtin, so a caller catching
    AttestationRefusal does not have an OSError escape past it.
    """
    path = journal_path(LINEAGE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()  # a directory where the journal should be
    with pytest.raises(JournalUnreadable) as caught:
        read_journal(LINEAGE)
    assert "cannot be read as text at all" in str(caught.value)


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


def test_a_later_build_entry_is_never_refused_on_its_own_account():
    """§B.3's forward-compatibility promise, as the gate re-scoped it.

    An entry this build cannot read is skipped and reported, never refused
    *on its own account*, and readable entries around it still establish a
    head. That is what keeps a shared journal from bricking an older build,
    and it survives verbatim.

    What the promise never licensed is the stronger reading — that a
    comparison holding zero readable evidence should proceed. That case is
    ``test_a_journal_of_nothing_but_later_build_entries_declines`` below;
    declining there refuses no entry.
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


def test_a_kindless_dict_is_not_absorbed_as_a_header():
    """Headers are identified by shape; everything else kindless is a loss.

    Treating any kindless dict as a header absorbed ``{}`` with no skip
    recorded — a second byte pattern through which a line vanished silently,
    and so a second route to the classification this journal exists to
    prevent. Same demonstration as the out-of-order case above, with a
    different two bytes.

    See ``finding:s3wp1-gate-kindless-dict-absorbed-as-header``.
    """
    append_reset(90)
    append_entry(observation(92))  # writer B journals first
    append_entry(observation(91))  # writer A journals last

    lines = journal_path(LINEAGE).read_text().splitlines()
    lines[2] = "{}"  # the line holding the epoch maximum
    journal_path(LINEAGE).write_text("\n".join(lines) + "\n")

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 91
    assert result.skipped != ()
    assert "line 3" in result.skipped[0]
    with pytest.raises(IndeterminateComparison):
        result.established_head()


def test_a_journal_of_nothing_but_later_build_entries_declines():
    """Content claimed, none readable — NOT first contact.

    An empty journal says nothing was ever accepted here, and trust on first
    use is the honest answer to it. A journal holding lines this build cannot
    read says heads WERE accepted and their ordinals are what was lost.
    Collapsing the two would grant TOFU precisely because the journal became
    unreadable.

    The version-skew consequence is real and accepted: an older build against
    a purely newer journal declines its comparisons, and resolution is
    operator work. See ``finding:s3wp1-gate-all-entries-unreadable-silent-tofu``.
    """
    lines = [
        json.dumps(
            {
                "v": 1,
                "type": "arrival-head-observation",
                "protocol": 2,
                "wire": 2,
            }
        )
    ]
    for ordinal in (4215, 4216, 4217):
        lines.append(
            json.dumps(
                {
                    "v": 1,
                    "kind": "checkpoint-from-the-future",
                    "level": "full",
                    "lineage": LINEAGE,
                    "ordinal": ordinal,
                    "record_hash": "d" * 64,
                    "observed_at": 3.0,
                }
            )
        )
    result = parse_journal_lines(lines)

    assert isinstance(result.known, HeadUnreadable)
    assert len(result.skipped) == 3
    assert result.entries == ()

    # Every comparison declines — rollback included, because there is no bound.
    with pytest.raises(IndeterminateComparison) as caught:
        result.established_head()
    assert "NOT first contact" in str(caught.value)
    assert not hasattr(result.known, "at_least")


def test_a_header_only_journal_is_still_first_contact():
    """No surviving OR skipped content claims, so nothing was ever accepted."""
    result = parse_journal_lines([HEADER])
    assert result.known is None
    assert compare(result.established_head(), head(0), None) is Outcome.FIRST_CONTACT


def test_a_header_naming_another_type_is_not_this_journals_header():
    result = parse_journal_lines(
        [json.dumps({"v": 1, "type": "something-else", "protocol": 1})]
    )
    assert result.skipped != ()
    assert isinstance(result.known, HeadUnreadable)


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
    """And a journal of nothing but such an entry claims content it lost."""
    result = parse_journal_lines(
        [
            HEADER,
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
            ),
        ]
    )
    assert isinstance(result.known, HeadUnreadable)
    assert result.skipped != ()
    with pytest.raises(IndeterminateComparison):
        result.established_head()


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
    append_reset(3)
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


def test_a_malformed_binding_line_refuses_rather_than_being_skipped():
    """SUPERSEDED: this pinned the skip, and the skip was the defect.

    The reasoning it carried — "a missing binding degrades to first contact,
    which it never guaranteed" — is true of an ABSENT bindings file and false
    of a line that will not parse. A skipped line may be the very binding that
    names this location, so skipping answers "nothing is bound here" on
    evidence that says nothing of the kind, and a replaced store then opens as
    first contact (``finding:s3wp3-binding-probes-fail-acceptance-side``).

    Absent still answers None, and its own test below is unchanged.
    """
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    with bindings_path().open("a") as handle:
        handle.write("{not json\n")
    with pytest.raises(BindingsUnreadable):
        bound_lineage("/a/project.arrival")


def test_a_non_utf8_bindings_file_refuses_rather_than_escaping_untyped():
    """Sol r3's repro at the layer the open reaches first.

    A raw ``UnicodeDecodeError`` walked past every ``except AttestationRefusal``
    — the same builtin-escape gap ``JournalUnreadable`` closes for the journal,
    which already catches ``UnicodeDecodeError`` alongside ``OSError``.
    """
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    bindings_path().write_bytes(b"\xff\xfe")
    with pytest.raises(BindingsUnreadable) as excinfo:
        bound_lineage("/a/project.arrival")
    assert "not valid UTF-8" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)


def test_an_unusable_shape_refuses_in_bound_lineage_itself():
    """L-7 at this reader, pinned directly.

    Through an open the seam's alias sweep also refuses an unusable shape, so
    reverting this arm alone still produces a refusal and an integration test
    cannot tell the two apart. The direct call is what makes this layer's
    correctness the thing being measured — the third time that lesson has come
    up in this unit, and the first time it was applied before the demo found it.
    """
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    with bindings_path().open("a") as handle:
        handle.write("{}\n")
    with pytest.raises(BindingsUnreadable) as excinfo:
        bound_lineage("/a/project.arrival")
    assert "carries no location and lineage" in str(excinfo.value)


def test_a_binding_naming_another_location_is_still_skipped():
    """The narrow survivor, at this reader too."""
    record_binding("/a/project.arrival", LINEAGE, 1.0)
    record_binding("/b/other.arrival", OTHER_LINEAGE, 2.0)
    assert bound_lineage("/a/project.arrival") == LINEAGE
    assert bound_lineage("/nothing/here.arrival") is None


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


# ---------------------------------------------------------------------------
# Trust-reset replay (finding:s3wp3-trust-reset-replay)
# ---------------------------------------------------------------------------


def test_a_replayed_trust_reset_does_not_reopen_the_epoch_it_closed():
    """Sol r1's repro. An entry is bytes, so an old reset can be re-appended.

    A reset accepting head 5 legitimately closed the epoch that reached 10.
    The journal then advanced to 8. Re-appending a byte-copy of that reset
    would, on last-reset-wins, scope the epoch to it again and read *K* as 5 —
    so a store rolled back to 5 opens UNCHANGED and the abandoned epoch is
    resurrected. Silent re-acceptance, reached through the one entry kind whose
    whole job is to be the licensed way down.

    The binding makes the replay INEXPRESSIBLE rather than merely detectable:
    the copy names the entry it originally followed, and at the end of the
    journal that is not the entry in front of it. It is skipped and reported,
    the genuine earlier reset still opens the epoch, and *K* stays at 8.
    """
    for ordinal in range(1, 11):
        append_entry(observation(ordinal))
    legitimate = append_reset(5, note="restored from archive; abandoned 10")
    # A DIFFERENT digest after the restore: the store re-advances through a new
    # history, so ordinal 6 after the reset is not the ordinal 6 before it.
    # Modelling it as the same bytes would have been the fixture asserting a
    # store no backend produces.
    for ordinal in (6, 7, 8):
        append_entry(observation(ordinal, "b"))

    append_entry(legitimate)  # the replay: the very same entry, again

    result = read_journal(LINEAGE)
    # A replay is recorded and weightless, so the read stays ESTABLISHED — one
    # replayed line must not cost the journal its O(1) unchanged opens.
    assert isinstance(result.known, EstablishedHead)
    assert result.established_head().head.ordinal == 8, "the replay moved K"
    # Caught by the byte-duplicate gate, which now fires BEFORE the position
    # binding ever sees the line — a literal replay is literal bytes.
    assert any("byte-identical" in note for note in result.skipped), result.skipped
    assert compare(result.established_head(), head(5), None) is Outcome.ROLLBACK


def test_the_genuine_reset_is_still_honored_after_the_replay_is_rejected():
    """Rejecting a replay must not reject the reset it was copied from.

    The scan keeps walking back for an earlier valid boundary, so the epoch is
    still the one the operator opened — otherwise closing the replay hole would
    reintroduce the deadlock the epoch scoping exists to prevent.
    """
    for ordinal in range(1, 11):
        append_entry(observation(ordinal))
    legitimate = append_reset(5)
    append_entry(observation(8, "b"))
    append_entry(legitimate)

    result = read_journal(LINEAGE)
    # The epoch still opens at the legitimate reset, and the replayed copy is
    # not in it at all now: the byte-duplicate gate drops the line before it
    # can be an entry, let alone a boundary.
    assert [entry.head.ordinal for entry in result.epoch] == [5, 8]
    assert isinstance(result.known, EstablishedHead)
    assert result.established_head().head.ordinal == 8


def test_a_crash_retry_duplicate_reset_is_skipped_and_never_refuses():
    """The reason this is a skip record rather than a refusal.

    Appending the same reset twice is what a crashed-and-retried ceremony
    leaves. Refusing would brick every subsequent open on an operator's benign
    retry; skipping keeps the journal readable and leaves *K* at the higher
    head, which is the refusal-side failure.
    """
    for ordinal in range(1, 6):
        append_entry(observation(ordinal))
    entry = append_reset(3)
    append_entry(entry)  # the retry lands a second copy

    result = read_journal(LINEAGE)  # does not raise
    assert result.known is not None
    assert any("byte-identical" in note for note in result.skipped)


def test_a_reset_opening_an_empty_journal_binds_to_nothing():
    """There is no predecessor to name, and the empty binding says so."""
    entry = append_reset(4)
    assert entry.follows == (0, "")
    result = read_journal(LINEAGE)
    assert result.skipped == ()
    assert result.epoch == (entry,)


def test_a_reset_with_no_binding_is_not_an_epoch_boundary():
    """The field is REQUIRED — there is no binding-less compat path.

    The journal format exists only on unmerged slice-3 branches, so there is no
    deployed state to migrate and an "unbound resets still count" arm would be
    a permanent hole built for nobody.
    """
    append_entry(observation(1))
    append_entry(observation(9))
    append_entry(observation(2, kind=Kind.TRUST_RESET, level=Level.FULL))

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 9
    assert any("(none)" in note for note in result.skipped), result.skipped


def test_binding_a_reset_does_not_require_a_readable_head():
    """The ceremony must work on the journals it exists to recover from.

    An equivocating journal REFUSES a full read, and equivocation is one of the
    states an operator runs this ceremony to resolve. Binding the reset
    therefore reads the last entry without computing *K*, so producing one
    stays possible exactly when it is needed.
    """
    append_entry(observation(6, "a"))
    append_entry(observation(6, "b"))
    with pytest.raises(JournalEquivocation):
        read_journal(LINEAGE)

    entry = append_reset(4)  # must not raise
    assert entry.follows == (3, entry_identity(observation(6, "b")))
    assert read_journal(LINEAGE).established_head() is not None


# ---------------------------------------------------------------------------
# Sol r2: replaying CONTEXT, not just the entry (finding:s3wp3-trust-reset-replay)
# ---------------------------------------------------------------------------


def _journal_reset_at_5_then_advanced_to_8() -> HeadAttestation:
    """Ordinals 1-10, a legitimate reset accepting 5, then 6-8. Returns the reset."""
    for ordinal in range(1, 11):
        append_entry(observation(ordinal))
    legitimate = append_reset(5, note="restored from archive; abandoned 10")
    for ordinal in (6, 7, 8):
        append_entry(observation(ordinal, "b"))  # a new history after the restore
    return legitimate


def test_replaying_the_predecessor_with_the_reset_does_not_reopen_the_epoch():
    """Sol r2's repro. Identity alone was defeated by replaying CONTEXT.

    Re-appending the historical predecessor and the reset as an ordered suffix
    reproduces the recorded identity exactly — the entry the copy names really
    is sitting in front of it. Identity was the right kind of binding and the
    wrong amount of it: it is a property of the bytes, so bytes can carry it.

    The physical line cannot be carried. Copied bytes appended later land
    later, so the position claim is stale no matter how much surrounding
    context comes with them, which is what makes this close the class rather
    than the instance.
    """
    legitimate = _journal_reset_at_5_then_advanced_to_8()
    predecessor = observation(10)

    append_entry(predecessor)  # the context, replayed
    append_entry(legitimate)  # and the reset behind it

    result = read_journal(LINEAGE)
    # BOTH copied lines are literal replays, so both are skipped — the reset
    # and the advance that was replayed to give it its context. Neither the
    # epoch nor K moves.
    duplicates = [note for note in result.skipped if "byte-identical" in note]
    assert len(duplicates) == 2, result.skipped
    assert isinstance(result.known, EstablishedHead)
    assert result.established_head().head.ordinal == 8
    assert compare(result.established_head(), head(5), None) is Outcome.ROLLBACK


def test_replaying_the_whole_suffix_does_not_reopen_the_epoch():
    """The generalization: more context replayed is still a later position."""
    _journal_reset_at_5_then_advanced_to_8()
    suffix = list(read_journal(LINEAGE).entries)

    for entry in suffix:
        append_entry(entry)

    result = read_journal(LINEAGE)
    assert isinstance(result.known, EstablishedHead)
    assert result.established_head().head.ordinal == 8
    assert compare(result.established_head(), head(5), None) is Outcome.ROLLBACK
    assert any("byte-identical" in note for note in result.skipped)


def test_a_replayed_advance_cannot_reimport_an_abandoned_head():
    """The acceptance vector, and why direction was the wrong thing to judge by.

    Re-appending an ``advance`` from before a reset used to raise *K* to an
    abandoned head. I classified that as safe because *K* moved UP, and refused
    more. That was the wrong axis. The head *K* then named was GENUINE — a real
    head this machine really did accept — so a store restored from the pre-reset
    backup presents it exactly, compares EQUAL, and the unchanged arm does no
    descent verification by design. The ceremonially abandoned state opened
    silently. A wrongly-raised *K* naming a real abandoned head is a landing
    pad, not a wall.

    The byte-duplicate gate closes it at the source: the replayed line is
    literal bytes this journal already holds, so it re-asserts rather than
    records, and *K* never moves.
    """
    _journal_reset_at_5_then_advanced_to_8()
    assert read_journal(LINEAGE).established_head().head.ordinal == 8

    append_entry(observation(10))  # an abandoned head, re-asserted verbatim

    result = read_journal(LINEAGE)
    assert any("byte-identical" in note for note in result.skipped)
    assert isinstance(result.known, EstablishedHead)
    known = result.established_head()
    assert known.head.ordinal == 8, "K reached an abandoned head"
    # And the restored abandoned backup is no longer equal to what is
    # remembered — it is now a REWRITE, refused on a full comparison rather
    # than declined on a bound.
    assert known.head != head(10)
    assert compare(known, head(10), None) is Outcome.REWRITE


def test_an_injected_collision_costs_a_walk_and_never_an_acceptance():
    """Where the gate is wrong, it must be wrong on the verification side.

    Two genuinely independent events that serialize to identical bytes are
    indistinguishable from a replay, so the gate drops the later one. This
    constructs exactly that — a post-reset entry whose bytes coincide with one
    from the abandoned epoch — and pins the consequence, rather than resting on
    the collision being improbable.

    The consequence is that *K* reads LOWER than the truth. The store then
    presents a head above it, which is an ADVANCE, and the advance branch is
    the one that pays for a verified walk: descent from the remembered head is
    established before anything is accepted. Cost, not credulity — the failure
    lands on the verification side, never on acceptance.
    """
    for ordinal in (1, 2, 3):
        append_entry(observation(ordinal))
    append_reset(1)
    append_entry(observation(3))  # a genuine new entry, colliding with line 4

    result = read_journal(LINEAGE)
    assert any("byte-identical" in note for note in result.skipped)
    # K is the reset head, NOT the colliding 3 — lower than the truth. And the
    # read is now ESTABLISHED at that low K, which is what makes the dedup
    # predicate acceptance-load-bearing: a false match discards a real line and
    # still claims to know the head. This is the pin for that weight.
    known = result.established_head()
    assert known is not None
    assert known.head.ordinal == 1
    # A store at the true head is therefore an ADVANCE, which must establish
    # descent rather than be believed: with no vouched record at K, REWRITE.
    assert compare(known, head(3), None) is Outcome.REWRITE
    assert compare(known, head(3), head(1)) is Outcome.ADVANCED


def test_concatenating_a_foreign_journal_does_not_import_its_resets():
    """The combine case. Every appended reset lands at a shifted line.

    A journal pasted onto the end of another is the bulk form of a replay, and
    it is the one an ordinary tool could do by accident. The foreign resets all
    carry positions from the file they were written in, so none of them opens
    an epoch here and *K* stays the local maximum.
    """
    for ordinal in (1, 2, 3):
        append_entry(observation(ordinal))
    local = append_reset(2)
    append_entry(observation(9))

    foreign_lines = [
        HEADER,
        json.dumps(
            {
                "v": 1,
                "kind": "advance",
                "level": "commit",
                "lineage": LINEAGE,
                "ordinal": 4,
                "record_hash": "c" * 64,
                "observed_at": 1.0,
            }
        ),
        json.dumps(
            {
                "v": 1,
                "kind": "trust-reset",
                "level": "full",
                "lineage": LINEAGE,
                "ordinal": 4,
                "record_hash": "c" * 64,
                "observed_at": 1.0,
                # A binding that was valid IN ITS OWN FILE, at line 2.
                "follows": [2, "does-not-matter"],
            }
        ),
    ]
    with journal_path(LINEAGE).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(foreign_lines) + "\n")

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 9, "a foreign reset took hold"
    assert any("trust-reset" in note for note in result.skipped)
    assert local.head.ordinal == 2


def test_the_position_is_the_physical_line_not_an_index_of_parsed_entries():
    """A judgment-dependent index would drift; a file line does not.

    An unreadable line sits between the predecessor and the reset here. It
    occupies a physical line, so the predecessor's line number accounts for it
    — where an index among successfully parsed entries would not, and would
    renumber the moment a future build classified that line differently.
    """
    append_entry(observation(1))
    with journal_path(LINEAGE).open("a", encoding="utf-8") as handle:
        handle.write("{ not json at all\n")
    entry = append_reset(1)

    assert entry.follows is not None
    # header(1), observation(2), damage(3) — so the predecessor is at line 2,
    # while its index among parsed entries is 0.
    assert entry.follows[0] == 2
    result = read_journal(LINEAGE)
    assert result.epoch == (entry,), "the reset was not honored"


# ---------------------------------------------------------------------------
# Per-cause skip weighting (finding:s3-dedup-skip-weakens-read-permanently)
# ---------------------------------------------------------------------------


def test_a_crash_retry_duplicate_does_not_weaken_the_read_forever():
    """The empirical case: one benign retry must not cost the file its O(1) opens.

    A crash-retry duplicate is byte-identical BY CONSTRUCTION — the same entry,
    written again — and the journal is append-only, so the duplicate line is
    there for the life of the file. Weighting it would have bounded every
    subsequent read forever: ``established_head()`` raising for good, and the
    unchanged-open design gone, from a crash that lost nothing.

    The skip record stays. What it stops doing is representing ignorance,
    because the content it skipped is a line this read already counted.
    """
    append_entry(observation(1))
    append_entry(observation(1))  # the retry, byte-identical
    for ordinal in (2, 3, 4, 5):
        append_entry(observation(ordinal))

    result = read_journal(LINEAGE)
    assert any("byte-identical" in note for note in result.skipped), result.skipped
    known = result.established_head()  # ANSWERS rather than raising
    assert known is not None
    assert known.head == head(5)
    assert compare(known, head(5), None) is Outcome.UNCHANGED
    assert compare(known, head(7), known.head) is Outcome.ADVANCED


def test_a_dedup_skip_beside_an_unreadable_line_still_bounds():
    """Per-CAUSE, not per-read — and this is the case that tells them apart.

    "A read whose only skips are re-assertions is established" is the wrong
    shape: it does not compose. Here a weightless re-assertion sits beside a
    line that genuinely could not be read, and the read must still bound —
    because the unreadable line carries its own weight regardless of what else
    is in the file.
    """
    append_entry(observation(1))
    append_entry(observation(1))  # weightless
    with journal_path(LINEAGE).open("a", encoding="utf-8") as handle:
        handle.write("{ not json at all\n")  # carries weight
    append_entry(observation(2))

    result = read_journal(LINEAGE)
    assert any("byte-identical" in note for note in result.skipped)
    assert any("does not parse" in note for note in result.skipped)
    assert isinstance(result.known, HeadLowerBound)
    # The bound names only the causes that produced it, not every skip.
    assert all("byte-identical" not in note for note in result.known.skipped)
    with pytest.raises(IndeterminateComparison):
        result.established_head()


def test_a_voided_reset_keeps_its_weight():
    """Ruled narrowly: only a re-assertion is weightless.

    A reset whose binding does not match is a line whose CONTENT is perfectly
    readable — so the tempting generalization is that it carries no ignorance
    either. It does: what is unknown is not the bytes but what the operator
    meant by them, and a bound is exactly how that uncertainty is represented.
    """
    append_entry(observation(1))
    append_entry(observation(9))
    append_entry(observation(2, kind=Kind.TRUST_RESET, level=Level.FULL))

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 9
    assert any("trust-reset" in note for note in result.known.skipped)


# ---------------------------------------------------------------------------
# Amendment #5: weakening is epoch-scoped by physical line position
# ---------------------------------------------------------------------------


def _damaged_then_reset_then_clean() -> None:
    """Damage at line 3, a reset later, then a clean advance.

    The construction from my own verify-item-1 report, which is what produced
    the ruling: the operator ran the ceremony precisely to put the damage
    behind them.
    """
    append_entry(observation(1))
    append_entry(observation(2))
    path = journal_path(LINEAGE)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines.insert(2, "{ damaged line\n")
    path.write_text("".join(lines), encoding="utf-8")
    append_reset(2)
    append_entry(observation(3, "b"))


def test_damage_behind_the_boundary_no_longer_weakens_the_read():
    """The healing story, and the regression this amendment exists for.

    A line-positioned loss sitting BEFORE the boundary reset's line carries no
    weight: the ceremony decreed trust in a head, and everything positionally
    behind that decree is what it decreed past. Without this the operator runs
    the ceremony, gets a correct K, and is still handed a bounded read forever
    from damage the reset was run to put behind them.
    """
    _damaged_then_reset_then_clean()
    result = read_journal(LINEAGE)
    assert any("does not parse" in note for note in result.skipped)
    known = result.established_head()  # ANSWERS
    assert known is not None
    assert known.head == head(3, "b")


def test_damage_at_or_after_the_boundary_still_weakens():
    """Position scoping is not an amnesty. Only what is BEHIND the decree."""
    append_entry(observation(1))
    append_reset(1)
    append_entry(observation(2, "b"))
    with journal_path(LINEAGE).open("a", encoding="utf-8") as handle:
        handle.write("{ damaged line\n")  # after the boundary

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    with pytest.raises(IndeterminateComparison):
        result.established_head()


def test_a_failed_ceremony_attempt_does_not_bound_a_successful_rerun():
    """The healing story end to end.

    A reset whose binding did not match is a weakening cause, so the operator's
    own failed attempt could otherwise bound every read after it — the remedy
    being the thing that broke them.

    It heals through the epoch walk rather than through position weighting, and
    the distinction matters for anyone reading this as coverage of the latter:
    ``_epoch_of`` walks BACKWARD and returns at the first valid reset, so the
    voided attempt below it is never examined and produces no note at all.
    Position scoping is exercised by the damage tests, not by this one.
    """
    append_entry(observation(1))
    append_entry(observation(9))
    append_entry(observation(2, kind=Kind.TRUST_RESET, level=Level.FULL))  # voided
    assert isinstance(read_journal(LINEAGE).known, HeadLowerBound)

    append_reset(9)  # the operator re-runs it, correctly this time

    result = read_journal(LINEAGE)
    known = result.established_head()  # healed
    assert known is not None
    assert known.head.ordinal == 9
    # The voided attempt is not even reported, and that is the backward walk
    # short-circuiting at the first valid boundary rather than a loss: the
    # operator was already told at the time, because `trust_reset` reads its
    # own entry back and raises `TrustResetNotHonored` when it does not take.
    assert not any("trust-reset" in note for note in result.skipped)


def test_a_missing_header_weakens_regardless_of_any_boundary():
    """Edge 1: a structural absence has no position to be decreed past.

    The header would be line 1 and would sit below every boundary, so position
    scoping would silently exempt the one loss that is a claim about the FILE
    rather than about a line. Structural losses carry no line and keep their
    weight.
    """
    append_entry(observation(1))
    path = journal_path(LINEAGE)
    body = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(body[1:]), encoding="utf-8")  # drop the header
    append_reset(1)

    result = read_journal(LINEAGE)
    assert any("header" in note for note in result.skipped)
    assert isinstance(result.known, HeadLowerBound)
    assert any("header" in note for note in result.known.skipped)


def test_with_no_valid_reset_every_weakening_cause_keeps_full_weight():
    """Edge 3: "nothing to be after" is not the same as "after it"."""
    append_entry(observation(1))
    with journal_path(LINEAGE).open("a", encoding="utf-8") as handle:
        handle.write("{ damaged line\n")
    append_entry(observation(2))

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 2


def test_damage_on_both_sides_bounds_from_the_current_epoch_only():
    """Mixed: the abandoned side is weightless, the current side bounds.

    And ``at_least`` comes from the epoch, so an abandoned high ordinal cannot
    inflate the bound into false rollback refusals against a genuine
    current-epoch store.
    """
    for ordinal in (98, 99, 100):
        append_entry(observation(ordinal))
    path = journal_path(LINEAGE)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines.insert(2, "{ abandoned-epoch damage\n")
    path.write_text("".join(lines), encoding="utf-8")
    append_reset(90)
    append_entry(observation(91, "b"))
    with journal_path(LINEAGE).open("a", encoding="utf-8") as handle:
        handle.write("{ current-epoch damage\n")

    result = read_journal(LINEAGE)
    assert isinstance(result.known, HeadLowerBound)
    assert result.known.at_least.head.ordinal == 91, "an abandoned ordinal leaked in"
    assert len(result.known.skipped) == 1, result.known.skipped
    assert "current-epoch damage" not in result.known.skipped[0]
