"""Integration and contract tests for declaration mutations and ceremonies."""

from __future__ import annotations

from pathlib import Path

import pytest
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
from custody import ensure_signing_key
from lang.ast import FoldCollect, FoldCount, FoldDecl, LoopDef


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

    new_def = LoopDef(
        folds=(FoldDecl("items", FoldCollect(10)),)
    )

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
