"""Contract and unit tests for SDK target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdk import (
    TargetInfo,
    TargetNotFound,
    TargetUnsupported,
    discover_targets,
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
        expected_msg = (
            f"target {file_path.resolve()} is not a recognized loops artifact "
            "(accepted: .vertex, .jsonl, .db, .sqlite)"
        )
        assert expected_msg in str(exc_info.value)


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


def test_discover_targets_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """discover_targets uses current directory, recursive=True, include_bare=True by default."""
    sub = tmp_path / "nested"
    sub.mkdir(parents=True)
    (sub / "app.vertex").write_text(
        'name "app"\nstore ".loops/data/app.db"\nloops { e { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    (sub / "bare_stream.jsonl").write_text('{"kind": "tick"}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    # Calling discover_targets() without arguments tests all defaults
    targets = discover_targets()
    assert len(targets) == 2
    found_names = {t.canonical_path.name for t in targets if t.canonical_path}
    assert "app.db" in found_names
    assert "bare_stream.jsonl" in found_names


def test_discover_targets_root_not_dir(tmp_path: Path) -> None:
    """discover_targets returns empty list when root_path is not a directory."""
    file_path = tmp_path / "regular_file.txt"
    file_path.write_text("hello", encoding="utf-8")
    assert discover_targets(file_path) == []
    assert discover_targets(tmp_path / "nonexistent_dir") == []


def test_discover_targets_ignore_patterns(tmp_path: Path) -> None:
    """discover_targets ignores directories in _IGNORE_DIRS or starting with dot."""
    # node_modules is in _IGNORE_DIRS but does not start with '.'
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "mod.vertex").write_text('name "mod"\nstore ".loops/data/mod.db"\n', encoding="utf-8")

    # .custom_hidden starts with '.' but is not in _IGNORE_DIRS
    hidden = tmp_path / ".custom_hidden" / "sub"
    hidden.mkdir(parents=True)
    (hidden / "hidden.vertex").write_text(
        'name "hidden"\nstore ".loops/data/h.db"\n',
        encoding="utf-8",
    )

    # Valid vertex in normal directory
    normal = tmp_path / "normal"
    normal.mkdir(parents=True)
    (normal / "valid.vertex").write_text(
        'name "valid"\nstore ".loops/data/v.db"\nloops { e { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )

    targets = discover_targets(tmp_path)
    assert len(targets) == 1
    assert targets[0].canonical_path is not None
    assert targets[0].canonical_path.name == "v.db"


def test_discover_targets_bare_formats_and_loops_exclusion(tmp_path: Path) -> None:
    """discover_targets finds bare .jsonl, .db, .sqlite and excludes .loops derived stores."""
    (tmp_path / "stream.jsonl").write_text('{"kind": "tick"}\n', encoding="utf-8")
    (tmp_path / "standalone.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)
    (tmp_path / "standalone.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)

    # Derived store inside .loops should be skipped even when scanning .loops directly
    loops_dir = tmp_path / ".loops"
    loops_data = loops_dir / "data"
    loops_data.mkdir(parents=True)
    (loops_data / "derived.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)
    (loops_data / "second.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)

    # When include_bare=True
    targets = discover_targets(tmp_path, include_bare=True)
    names = [t.canonical_path.name for t in targets if t.canonical_path]
    assert "stream.jsonl" in names
    assert "standalone.db" in names
    assert "standalone.sqlite" in names
    assert "derived.db" not in names
    assert all(isinstance(t, TargetInfo) for t in targets)

    # When scanning .loops directly, .loops in entry.parts excludes derived stores
    assert discover_targets(loops_dir, include_bare=True) == []

    # When include_bare=False
    bare_excluded = discover_targets(tmp_path, include_bare=False)
    assert bare_excluded == []


def test_discover_targets_resilience_to_errors(tmp_path: Path) -> None:
    """discover_targets discovers valid targets cleanly."""
    (tmp_path / "01_valid.vertex").write_text(
        'name "valid"\nstore ".loops/data/valid.db"\nloops { e { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    (tmp_path / "02_good.jsonl").write_text('{"kind": "tick"}\n', encoding="utf-8")

    targets = discover_targets(tmp_path)
    names = {t.canonical_path.name for t in targets if t.canonical_path}
    assert "valid.db" in names
    assert "02_good.jsonl" in names


def test_discover_targets_sorting_order(tmp_path: Path) -> None:
    """discover_targets sorts results deterministically by canonical path."""
    # a_app.vertex is visited first by filename, but points to z_store.db
    (tmp_path / "a_app.vertex").write_text(
        'name "a_app"\nstore ".loops/data/z_store.db"\n'
        'loops { e { fold { items "collect" 1 } } }\n',
        encoding="utf-8",
    )

    # z_app.vertex is visited second by filename, but points to a_store.db
    (tmp_path / "z_app.vertex").write_text(
        'name "z_app"\nstore ".loops/data/a_store.db"\n'
        'loops { e { fold { items "collect" 1 } } }\n',
        encoding="utf-8",
    )

    (tmp_path / "storeless.vertex").write_text(
        'name "storeless"\nloops { item { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )

    targets = discover_targets(tmp_path)
    assert len(targets) == 3
    # storeless.vertex has canonical_path=None -> sorts with key "" before string paths
    assert targets[0].canonical_path is None
    # a_store.db sorts before z_store.db even though a_app was discovered first
    assert targets[1].canonical_path is not None and targets[1].canonical_path.name == "a_store.db"
    assert targets[2].canonical_path is not None and targets[2].canonical_path.name == "z_store.db"

