"""Tests for init_vertex scaffolding and inspect_declaration operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from client import (
    ClientValueError,
    DeclarationInspectionResult,
    InitVertexResult,
    TargetError,
    TargetNotFound,
    init_vertex,
    inspect_declaration,
)


def test_init_vertex_standalone_sqlite(tmp_path: Path) -> None:
    """init_vertex creates standalone .vertex file with SQLite store path."""
    target = tmp_path / "project.vertex"
    res = init_vertex(target, name="project", store_type="sqlite")

    assert isinstance(res, InitVertexResult)
    assert res.target_path == str(target.resolve())
    assert res.name == "project"
    assert res.store_type == "sqlite"
    assert res.is_root is False
    assert res.file_written is True
    assert target.exists()

    # Can inspect right away
    info = inspect_declaration(target)
    assert isinstance(info, DeclarationInspectionResult)
    assert info.name == "project"
    assert info.syntax_valid is True
    assert info.errors == []


def test_init_vertex_with_observer_and_strict(tmp_path: Path) -> None:
    """init_vertex configures observer and strict true when requested."""
    target = tmp_path / "strict_app.vertex"
    res = init_vertex(target, name="strict_app", observer="alice", strict=True)
    assert res.file_written is True

    info = inspect_declaration(target)
    assert info.strict is True
    assert "alice" in info.declared_observers


def test_init_vertex_root_discovery(tmp_path: Path) -> None:
    """init_vertex with is_root=True creates a discovery aggregate vertex."""
    target = tmp_path / "root.vertex"
    res = init_vertex(target, is_root=True)

    assert res.is_root is True
    assert target.exists()

    info = inspect_declaration(target)
    assert info.is_aggregate is True


def test_init_vertex_already_exists_raises_target_error(tmp_path: Path) -> None:
    """init_vertex raises TargetError when target already exists and overwrite is False."""
    target = tmp_path / "existing.vertex"
    target.write_text('name "existing"\n', encoding="utf-8")

    with pytest.raises(TargetError) as exc_info:
        init_vertex(target, overwrite=False)
    assert "already exists" in str(exc_info.value)


def test_inspect_declaration_non_vertex_raises(tmp_path: Path) -> None:
    """inspect_declaration raises ClientValueError on non-vertex."""
    log = tmp_path / "data.jsonl"
    log.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ClientValueError) as exc_info:
        inspect_declaration(log)
    assert "requires a .vertex target" in str(exc_info.value)


def test_inspect_declaration_missing_target_raises(tmp_path: Path) -> None:
    """inspect_declaration raises TargetNotFound on non-existent path."""
    missing = tmp_path / "absent.vertex"
    with pytest.raises(TargetNotFound):
        inspect_declaration(missing)


def test_inspect_declaration_syntax_error(tmp_path: Path) -> None:
    """inspect_declaration surfaces syntax errors cleanly without throwing."""
    corrupt = tmp_path / "corrupt.vertex"
    corrupt.write_text("invalid [ { kdl", encoding="utf-8")

    info = inspect_declaration(corrupt)
    assert info.syntax_valid is False
    assert len(info.errors) >= 1
