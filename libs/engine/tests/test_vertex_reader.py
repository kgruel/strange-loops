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

    def test_collect_1_fold(self, tmp_path):
        """FoldCollect with max=1 keeps the latest full payload."""
        from engine import vertex_read

        vpath = _create_vertex_file(tmp_path, "test", '  handoff { fold { items "collect" 1 } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "handoff", "ts": 1000.0, "payload": {"message": "first session"}},
            {"kind": "handoff", "ts": 5000.0, "payload": {"message": "second session"}},
        ])

        result = vertex_read(vpath)
        items = result["handoff"]["items"]
        assert len(items) == 1
        assert items[0]["message"] == "second session"

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
  handoff  { fold { items "collect" 1 } }
""")
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "handoff", "ts": 2000.0, "payload": {"context": "finishing auth"}},
        ])

        result = vertex_read(vpath)

        # All 5 kinds present in result
        assert set(result.keys()) == {"decision", "thread", "change", "task", "handoff"}

        # Handoff surfaced automatically — no reader code knows about it
        assert len(result["handoff"]["items"]) == 1
        assert result["handoff"]["items"][0]["context"] == "finishing auth"

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


def _create_search_vertex(tmp_path: Path, name: str, loops_kdl: str) -> Path:
    """Write a .vertex file with search declarations."""
    content = f'name "{name}"\nstore "./store.db"\n\nloops {{\n{loops_kdl}\n}}\n'
    vpath = tmp_path / f"{name}.vertex"
    vpath.write_text(content)
    return vpath


class TestVertexSearch:
    """vertex_search: FTS5 full-text search through the vertex interface."""

    def test_basic_search(self, tmp_path):
        """Finds facts by keyword in declared search fields."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path,
            "test",
            '  exchange {\n    fold { items "by" "conversation_id" }\n    search "prompt" "response"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "exchange", "ts": 1000.0, "payload": {
                "conversation_id": "c1", "prompt": "explain quantum computing", "response": "Quantum computing uses qubits",
            }},
            {"kind": "exchange", "ts": 2000.0, "payload": {
                "conversation_id": "c2", "prompt": "what is python", "response": "Python is a programming language",
            }},
        ])

        results = vertex_search(vpath, "quantum")
        assert len(results) == 1
        assert results[0]["payload"]["prompt"] == "explain quantum computing"

    def test_word_boundary(self, tmp_path):
        """FTS5 tokenization means 'test' doesn't match 'greatest'."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "this is a test"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "the greatest achievement"}},
        ])

        results = vertex_search(vpath, "test")
        assert len(results) == 1
        assert results[0]["payload"]["text"] == "this is a test"

    def test_kind_filter(self, tmp_path):
        """Kind parameter narrows search to specific kinds."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path,
            "test",
            '  decision {\n    fold { items "by" "topic" }\n    search "summary"\n  }\n'
            '  thread {\n    fold { items "by" "name" }\n    search "notes"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "summary": "use vertex pattern"}},
            {"kind": "thread", "ts": 2000.0, "payload": {"name": "design", "notes": "vertex pattern review"}},
        ])

        results = vertex_search(vpath, "vertex", kind="decision")
        assert len(results) == 1
        assert results[0]["kind"] == "decision"

    def test_time_range(self, tmp_path):
        """Since/until narrows search to time window."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "early note about search"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "middle note about search"}},
            {"kind": "note", "ts": 3000.0, "payload": {"text": "late note about search"}},
        ])

        results = vertex_search(vpath, "search", since=1500.0, until=2500.0)
        assert len(results) == 1
        assert results[0]["ts"].timestamp() == pytest.approx(2000.0, abs=1)

    def test_limit(self, tmp_path):
        """Limit caps result count."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": float(i), "payload": {"text": f"message about loops {i}"}}
            for i in range(1000, 1010)
        ])

        results = vertex_search(vpath, "loops", limit=3)
        assert len(results) == 3

    def test_newest_first(self, tmp_path):
        """Results are ordered newest first."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "first hello"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "second hello"}},
            {"kind": "note", "ts": 3000.0, "payload": {"text": "third hello"}},
        ])

        results = vertex_search(vpath, "hello")
        assert len(results) == 3
        timestamps = [r["ts"].timestamp() for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_empty_query_returns_nothing(self, tmp_path):
        """Empty query returns empty list, not an error."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
        ])

        assert vertex_search(vpath, "") == []
        assert vertex_search(vpath, "   ") == []

    def test_no_store_returns_empty(self, tmp_path):
        """Vertex without store file → empty list."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        # Don't create store.db

        assert vertex_search(vpath, "hello") == []

    def test_no_store_declared_returns_empty(self, tmp_path):
        """Vertex with no store declaration → empty list."""
        from engine import vertex_search

        content = 'name "nostored"\nloops {\n  note {\n    search "text"\n  }\n}\n'
        vpath = tmp_path / "nostored.vertex"
        vpath.write_text(content)

        assert vertex_search(vpath, "hello") == []

    def test_no_search_declarations_returns_empty(self, tmp_path):
        """Vertex with no search declarations → nothing indexed, empty results."""
        from engine import vertex_search

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "summary": "use JWT"}},
        ])

        assert vertex_search(vpath, "JWT") == []

    def test_undeclared_field_not_matched(self, tmp_path):
        """Only declared search fields are indexed — other fields ignored."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  exchange {\n    fold { items "by" "id" }\n    search "prompt"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "exchange", "ts": 1000.0, "payload": {
                "id": "1", "prompt": "hello world", "response": "greetings",
            }},
        ])

        # "hello" is in the indexed prompt field
        assert len(vertex_search(vpath, "hello")) == 1
        # "greetings" is only in the non-indexed response field
        assert len(vertex_search(vpath, "greetings")) == 0

    def test_kind_without_search_skipped(self, tmp_path):
        """Facts of kinds without search declarations are not indexed."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  note {\n    search "text"\n  }\n'
            '  counter {\n    fold { count "inc" }\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
            {"kind": "counter", "ts": 2000.0, "payload": {"value": 42, "label": "hello"}},
        ])

        results = vertex_search(vpath, "hello")
        assert len(results) == 1
        assert results[0]["kind"] == "note"

    def test_incremental_catchup(self, tmp_path):
        """New facts added after first search are indexed on subsequent search."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"

        _seed_facts(db_path, [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "first message"}},
        ])

        # First search — builds FTS index
        results = vertex_search(vpath, "first")
        assert len(results) == 1

        # Add more facts directly to the store
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?)",
            ("note", 2000.0, "test", "", json.dumps({"text": "second message"})),
        )
        conn.commit()
        conn.close()

        # Second search — catches up on new facts
        results = vertex_search(vpath, "second")
        assert len(results) == 1
        assert results[0]["payload"]["text"] == "second message"

    def test_phrase_search(self, tmp_path):
        """FTS5 phrase search with double quotes."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "the quick brown fox"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "quick and brown separately"}},
        ])

        # Phrase match — only the exact sequence
        results = vertex_search(vpath, '"quick brown"')
        assert len(results) == 1
        assert results[0]["payload"]["text"] == "the quick brown fox"

    def test_search_without_fold(self, tmp_path):
        """A kind with search but no fold is valid and searchable."""
        from engine import vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  ambient.text {\n    search "text" "source"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "ambient.text", "ts": 1000.0, "payload": {"text": "hello world", "source": "terminal"}},
        ])

        results = vertex_search(vpath, "hello")
        assert len(results) == 1

    def test_result_shape_matches_vertex_facts(self, tmp_path):
        """Search results have the same dict shape as vertex_facts."""
        from engine import vertex_facts, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])

        search_result = vertex_search(vpath, "hello")[0]
        facts_result = vertex_facts(vpath, 0.0, 9999.0)[0]

        # Same keys
        assert set(search_result.keys()) == set(facts_result.keys())
        # Same types
        assert type(search_result["ts"]) is type(facts_result["ts"])
        assert type(search_result["payload"]) is type(facts_result["payload"])
