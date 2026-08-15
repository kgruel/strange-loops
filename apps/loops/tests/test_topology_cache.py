"""Tests for cache-first _topology resolution in loops.main._try_topology_from_store.

Relocated here from libs/engine/tests/test_topology.py. These exercise
``loops.main``, which is application code, so they belong to the application's
suite: a core library's tests importing an app inverts the dependency the
architecture rules enforce for production source, and it only surfaced when CI
ran each package in isolation (`uv run --package engine`), where the app is not
installed. It passed on developer machines for the worst reason — the venv
happened to contain the app.

The vertex-building helpers below are duplicated from the engine suite rather
than imported across the boundary, because importing them would recreate the
same inversion in the other direction.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _create_child_vertex(parent_dir: Path, name: str, *, with_store: bool = True) -> Path:
    """Create a child vertex file with loops declarations and optional store."""
    child_dir = parent_dir / name
    child_dir.mkdir(parents=True, exist_ok=True)
    vpath = child_dir / f"{name}.vertex"

    store_line = f'store "./data/{name}.db"\n' if with_store else ""
    content = (
        f'name "{name}"\n'
        f"{store_line}\n"
        "loops {\n"
        "  item {\n"
        "    fold {\n"
        '      items "by" "name"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    vpath.write_text(content)

    if with_store:
        db_path = child_dir / "data" / f"{name}.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _init_store(db_path)

    return vpath


def _init_store(db_path: Path) -> None:
    """Initialize a minimal SQLite store schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS facts ("
        "    id TEXT NOT NULL PRIMARY KEY,"
        "    kind TEXT NOT NULL,"
        "    ts REAL NOT NULL,"
        "    observer TEXT NOT NULL,"
        "    origin TEXT NOT NULL DEFAULT '',"
        "    payload TEXT NOT NULL"
        ");"
        "CREATE TABLE IF NOT EXISTS ticks ("
        "    id TEXT NOT NULL PRIMARY KEY,"
        "    name TEXT NOT NULL,"
        "    ts REAL NOT NULL,"
        "    since REAL,"
        "    origin TEXT NOT NULL,"
        "    payload TEXT NOT NULL"
        ");"
    )
    conn.commit()
    conn.close()


def _create_root_vertex(tmp_path: Path, *, with_store: bool = True) -> Path:
    """Create a root vertex with discover and optional store + _topology."""
    store_line = 'store "./data/root.db"\n' if with_store else ""
    topology_block = (
        "  _topology {\n"
        "    fold {\n"
        '      items "by" "name"\n'
        "    }\n"
        "  }\n"
    ) if with_store else ""

    content = (
        'name "root"\n'
        f"{store_line}"
        'discover "./**/*.vertex"\n\n'
        "loops {\n"
        f"{topology_block}"
        "}\n"
    )
    vpath = tmp_path / "root.vertex"
    vpath.write_text(content)
    return vpath


class TestTopologyCacheResolution:
    """Tests for cache-first _topology resolution in _try_topology_from_store."""

    def test_cache_hit_returns_kind_keys_and_stores(self, tmp_path):
        """Reading _topology from store returns correct kind_keys and store paths."""
        from engine.vertex_reader import emit_topology

        _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path)

        emit_topology(root)

        # Now read back using the cache function
        from loops.main import _try_topology_from_store

        db_path = tmp_path / "data" / "root.db"
        result = _try_topology_from_store(db_path)

        assert result is not None
        kind_keys, store_paths = result
        assert "item" in kind_keys
        assert kind_keys["item"] == "name"
        assert len(store_paths) == 1
        assert store_paths[0].exists()

    def test_cache_miss_on_empty_store(self, tmp_path):
        """Returns None when store has no _topology facts."""
        from loops.main import _try_topology_from_store

        db_path = tmp_path / "data" / "test.db"
        _init_store(db_path)

        result = _try_topology_from_store(db_path)
        assert result is None

    def test_cache_miss_on_stale_store_path(self, tmp_path):
        """Returns None when a cached store path no longer exists."""
        from engine.vertex_reader import emit_topology

        _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path)

        emit_topology(root)

        # Delete the child's store to make the cache stale
        child_db = tmp_path / "alpha" / "data" / "alpha.db"
        child_db.unlink()

        from loops.main import _try_topology_from_store

        db_path = tmp_path / "data" / "root.db"
        result = _try_topology_from_store(db_path)
        assert result is None  # Stale — should trigger fallback

    def test_cache_miss_on_nonexistent_store(self, tmp_path):
        """Returns None when store db doesn't exist."""
        from loops.main import _try_topology_from_store

        result = _try_topology_from_store(tmp_path / "nonexistent.db")
        assert result is None
