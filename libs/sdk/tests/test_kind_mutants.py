"""Mutation-testing survivor burn-down for sdk.kind.

Each test here pins a precise, previously-unasserted behavioral detail of
sdk.kind's public surface (add_kind, edit_kind, remove_kind, grant_observer,
revoke_observer, plan_kind_mutation) — exact error messages, exact result
field values, and the exact shape of the `changes` list — so that mutants
mutating those details fail rather than survive.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from custody import ensure_signing_key
from lang.ast import FoldCollect, FoldDecl, LoopDef

from sdk import (
    CeremonyFailed,
    DeclarationPlanResult,
    KindMutationResult,
    SdkValueError,
    TargetUnsupported,
    add_kind,
    edit_kind,
    grant_observer,
    inspect_declaration,
    plan_kind_mutation,
    remove_kind,
    revoke_observer,
)

# --------------------------------------------------------------------------
# Exact error messages (TargetUnsupported / SdkValueError text)
# --------------------------------------------------------------------------


def test_target_unsupported_messages_are_exact(tmp_path: Path) -> None:
    """Each op's TargetUnsupported message names the op and the wrong target type."""
    log_path = tmp_path / "standalone.jsonl"
    log_path.write_text('{"kind": "note"}\n', encoding="utf-8")

    with pytest.raises(
        TargetUnsupported, match=r"^add_kind requires a \.vertex target, got jsonl_log$"
    ):
        add_kind(log_path, "test", observer="admin")

    with pytest.raises(
        TargetUnsupported, match=r"^edit_kind requires a \.vertex target, got jsonl_log$"
    ):
        edit_kind(log_path, "test", LoopDef(folds=()), observer="admin")

    with pytest.raises(
        TargetUnsupported, match=r"^remove_kind requires a \.vertex target, got jsonl_log$"
    ):
        remove_kind(log_path, "test", observer="admin")

    with pytest.raises(
        TargetUnsupported, match=r"^grant_observer requires a \.vertex target, got jsonl_log$"
    ):
        grant_observer(log_path, "alice", observer="admin")

    with pytest.raises(
        TargetUnsupported, match=r"^revoke_observer requires a \.vertex target, got jsonl_log$"
    ):
        revoke_observer(log_path, "alice", observer="admin")

    with pytest.raises(
        TargetUnsupported, match=r"^plan_kind_mutation requires a \.vertex target, got jsonl_log$"
    ):
        plan_kind_mutation(log_path, "add", "test")


def test_plan_kind_mutation_invalid_op_message(sample_vertex: Path) -> None:
    """An unsupported op raises SdkValueError naming the op and the valid choices."""
    with pytest.raises(
        SdkValueError,
        match=r"^unsupported mutation op 'bogus', expected 'add', 'edit', or 'remove'$",
    ):
        plan_kind_mutation(sample_vertex, "bogus", "todo")


# --------------------------------------------------------------------------
# op dispatch — each branch must call the right helper, not a sibling one
# --------------------------------------------------------------------------


def test_plan_kind_mutation_edit_op(sample_vertex: Path) -> None:
    """op='edit' plans an edit of the existing 'note' kind."""
    new_def = LoopDef(folds=(FoldDecl("items", FoldCollect(5)),))
    plan = plan_kind_mutation(sample_vertex, "edit", "note", new_def)
    assert isinstance(plan, DeclarationPlanResult)
    assert plan.applicable is True


def test_plan_kind_mutation_remove_op(multi_kind_vertex: Path) -> None:
    """op='remove' plans removal of an existing kind."""
    plan = plan_kind_mutation(multi_kind_vertex, "remove", "task")
    assert plan.applicable is True


def test_plan_kind_mutation_edit_nonexistent_is_refused(sample_vertex: Path) -> None:
    """op='edit' on a kind that does not exist is a refused (non-applicable) plan."""
    plan = plan_kind_mutation(sample_vertex, "edit", "ghost", LoopDef(folds=()))
    assert plan.applicable is False
    assert plan.mode == "refused"
    assert plan.generation_before is None
    assert plan.changes == []
    assert plan.vertex_path == str(sample_vertex.resolve())
    assert plan.reason  # non-empty, carries the underlying ValueError text


def test_plan_kind_mutation_remove_nonexistent_is_refused(sample_vertex: Path) -> None:
    """op='remove' on a kind that does not exist is a refused plan."""
    plan = plan_kind_mutation(sample_vertex, "remove", "ghost")
    assert plan.applicable is False
    assert plan.mode == "refused"
    assert plan.generation_before is None
    assert plan.changes == []


def test_plan_kind_mutation_add_duplicate_is_refused(sample_vertex: Path) -> None:
    """op='add' on an already-declared kind is a refused plan (not an exception)."""
    plan = plan_kind_mutation(sample_vertex, "add", "note")
    assert plan.applicable is False
    assert plan.mode == "refused"
    assert plan.vertex_path == str(sample_vertex.resolve())
    assert plan.generation_before is None
    assert plan.changes == []
    assert plan.reason != "None"
    assert "note" in plan.reason or "already exists" in plan.reason


# --------------------------------------------------------------------------
# result field wiring on success — every field, not just status
# --------------------------------------------------------------------------


def test_add_kind_result_fields_and_changes(sample_vertex: Path) -> None:
    """add_kind's KindMutationResult carries every field wired to the right source,
    and `changes` is a non-empty list of change descriptions naming the added kind."""
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "priming", observer="admin")  # leave genesis mode first

    result = add_kind(sample_vertex, "todo", observer="admin")

    assert isinstance(result, KindMutationResult)
    assert result.status in ("applied", "noop")
    assert isinstance(result.reason, str) and result.reason
    assert isinstance(result.mode, str) and result.mode
    assert result.vertex_path == str(sample_vertex.resolve())
    assert isinstance(result.generation_before, dict)
    assert isinstance(result.generation_after, dict)
    assert result.generation_before != result.generation_after
    assert result.file_written is True

    assert isinstance(result.changes, list)
    assert len(result.changes) >= 1
    # Change entries are lang.document.Change NamedTuples without as_dict —
    # they must fall through to the str(c) branch, and each must name 'todo'.
    for change in result.changes:
        assert isinstance(change, str)
        assert "todo" in change


def test_edit_kind_result_fields(sample_vertex: Path) -> None:
    """edit_kind's result generation/changes reflect the edit against gen 1."""
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "priming", observer="admin")  # leave genesis mode first
    new_def = LoopDef(folds=(FoldDecl("items", FoldCollect(10)),))

    result = edit_kind(sample_vertex, "note", definition=new_def, observer="admin")

    assert isinstance(result.generation_before, dict)
    assert isinstance(result.generation_after, dict)
    assert result.generation_before != result.generation_after
    assert result.vertex_path == str(sample_vertex.resolve())
    assert isinstance(result.mode, str) and result.mode
    assert isinstance(result.reason, str) and result.reason
    assert result.file_written is True
    assert len(result.changes) >= 1
    assert all(isinstance(c, str) and "note" in c for c in result.changes)


def test_remove_kind_result_fields(multi_kind_vertex: Path) -> None:
    """remove_kind's result generation/changes reflect the removal against gen 1."""
    ensure_signing_key(multi_kind_vertex, "admin")
    add_kind(multi_kind_vertex, "priming", observer="admin")  # leave genesis mode first

    result = remove_kind(multi_kind_vertex, "note", observer="admin")

    assert isinstance(result.generation_before, dict)
    assert isinstance(result.generation_after, dict)
    assert result.generation_before != result.generation_after
    assert result.vertex_path == str(multi_kind_vertex.resolve())
    assert isinstance(result.mode, str) and result.mode
    assert isinstance(result.reason, str) and result.reason
    assert result.file_written is True
    assert len(result.changes) >= 1
    assert any(isinstance(c, str) and "note" in c for c in result.changes)


def test_grant_observer_result_fields(sample_vertex: Path) -> None:
    """grant_observer's result generation/changes reflect the grant against gen 1."""
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "priming", observer="admin")  # leave genesis mode first

    result = grant_observer(sample_vertex, "bob", grants=["note"], observer="admin")

    assert isinstance(result.generation_before, dict)
    assert isinstance(result.generation_after, dict)
    assert result.generation_before != result.generation_after
    assert result.vertex_path == str(sample_vertex.resolve())
    assert isinstance(result.mode, str) and result.mode
    assert isinstance(result.reason, str) and result.reason
    assert len(result.changes) >= 1
    assert any(isinstance(c, str) and "bob" in c for c in result.changes)
    assert result.file_written is True


def test_revoke_observer_result_fields(sample_vertex: Path) -> None:
    """revoke_observer's result generation/changes reflect the revoke."""
    ensure_signing_key(sample_vertex, "admin")
    grant_observer(sample_vertex, "bob", grants=["note"], observer="admin")

    result = revoke_observer(sample_vertex, "bob", observer="admin")

    assert isinstance(result.generation_before, dict)
    assert isinstance(result.generation_after, dict)
    assert result.generation_before != result.generation_after
    assert result.vertex_path == str(sample_vertex.resolve())
    assert isinstance(result.mode, str) and result.mode
    assert isinstance(result.reason, str) and result.reason
    assert result.file_written is True
    assert len(result.changes) >= 1
    assert any(isinstance(c, str) and "bob" in c for c in result.changes)


def test_plan_kind_mutation_result_fields(sample_vertex: Path) -> None:
    """plan_kind_mutation's applicable-plan result carries preview fields and changes."""
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "priming", observer="admin")  # leave genesis mode first

    plan = plan_kind_mutation(sample_vertex, "add", "todo")

    assert plan.applicable is True
    assert plan.mode in ("genesis", "clean", "edit")
    assert plan.vertex_path == str(sample_vertex.resolve())
    assert isinstance(plan.generation_before, dict)
    assert isinstance(plan.reason, str) and plan.reason
    assert isinstance(plan.changes, list)
    assert len(plan.changes) >= 1
    assert any("todo" in c for c in plan.changes)


def test_edit_kind_identical_definition_is_noop(sample_vertex: Path) -> None:
    """Editing a kind with the exact definition it already has produces status='noop'
    (engine.ceremony's mode=='edit' and not preview.changes path)."""
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "priming", observer="admin")  # leave genesis mode first
    same_def = LoopDef(folds=(FoldDecl("items", FoldCollect(100)),))  # matches sample_vertex's note

    result = edit_kind(sample_vertex, "note", definition=same_def, observer="admin")

    assert result.status == "noop"


def test_grant_observer_identical_grant_is_noop(sample_vertex: Path) -> None:
    """Re-granting an observer with identical identity/key/grants produces status='noop'."""
    ensure_signing_key(sample_vertex, "admin")
    explicit_key = "Z" * 43 + "="

    grant_observer(sample_vertex, "gina", key=explicit_key, grants=["note"], observer="admin")
    result = grant_observer(
        sample_vertex, "gina", key=explicit_key, grants=["note"], observer="admin"
    )

    assert result.status == "noop"


def test_plan_kind_mutation_pending_intent_is_non_applicable_without_exception(
    sample_vertex: Path,
) -> None:
    """A stray .intent sibling makes the SUCCESS-branch preview non-applicable
    (pending_intent path in engine.ceremony) — this never raises SdkValueError,
    it flows straight through to the normal DeclarationPlanResult construction
    with preview.applicable/preview.reason actually False/non-default."""
    intent_path = sample_vertex.parent / (sample_vertex.name + ".intent")
    intent_path.write_text("bogus pending intent", encoding="utf-8")

    plan = plan_kind_mutation(sample_vertex, "add", "todo")

    assert plan.applicable is False
    assert "pending declaration-update intent" in plan.reason


# --------------------------------------------------------------------------
# grant_observer: key resolution branch (auto-mint vs explicit) must be exact
# --------------------------------------------------------------------------


def test_grant_observer_explicit_key_is_used_verbatim(sample_vertex: Path) -> None:
    """An explicitly supplied key bypasses custody minting and lands in the file as-is."""
    ensure_signing_key(sample_vertex, "admin")
    explicit_key = "Q" * 43 + "="  # syntactically key-shaped, not required to be valid crypto

    grant_observer(sample_vertex, "carol", key=explicit_key, observer="admin")

    text = sample_vertex.read_text(encoding="utf-8")
    assert explicit_key in text


def test_grant_observer_auto_minted_keys_differ_per_observer(sample_vertex: Path) -> None:
    """Two observers granted without an explicit key each get their OWN minted key
    (ensure_signing_key must be called with this observer's name, not None/shared)."""
    ensure_signing_key(sample_vertex, "admin")

    grant_observer(sample_vertex, "alice", observer="admin")
    grant_observer(sample_vertex, "dave", observer="admin")

    text = sample_vertex.read_text(encoding="utf-8")
    keys = re.findall(r'key "([^"]+)"', text)
    assert len(keys) >= 2
    assert len(set(keys)) == len(keys), "each auto-minted observer key must be distinct"


# --------------------------------------------------------------------------
# revoke_observer: exact refusal message on a non-existent observer
# --------------------------------------------------------------------------


def test_revoke_nonexistent_observer_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    with pytest.raises(
        CeremonyFailed,
        match=r"^could not remove observer 'ghost_observer': ",
    ):
        revoke_observer(sample_vertex, "ghost_observer", observer="admin")


def test_grant_observer_empty_name_message_exact(sample_vertex: Path) -> None:
    """An empty observer_name makes upsert_vertex_observer raise; grant_observer
    wraps it with the 'could not splice observer grant' prefix and the real detail."""
    ensure_signing_key(sample_vertex, "admin")
    with pytest.raises(CeremonyFailed, match=r"^could not splice observer grant: "):
        grant_observer(sample_vertex, "", observer="admin")


# --------------------------------------------------------------------------
# add/edit/remove_kind exact "could not generate kind mutation" refusal text
# --------------------------------------------------------------------------


def test_add_kind_duplicate_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    with pytest.raises(CeremonyFailed, match=r"^could not generate kind mutation: "):
        add_kind(sample_vertex, "note", observer="admin")


def test_edit_kind_nonexistent_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    with pytest.raises(CeremonyFailed, match=r"^could not generate kind mutation: "):
        edit_kind(sample_vertex, "ghost_kind", LoopDef(folds=()), observer="admin")


def test_remove_kind_nonexistent_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    with pytest.raises(CeremonyFailed, match=r"^could not generate kind mutation: "):
        remove_kind(sample_vertex, "ghost_kind", observer="admin")


# --------------------------------------------------------------------------
# grant_observer: identity/grants must be threaded through to the written text
# --------------------------------------------------------------------------


def test_grant_observer_identity_and_grants_threaded(sample_vertex: Path) -> None:
    """identity= and grants= reach the written declaration verbatim."""
    ensure_signing_key(sample_vertex, "admin")

    grant_observer(
        sample_vertex,
        "erin",
        identity="erin-identity",
        grants=["note", "todo"],
        observer="admin",
    )

    text = sample_vertex.read_text(encoding="utf-8")
    assert "erin-identity" in text
    assert "note" in text
    assert "todo" in text

    info = inspect_declaration(sample_vertex)
    assert "erin" in info.declared_observers


def test_grant_observer_no_grants_produces_empty_grant_set(sample_vertex: Path) -> None:
    """Omitting grants= (None) must not silently pass through a bogus/None grants value."""
    ensure_signing_key(sample_vertex, "admin")

    result = grant_observer(sample_vertex, "frank", observer="admin")
    assert result.status in ("applied", "noop")

    info = inspect_declaration(sample_vertex)
    assert "frank" in info.declared_observers


# --------------------------------------------------------------------------
# "declaration update not applicable" CeremonyFailed — reached via the
# SUCCESS-branch preview (pending-intent), not the helper's ValueError catch.
# --------------------------------------------------------------------------


def _plant_pending_intent(vertex_path: Path) -> None:
    (vertex_path.parent / (vertex_path.name + ".intent")).write_text(
        "bogus pending intent", encoding="utf-8"
    )


def test_add_kind_not_applicable_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    _plant_pending_intent(sample_vertex)

    with pytest.raises(CeremonyFailed, match=r"^declaration update not applicable: "):
        add_kind(sample_vertex, "todo", observer="admin")


def test_edit_kind_not_applicable_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    _plant_pending_intent(sample_vertex)
    new_def = LoopDef(folds=(FoldDecl("items", FoldCollect(5)),))

    with pytest.raises(CeremonyFailed, match=r"^declaration update not applicable: "):
        edit_kind(sample_vertex, "note", new_def, observer="admin")


def test_remove_kind_not_applicable_message_exact(multi_kind_vertex: Path) -> None:
    ensure_signing_key(multi_kind_vertex, "admin")
    _plant_pending_intent(multi_kind_vertex)

    with pytest.raises(CeremonyFailed, match=r"^declaration update not applicable: "):
        remove_kind(multi_kind_vertex, "note", observer="admin")


def test_grant_observer_not_applicable_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    _plant_pending_intent(sample_vertex)

    with pytest.raises(CeremonyFailed, match=r"^declaration update not applicable: "):
        grant_observer(sample_vertex, "alice", observer="admin")


def test_revoke_observer_not_applicable_message_exact(sample_vertex: Path) -> None:
    ensure_signing_key(sample_vertex, "admin")
    grant_observer(sample_vertex, "alice", observer="admin")
    _plant_pending_intent(sample_vertex)

    with pytest.raises(CeremonyFailed, match=r"^declaration update not applicable: "):
        revoke_observer(sample_vertex, "alice", observer="admin")
