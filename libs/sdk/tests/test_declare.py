"""Tests for init_vertex scaffolding and inspect_declaration operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdk import (
    DeclarationInspectionResult,
    InitVertexResult,
    SdkValueError,
    TargetError,
    TargetNotFound,
    init_vertex,
    inspect_declaration,
)


def test_init_vertex_standalone_sqlite(tmp_path: Path) -> None:
    """init_vertex creates standalone .vertex file with SQLite store path."""
    target = tmp_path / "project.vertex"
    # Calling init_vertex without name or store_type tests default arguments
    res = init_vertex(target)

    assert isinstance(res, InitVertexResult)
    assert res.target_path == str(target.resolve())
    assert res.name == "project"
    assert res.store_type == "sqlite"
    assert res.store_path == ".loops/data/project.db"
    assert res.is_root is False
    assert res.file_written is True
    assert target.exists()

    # Can inspect right away
    info = inspect_declaration(target)
    assert isinstance(info, DeclarationInspectionResult)
    assert info.target_path == str(target.resolve())
    assert info.name == "project"
    assert info.status == "file-pre-genesis"
    assert info.store_mode == "sqlite"
    assert info.store_path is not None and info.store_path.endswith("project.db")
    assert info.declared_kinds == ["item"]
    assert info.declared_observers == []
    assert info.cadence_ticks == []
    assert info.strict is False
    assert info.is_aggregate is False
    assert info.syntax_valid is True
    assert info.errors == []


def test_init_vertex_with_observer_and_strict(tmp_path: Path) -> None:
    """init_vertex configures observer keypair and strict true when requested."""
    target = tmp_path / "strict_app.vertex"
    res = init_vertex(target, name="strict_app", observer="alice", strict=True)
    assert res.file_written is True
    assert (target.parent / "keys" / "alice" / "ed25519.key").exists()

    info = inspect_declaration(target)
    assert info.strict is True
    assert info.declared_observers == ["alice"]


def test_init_vertex_root_discovery(tmp_path: Path) -> None:
    """init_vertex with is_root=True creates a discovery aggregate vertex."""
    target = tmp_path / "root.vertex"
    res = init_vertex(target, is_root=True)

    assert res.is_root is True
    assert res.store_path is None
    assert target.exists()

    info = inspect_declaration(target)
    assert info.is_aggregate is True
    assert info.declared_kinds == []

    # The generated discovery comment is fixed content (case, wording) — pin it so
    # a corruption of the scaffold text doesn't silently drift unnoticed.
    written = target.read_text(encoding="utf-8")
    assert "// Root vertex — discovers all .vertex files under this directory\n" in written


def test_init_vertex_already_exists_raises_target_error(tmp_path: Path) -> None:
    """init_vertex raises TargetError when target already exists and overwrite is False."""
    target = tmp_path / "existing.vertex"
    target.write_text('name "existing"\n', encoding="utf-8")

    # Default overwrite is False
    with pytest.raises(TargetError) as exc_info:
        init_vertex(target)
    assert f"vertex file already exists: {target.resolve()}" in str(exc_info.value)

    # Overwrite=True succeeds
    res = init_vertex(target, overwrite=True)
    assert res.file_written is True


def test_init_vertex_jsonl_and_custom_store_path(tmp_path: Path) -> None:
    """init_vertex configures JSONL extension and custom store paths correctly."""
    target_jsonl = tmp_path / "jsonl_app.vertex"
    res1 = init_vertex(target_jsonl, store_type="jsonl")
    assert res1.store_type == "jsonl"
    assert res1.store_path == ".loops/data/jsonl_app.jsonl"
    info1 = inspect_declaration(target_jsonl)
    assert info1.store_mode == "jsonl"

    target_upper = tmp_path / "upper_app.vertex"
    res2 = init_vertex(target_upper, store_type="JSONL")
    assert res2.store_path == ".loops/data/upper_app.jsonl"

    target_custom = tmp_path / "custom_app.vertex"
    res3 = init_vertex(target_custom, store_path="custom/path.db")
    assert res3.store_path == "custom/path.db"
    info3 = inspect_declaration(target_custom)
    assert info3.store_path is not None and "custom/path.db" in info3.store_path


def test_init_vertex_nested_parents(tmp_path: Path) -> None:
    """init_vertex creates nested parent directories when they do not exist."""
    target_nested = tmp_path / "deep" / "nested" / "dir" / "app.vertex"
    res = init_vertex(target_nested)
    assert res.file_written is True
    assert target_nested.exists()


def test_inspect_declaration_non_vertex_raises(tmp_path: Path) -> None:
    """inspect_declaration raises SdkValueError on non-vertex."""
    log = tmp_path / "data.jsonl"
    log.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SdkValueError) as exc_info:
        inspect_declaration(log)
    assert "inspect_declaration requires a .vertex target, got jsonl_log" in str(exc_info.value)


def test_inspect_declaration_missing_target_raises(tmp_path: Path) -> None:
    """inspect_declaration raises TargetNotFound on non-existent path."""
    missing = tmp_path / "absent.vertex"
    with pytest.raises(TargetNotFound) as exc_info:
        inspect_declaration(missing)
    assert f"target path does not exist: {missing.resolve()}" in str(exc_info.value)


def test_inspect_declaration_syntax_error(tmp_path: Path) -> None:
    """inspect_declaration surfaces syntax errors cleanly without throwing."""
    corrupt = tmp_path / "corrupt.vertex"
    corrupt.write_text("invalid [ { kdl", encoding="utf-8")

    info = inspect_declaration(corrupt)
    assert info.syntax_valid is False
    assert len(info.errors) >= 1
    assert isinstance(info.errors[0], str) and "None" not in info.errors and len(info.errors[0]) > 0
    assert info.status == "uninitialized"
    assert info.strict is False
    assert info.is_aggregate is False


def test_inspect_declaration_name_differs_from_stem(tmp_path: Path) -> None:
    """inspect_declaration uses declared name when it differs from file stem."""
    target = tmp_path / "stem_name.vertex"
    target.write_text(
        'name "explicit_declared_name"\n'
        'store ".loops/data/app.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )

    info = inspect_declaration(target)
    assert info.name == "explicit_declared_name"
    assert info.name != target.stem


def test_inspect_declaration_unadopted_lineage_error(tmp_path: Path) -> None:
    """inspect_declaration captures store declaration errors in errors list."""
    import sqlite3

    db_path = tmp_path / "unadopted.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE facts (id TEXT, ts REAL, kind TEXT, payload TEXT)")
    conn.execute("INSERT INTO facts VALUES ('1', 1.0, '_decl.genesis', '{}')")
    conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

    target = tmp_path / "unadopted.vertex"
    target.write_text(
        'name "unadopted"\n'
        f'store "{db_path}"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )

    info = inspect_declaration(target)
    assert info.syntax_valid is True
    assert len(info.errors) == 1
    assert "no own_lineage marker" in info.errors[0]
    assert info.status == "uninitialized"


def test_inspect_declaration_multiple_loops(tmp_path: Path) -> None:
    """inspect_declaration extracts declared loop kinds and sets empty cadence_ticks."""
    target = tmp_path / "multi_app.vertex"
    target.write_text(
        'name "multi_app"\n'
        'store ".loops/data/multi.db"\n'
        'loops {\n'
        '  task { fold { items "collect" 10 } }\n'
        '  event { fold { items "collect" 20 } }\n'
        '}\n',
        encoding="utf-8",
    )

    info = inspect_declaration(target)
    assert info.name == "multi_app"
    assert info.cadence_ticks == []
    assert info.declared_kinds == ["event", "task"]


def test_inspect_declaration_combine_aggregate(tmp_path: Path) -> None:
    """inspect_declaration recognizes combine aggregate vertices."""
    target = tmp_path / "combine_app.vertex"
    target.write_text(
        'name "combine_app"\n'
        'combine {\n'
        '  vertex "a"\n'
        '  vertex "b"\n'
        '}\n',
        encoding="utf-8",
    )

    info = inspect_declaration(target)
    assert info.is_aggregate is True
    assert info.name == "combine_app"
    assert info.syntax_valid is True


def test_inspect_declaration_fallback_name(tmp_path: Path) -> None:
    """inspect_declaration falls back to file stem when name is not explicitly declared."""
    target = tmp_path / "unnamed.vertex"
    target.write_text(
        'store ".loops/data/unnamed.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )

    info = inspect_declaration(target)
    assert info.name == "unnamed"

