"""Integration and contract tests for declaration mutations and ceremonies."""

from __future__ import annotations

from pathlib import Path

import pytest
from custody import ensure_signing_key
from lang.ast import FoldCollect, FoldCount, FoldDecl, LoopDef

from client import (
    CeremonyFailed,
    KindMutationResult,
    TargetNotFound,
    TargetUnsupported,
    add_kind,
    edit_kind,
    emit_fact,
    read_state,
    remove_kind,
)


def test_add_kind_default_and_emit(sample_vertex: Path) -> None:
    """add_kind adds default definition, writes file, and permits emission."""
    ensure_signing_key(sample_vertex, "admin")

    result = add_kind(
        sample_vertex,
        "todo",
        observer="admin",
    )

    assert isinstance(result, KindMutationResult)
    assert result.status in ("applied", "noop")
    assert result.file_written is True
    assert result.mode in ("genesis", "clean")
    assert result.vertex_path == str(sample_vertex.resolve())

    # State now contains 'todo'
    state = read_state(sample_vertex)
    assert "todo" in state.sections
    assert "note" in state.sections

    # Can now emit 'todo' facts without admit_undeclared
    receipt = emit_fact(
        sample_vertex,
        "todo",
        {"task": "Buy groceries"},
        observer="admin",
    )
    assert receipt.stored is True


def test_add_kind_custom_definition(sample_vertex: Path) -> None:
    """add_kind with explicit LoopDef applies custom fold operations."""
    ensure_signing_key(sample_vertex, "admin")

    custom_def = LoopDef(
        folds=(
            FoldDecl("items", FoldCollect(25)),
            FoldDecl("count", FoldCount()),
        )
    )

    result = add_kind(
        sample_vertex,
        "metric",
        definition=custom_def,
        observer="admin",
    )
    assert result.status in ("applied", "noop")

    state = read_state(sample_vertex)
    assert "metric" in state.sections


def test_edit_kind(sample_vertex: Path) -> None:
    """edit_kind modifies an existing kind definition."""
    ensure_signing_key(sample_vertex, "admin")

    new_def = LoopDef(folds=(FoldDecl("items", FoldCollect(10)),))

    result = edit_kind(
        sample_vertex,
        "note",
        definition=new_def,
        observer="admin",
    )
    assert result.status in ("applied", "noop")

    state = read_state(sample_vertex)
    assert "note" in state.sections


def test_remove_kind(multi_kind_vertex: Path) -> None:
    """remove_kind removes a declared kind from the vertex."""
    ensure_signing_key(multi_kind_vertex, "admin")

    result = remove_kind(
        multi_kind_vertex,
        "note",
        observer="admin",
    )
    assert result.status in ("applied", "noop")

    state = read_state(multi_kind_vertex)
    assert "note" not in state.sections
    assert "task" in state.sections


def test_kind_operations_target_unsupported(tmp_path: Path) -> None:
    """Kind mutation operations raise TargetUnsupported on non-vertex targets."""
    log_path = tmp_path / "standalone.jsonl"
    log_path.write_text('{"kind": "note"}\n', encoding="utf-8")

    with pytest.raises(TargetUnsupported):
        add_kind(log_path, "test", observer="admin")

    with pytest.raises(TargetUnsupported):
        edit_kind(log_path, "test", LoopDef(folds=()), observer="admin")

    with pytest.raises(TargetUnsupported):
        remove_kind(log_path, "test", observer="admin")


def test_kind_operations_target_not_found(tmp_path: Path) -> None:
    """Kind mutation operations raise TargetNotFound on missing targets."""
    missing = tmp_path / "missing.vertex"

    with pytest.raises(TargetNotFound):
        add_kind(missing, "test", observer="admin")

    with pytest.raises(TargetNotFound):
        edit_kind(missing, "test", LoopDef(folds=()), observer="admin")

    with pytest.raises(TargetNotFound):
        remove_kind(missing, "test", observer="admin")


def test_default_loop_def() -> None:
    """_default_loop_def provides items collect 100."""
    from client.kind import _default_loop_def

    default_def = _default_loop_def()
    assert len(default_def.folds) == 1
    fold = default_def.folds[0]
    assert fold.target == "items"
    assert isinstance(fold.op, FoldCollect)
    assert fold.op.max_items == 100


def test_add_kind_duplicate_raises_ceremony_failed(sample_vertex: Path) -> None:
    """add_kind for an already existing kind raises CeremonyFailed."""
    ensure_signing_key(sample_vertex, "admin")

    with pytest.raises(CeremonyFailed) as exc_info:
        add_kind(sample_vertex, "note", observer="admin")
    assert "could not generate kind mutation" in str(exc_info.value) or "already exists" in str(
        exc_info.value
    )


def test_edit_kind_nonexistent_raises_ceremony_failed(sample_vertex: Path) -> None:
    """edit_kind for a non-existent kind raises CeremonyFailed."""
    ensure_signing_key(sample_vertex, "admin")

    with pytest.raises(CeremonyFailed) as exc_info:
        edit_kind(sample_vertex, "ghost_kind", LoopDef(folds=()), observer="admin")
    assert "could not generate kind mutation" in str(exc_info.value) or "does not exist" in str(
        exc_info.value
    )


def test_remove_kind_nonexistent_raises_ceremony_failed(sample_vertex: Path) -> None:
    """remove_kind for a non-existent kind raises CeremonyFailed."""
    ensure_signing_key(sample_vertex, "admin")

    with pytest.raises(CeremonyFailed) as exc_info:
        remove_kind(sample_vertex, "ghost_kind", observer="admin")
    assert "could not generate kind mutation" in str(exc_info.value) or "does not exist" in str(
        exc_info.value
    )


def test_recover_ceremony_nonexistent(tmp_path: Path) -> None:
    """recover_ceremony handles non-existent intent file cleanly."""
    from client import recover_ceremony

    missing_intent = tmp_path / "test.vertex.intent"
    outcome = recover_ceremony(missing_intent)
    assert isinstance(outcome, dict)
    assert "classification" in outcome
    assert "finished" in outcome
    assert "reason" in outcome
    assert outcome["intent_path"] == str(missing_intent)


def test_plan_kind_mutation_preview(sample_vertex: Path) -> None:
    """plan_kind_mutation performs preflight ceremony planning without disk mutation."""
    from client import DeclarationPlanResult, plan_kind_mutation

    original_text = sample_vertex.read_text(encoding="utf-8")

    plan = plan_kind_mutation(sample_vertex, "add", "planned_kind")
    assert isinstance(plan, DeclarationPlanResult)
    assert plan.applicable is True
    assert plan.mode in ("genesis", "clean")
    assert plan.schema == "loops.cli/declaration-plan/v1"

    # Disk text was not modified
    assert sample_vertex.read_text(encoding="utf-8") == original_text


def test_grant_and_revoke_observer(sample_vertex: Path) -> None:
    """grant_observer and revoke_observer manage the declared admission block."""
    from client import grant_observer, inspect_declaration, revoke_observer

    ensure_signing_key(sample_vertex, "admin")

    # Grant 'alice' with task and note capabilities
    res = grant_observer(
        sample_vertex,
        "alice",
        grants=["task", "note"],
        observer="admin",
    )
    assert res.status in ("applied", "noop")

    # Check via inspection
    info = inspect_declaration(sample_vertex)
    assert "alice" in info.declared_observers

    # Revoke 'alice'
    revoke_res = revoke_observer(sample_vertex, "alice", observer="admin")
    assert revoke_res.status in ("applied", "noop")

    info_after = inspect_declaration(sample_vertex)
    assert "alice" not in info_after.declared_observers
