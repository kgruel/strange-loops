"""Tests for _topology self-knowledge — emit_topology and vertex_read with own store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


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


class TestEmitTopology:
    """Tests for emit_topology — writing _topology facts to aggregation store."""

    def test_emits_topology_for_discovered_children(self, tmp_path):
        """emit_topology creates a _topology fact per discovered child vertex."""
        from engine.vertex_reader import emit_topology

        _create_child_vertex(tmp_path, "alpha")
        _create_child_vertex(tmp_path, "beta")
        root = _create_root_vertex(tmp_path)

        emit_topology(root)

        # Read back topology facts from root's store
        db_path = tmp_path / "data" / "root.db"
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT kind, observer, payload FROM facts WHERE kind = '_topology' ORDER BY payload"
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        names = set()
        for kind, observer, payload_json in rows:
            assert kind == "_topology"
            assert observer == "root"
            payload = json.loads(payload_json)
            names.add(payload["name"])
            assert "path" in payload
            assert "store" in payload
            assert "kind_keys" in payload
            assert payload["kind_keys"].get("item") == "name"

        assert names == {"alpha", "beta"}

    def test_emits_nothing_without_store(self, tmp_path):
        """emit_topology is a no-op when the vertex has no store declaration."""
        from engine.vertex_reader import emit_topology

        _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path, with_store=False)

        emit_topology(root)

        # No store should have been created
        db_path = tmp_path / "data" / "root.db"
        assert not db_path.exists()

    def test_emits_nothing_without_children(self, tmp_path):
        """emit_topology is a no-op when no children are discovered."""
        from engine.vertex_reader import emit_topology

        root = _create_root_vertex(tmp_path)

        emit_topology(root)

        # Store might be created by SqliteStore but should have no _topology facts
        db_path = tmp_path / "data" / "root.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT COUNT(*) FROM facts WHERE kind = '_topology'").fetchone()
            conn.close()
            assert rows[0] == 0

    def test_re_emission_is_additive(self, tmp_path):
        """Re-emitting topology adds new facts (fold handles dedup via upsert)."""
        from engine.vertex_reader import emit_topology

        _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path)

        emit_topology(root)
        emit_topology(root)

        db_path = tmp_path / "data" / "root.db"
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT COUNT(*) FROM facts WHERE kind = '_topology'").fetchone()
        conn.close()

        # Two emissions, one child = 2 raw facts (fold deduplicates at read time)
        assert rows[0] == 2

    def test_topology_payload_includes_store_path(self, tmp_path):
        """_topology facts include absolute store path for the child."""
        from engine.vertex_reader import emit_topology

        _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path)

        emit_topology(root)

        db_path = tmp_path / "data" / "root.db"
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT payload FROM facts WHERE kind = '_topology'"
        ).fetchone()
        conn.close()

        payload = json.loads(row[0])
        assert payload["store"]
        store_path = Path(payload["store"])
        assert store_path.is_absolute()

    def test_topology_child_without_store(self, tmp_path):
        """Children without a store get empty store string in topology."""
        from engine.vertex_reader import emit_topology

        _create_child_vertex(tmp_path, "alpha", with_store=False)
        root = _create_root_vertex(tmp_path)

        emit_topology(root)

        db_path = tmp_path / "data" / "root.db"
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT payload FROM facts WHERE kind = '_topology'"
        ).fetchone()
        conn.close()

        payload = json.loads(row[0])
        assert payload["store"] == ""


class TestVertexReadWithTopology:
    """Tests for vertex_read on vertices with both store and discover."""

    def test_reads_own_store_kinds(self, tmp_path):
        """vertex_read returns _topology from aggregation's own store."""
        from engine.vertex_reader import emit_topology, vertex_read

        _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path)

        # Emit topology facts to root's store
        emit_topology(root)

        # vertex_read should return _topology from own store
        state = vertex_read(root)
        assert "_topology" in state
        items = state["_topology"]["items"]
        assert "alpha" in items
        assert items["alpha"]["name"] == "alpha"

    def test_reads_combined_children_kinds(self, tmp_path):
        """vertex_read still returns inherited kinds from children."""
        from engine.vertex_reader import vertex_read

        child_vpath = _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path)

        # Seed a fact in the child store
        child_db = tmp_path / "alpha" / "data" / "alpha.db"
        conn = sqlite3.connect(str(child_db))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            ("FACT001", "item", 1000.0, "test", "", json.dumps({"name": "thing1", "value": 42})),
        )
        conn.commit()
        conn.close()

        state = vertex_read(root)
        # Should have inherited 'item' kind from child
        assert "item" in state
        assert "thing1" in state["item"]["items"]

    def test_reads_both_own_and_children(self, tmp_path):
        """vertex_read returns both self-knowledge and inherited kinds."""
        from engine.vertex_reader import emit_topology, vertex_read

        _create_child_vertex(tmp_path, "alpha")
        root = _create_root_vertex(tmp_path)

        # Seed child data
        child_db = tmp_path / "alpha" / "data" / "alpha.db"
        conn = sqlite3.connect(str(child_db))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            ("FACT001", "item", 1000.0, "test", "", json.dumps({"name": "thing1"})),
        )
        conn.commit()
        conn.close()

        # Emit topology
        emit_topology(root)

        state = vertex_read(root)
        assert "_topology" in state  # self-knowledge
        assert "item" in state  # inherited from child


class TestTopologyCacheResolution:
    """Tests for cache-first _topology resolution in _try_topology_from_store."""

    def test_cache_hit_returns_kind_keys_and_stores(self, tmp_path):
        """Reading _topology from store returns correct kind_keys and store paths."""
        from engine.vertex_reader import emit_topology

        child_vpath = _create_child_vertex(tmp_path, "alpha")
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
