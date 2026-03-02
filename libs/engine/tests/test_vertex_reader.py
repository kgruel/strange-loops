"""Tests for vertex_reader — query-time fold materialization."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def _create_vertex_file(tmp_path: Path, name: str, loops_kdl: str) -> Path:
    """Write a .vertex file with a store pointing to a .db in tmp_path."""
    content = f'name "{name}"\nstore "./store.db"\n\nloops {{\n{loops_kdl}\n}}\n'
    vpath = tmp_path / f"{name}.vertex"
    vpath.write_text(content)
    return vpath


def _seed_facts(db_path: Path, facts: list[dict]) -> None:
    """Insert facts into a SQLite store at db_path."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS facts ("
        "    rowid INTEGER PRIMARY KEY,"
        "    kind TEXT NOT NULL,"
        "    ts REAL NOT NULL,"
        "    observer TEXT NOT NULL,"
        "    origin TEXT NOT NULL DEFAULT '',"
        "    payload TEXT NOT NULL"
        ");"
        "CREATE TABLE IF NOT EXISTS ticks ("
        "    rowid INTEGER PRIMARY KEY,"
        "    name TEXT NOT NULL,"
        "    ts REAL NOT NULL,"
        "    since REAL,"
        "    origin TEXT NOT NULL,"
        "    payload TEXT NOT NULL"
        ");"
    )
    for f in facts:
        conn.execute(
            "INSERT INTO facts (kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?)",
            (f["kind"], f["ts"], f.get("observer", "test"), f.get("origin", ""), json.dumps(f["payload"])),
        )
    conn.commit()
    conn.close()


class TestVertexRead:
    """vertex_read: compile vertex declaration, replay facts, return fold state."""

    def test_upsert_fold(self, tmp_path):
        """FoldBy (Upsert) groups facts by key, keeping latest payload per key."""
        from engine import vertex_read

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "use JWT"}},
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "db", "message": "use SQLite"}},
            {"kind": "decision", "ts": 3000.0, "payload": {"topic": "auth", "message": "use sessions"}},
        ])

        result = vertex_read(vpath)
        items = result["decision"]["items"]

        # auth updated to latest payload
        assert items["auth"]["message"] == "use sessions"
        assert items["auth"]["_ts"] == 3000.0

        # db unchanged
        assert items["db"]["message"] == "use SQLite"
        assert items["db"]["_ts"] == 2000.0

    def test_collect_fold(self, tmp_path):
        """FoldCollect keeps last N items in insertion order."""
        from engine import vertex_read

        vpath = _create_vertex_file(tmp_path, "test", '  change { fold { items "collect" 2 } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "change", "ts": 1000.0, "payload": {"summary": "first"}},
            {"kind": "change", "ts": 2000.0, "payload": {"summary": "second"}},
            {"kind": "change", "ts": 3000.0, "payload": {"summary": "third"}},
        ])

        result = vertex_read(vpath)
        items = result["change"]["items"]

        # Only last 2 kept
        assert len(items) == 2
        assert items[0]["summary"] == "second"
        assert items[1]["summary"] == "third"

    def test_latest_fold(self, tmp_path):
        """FoldLatest stores timestamp of most recent fact."""
        from engine import vertex_read

        vpath = _create_vertex_file(tmp_path, "test", '  handoff { fold { items "latest" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "handoff", "ts": 1000.0, "payload": {"task": "a"}},
            {"kind": "handoff", "ts": 5000.0, "payload": {"task": "b"}},
        ])

        result = vertex_read(vpath)
        assert result["handoff"]["items"] == 5000.0

    def test_empty_store(self, tmp_path):
        """No store file → initial state for all kinds."""
        from engine import vertex_read

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        # Don't create store.db

        result = vertex_read(vpath)
        assert result["decision"]["items"] == {}

    def test_no_store_declared(self, tmp_path):
        """Vertex with no store → initial state."""
        from engine import vertex_read

        content = 'name "nostored"\nloops {\n  decision { fold { items "by" "topic" } }\n}\n'
        vpath = tmp_path / "nostored.vertex"
        vpath.write_text(content)

        result = vertex_read(vpath)
        assert result["decision"]["items"] == {}

    def test_handoff_proof(self, tmp_path):
        """Adding a new kind to vertex surfaces in read with zero code changes.

        This is the proof that the architecture works: new kinds are driven
        by declaration, not by code.
        """
        from engine import vertex_read

        # Vertex with original 4 kinds + handoff (5th)
        vpath = _create_vertex_file(tmp_path, "project", """
  decision { fold { items "by" "topic" } }
  thread   { fold { items "by" "name" } }
  change   { fold { items "collect" 20 } }
  task     { fold { items "by" "name" } }
  handoff  { fold { items "latest" } }
""")
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "handoff", "ts": 2000.0, "payload": {"context": "finishing auth"}},
        ])

        result = vertex_read(vpath)

        # All 5 kinds present in result
        assert set(result.keys()) == {"decision", "thread", "change", "task", "handoff"}

        # Handoff surfaced automatically — no reader code knows about it
        assert result["handoff"]["items"] == 2000.0

        # Original kinds still work
        assert "auth" in result["decision"]["items"]


class TestVertexFacts:
    """vertex_facts: raw fact access through the vertex."""

    def test_time_range(self, tmp_path):
        """Returns facts within the time range."""
        from engine import vertex_facts

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "b"}},
            {"kind": "decision", "ts": 3000.0, "payload": {"topic": "c"}},
        ])

        facts = vertex_facts(vpath, 1500.0, 2500.0)
        assert len(facts) == 1
        assert facts[0]["payload"]["topic"] == "b"

    def test_kind_filter(self, tmp_path):
        """Filters by kind when specified."""
        from engine import vertex_facts

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "thread", "ts": 1000.0, "payload": {"name": "b"}},
        ])

        facts = vertex_facts(vpath, 0.0, 9999.0, kind="decision")
        assert len(facts) == 1
        assert facts[0]["kind"] == "decision"

    def test_no_store(self, tmp_path):
        """No store file → empty list."""
        from engine import vertex_facts

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        facts = vertex_facts(vpath, 0.0, 9999.0)
        assert facts == []
