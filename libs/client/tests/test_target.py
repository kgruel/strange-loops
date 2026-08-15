"""Contract and unit tests for client target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from client import (
    TargetInfo,
    TargetNotFound,
    TargetUnsupported,
    resolve_target,
)


def test_resolve_target_vertex_sqlite(tmp_path: Path) -> None:
    """A .vertex target pointing to SQLite store resolves to vertex with sqlite mode."""
    vertex_path = tmp_path / "app.vertex"
    vertex_path.write_text(
        'name "app"\nstore ".loops/data/app.db"\nloops { task { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )

    info = resolve_target(vertex_path)
    assert isinstance(info, TargetInfo)
    assert info.target_type == "vertex"
    assert info.exists is True
    assert info.canonical_mode == "sqlite"
    assert info.canonical_path is not None
    assert info.canonical_path.name == "app.db"
    assert info.index_path is not None
    assert info.index_path.name == "app.db"


def test_resolve_target_vertex_jsonl(tmp_path: Path) -> None:
    """A .vertex target pointing to JSONL log resolves to vertex with jsonl mode."""
    vertex_path = tmp_path / "journal.vertex"
    vertex_path.write_text(
        'name "journal"\nstore ".loops/data/journal.jsonl"\n'
        'loops { entry { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )

    info = resolve_target(vertex_path)
    assert isinstance(info, TargetInfo)
    assert info.target_type == "vertex"
    assert info.exists is True
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path is not None
    assert info.canonical_path.name == "journal.jsonl"
    assert info.index_path is not None
    assert info.index_path.name == "journal.db"


def test_resolve_target_bare_jsonl(tmp_path: Path) -> None:
    """A bare .jsonl file resolves to jsonl_log with derived index path."""
    log_path = tmp_path / "events.jsonl"
    log_path.write_text('{"kind": "tick"}\n', encoding="utf-8")

    info = resolve_target(log_path)
    assert isinstance(info, TargetInfo)
    assert info.target_type == "jsonl_log"
    assert info.exists is True
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path == log_path.resolve()
    assert info.index_path is not None
    assert info.index_path.name == "events.db"


def test_resolve_target_bare_sqlite(tmp_path: Path) -> None:
    """A bare .db file with no sibling .jsonl resolves to sqlite_store."""
    db_path = tmp_path / "data.db"
    db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)

    info = resolve_target(db_path)
    assert isinstance(info, TargetInfo)
    assert info.target_type == "sqlite_store"
    assert info.exists is True
    assert info.canonical_mode == "sqlite"
    assert info.canonical_path == db_path.resolve()
    assert info.index_path == db_path.resolve()


def test_resolve_target_derived_index_sibling(tmp_path: Path) -> None:
    """A .db file with a sibling .jsonl is classified as derived_index with log as canonical."""
    log_path = tmp_path / "stream.jsonl"
    log_path.write_text('{"kind": "tick"}\n', encoding="utf-8")
    index_path = tmp_path / "stream.db"
    index_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)

    info = resolve_target(index_path)
    assert isinstance(info, TargetInfo)
    assert info.target_type == "derived_index"
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path == log_path.resolve()
    assert info.index_path == index_path.resolve()
    assert info.writable is False


def test_resolve_target_nonexistent_raises_target_not_found(tmp_path: Path) -> None:
    """Non-existent paths raise TargetNotFound with the path in the message."""
    missing = tmp_path / "nonexistent.vertex"
    with pytest.raises(TargetNotFound) as exc_info:
        resolve_target(missing)
    assert str(missing) in str(exc_info.value)


def test_resolve_target_unsupported_extensions(tmp_path: Path) -> None:
    """Non-loops file extensions raise TargetUnsupported."""
    for filename in ("notes.txt", "script.py", "README.md", "archive.tar.gz", "config.json"):
        file_path = tmp_path / filename
        file_path.write_text("dummy content", encoding="utf-8")
        with pytest.raises(TargetUnsupported) as exc_info:
            resolve_target(file_path)
        assert "not a recognized loops artifact" in str(exc_info.value)


def test_resolve_target_accepts_str_and_path(tmp_path: Path) -> None:
    """Both str and Path representations of a path resolve identically."""
    vertex_path = tmp_path / "str_test.vertex"
    vertex_path.write_text(
        'name "str_test"\nstore ".loops/data/str.db"\n'
        'loops { item { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )

    info_path = resolve_target(vertex_path)
    info_str = resolve_target(str(vertex_path))
    assert info_path == info_str


def test_discover_targets_tree(tmp_path: Path) -> None:
    """discover_targets scans directories and finds vertices and stores."""
    from client import discover_targets

    # Create workspace tree
    sub1 = tmp_path / "apps" / "frontend"
    sub1.mkdir(parents=True)
    (sub1 / "ui.vertex").write_text(
        'name "ui"\nstore ".loops/data/ui.db"\nloops { e { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )

    sub2 = tmp_path / "apps" / "backend"
    sub2.mkdir(parents=True)
    (sub2 / "api.vertex").write_text(
        'name "api"\nstore ".loops/data/api.db"\nloops { e { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )

    # Hidden dir should be ignored
    hidden = tmp_path / ".venv" / "ignore.vertex"
    hidden.parent.mkdir(parents=True)
    hidden.write_text('name "ignore"\n', encoding="utf-8")

    targets = discover_targets(tmp_path, recursive=True)
    assert len(targets) == 2
    names = {t.canonical_path.name for t in targets if t.canonical_path}
    assert "ui.db" in names
    assert "api.db" in names
