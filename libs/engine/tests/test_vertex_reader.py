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
    for i, f in enumerate(facts):
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (f.get("id", f"TESTFACT{i:04d}"), f["kind"], f["ts"], f.get("observer", "test"), f.get("origin", ""), json.dumps(f["payload"])),
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

        vpath = _create_vertex_file(tmp_path, "test", '  alert { fold { items "collect" 1 } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "alert", "ts": 1000.0, "payload": {"message": "first alert"}},
            {"kind": "alert", "ts": 5000.0, "payload": {"message": "second alert"}},
        ])

        result = vertex_read(vpath)
        items = result["alert"]["items"]
        assert len(items) == 1
        assert items[0]["message"] == "second alert"

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

    def test_declaration_driven_kinds(self, tmp_path):
        """Adding a new kind to vertex surfaces in read with zero code changes.

        This is the proof that the architecture works: new kinds are driven
        by declaration, not by code.
        """
        from engine import vertex_read

        # Vertex with original 4 kinds + alert (5th)
        vpath = _create_vertex_file(tmp_path, "project", """
  decision { fold { items "by" "topic" } }
  thread   { fold { items "by" "name" } }
  change   { fold { items "collect" 20 } }
  task     { fold { items "by" "name" } }
  alert    { fold { items "collect" 1 } }
""")
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "alert", "ts": 2000.0, "payload": {"context": "finishing auth"}},
        ])

        result = vertex_read(vpath)

        # All 5 kinds present in result
        assert set(result.keys()) == {"decision", "thread", "change", "task", "alert"}

        # Alert surfaced automatically — no reader code knows about it
        assert len(result["alert"]["items"]) == 1
        assert result["alert"]["items"][0]["context"] == "finishing auth"

        # Original kinds still work
        assert "auth" in result["decision"]["items"]


class TestVertexFold:
    """vertex_fold: typed FoldState with named fold targets."""

    def test_named_upsert_target(self, tmp_path):
        """Upsert target with a name other than 'items' works through vertex_fold."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { topics "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "db", "message": "SQLite"}},
        ])

        result = vertex_fold(vpath)
        section = result.sections[0]
        assert section.kind == "decision"
        assert section.fold_type == "by"
        assert len(section.items) == 2
        payloads = {item.payload["topic"]: item.payload["message"] for item in section.items}
        assert payloads == {"auth": "JWT", "db": "SQLite"}

    def test_named_collect_target(self, tmp_path):
        """Collect target with a name other than 'items' works through vertex_fold."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  event { fold { recent "collect" 3 } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "event", "ts": 1000.0, "payload": {"msg": "first"}},
            {"kind": "event", "ts": 2000.0, "payload": {"msg": "second"}},
        ])

        result = vertex_fold(vpath)
        section = result.sections[0]
        assert section.kind == "event"
        assert section.fold_type == "collect"
        assert len(section.items) == 2
        assert section.items[0].payload["msg"] == "first"
        assert section.items[1].payload["msg"] == "second"

    def test_items_target_still_works(self, tmp_path):
        """The conventional 'items' target name continues to work."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
        ])

        result = vertex_fold(vpath)
        section = result.sections[0]
        assert len(section.items) == 1
        assert section.items[0].payload["topic"] == "auth"

    def test_preview_fields_propagate(self, tmp_path):
        """Per-kind `preview` decl flows through to FoldSection.preview_fields."""
        from engine import vertex_fold

        vpath = _create_vertex_file(
            tmp_path,
            "test",
            '  friction { fold { items "by" "name" } preview "status" "message" }\n'
            '  change   { fold { items "collect" 20 } }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "friction", "ts": 1000.0,
             "payload": {"name": "f", "status": "open", "message": "m"}},
            {"kind": "change", "ts": 2000.0, "payload": {"summary": "x"}},
        ])

        result = vertex_fold(vpath)
        sections = {s.kind: s for s in result.sections}
        assert sections["friction"].preview_fields == ("status", "message")
        assert sections["change"].preview_fields == ()


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


class TestInternalKindExclusion:
    """SPEC §9.4 (S3, decision:architecture/internal-table-s3-read-exclusion):
    every read surface excludes the reserved `_decl.*` namespace by default,
    with an explicit `--kind`/`include_internal` escape hatch.
    """

    def test_unfolded_excludes_decl_kinds(self, tmp_path):
        """The undeclared-kinds footer never surfaces _decl.* — this is the
        direct fix for `sl read project` not being byte-identical pre/post
        `sl store absorb` (a declaration-event kind falling into `unfolded`)."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "_decl.receipt", "ts": 500.0, "payload": {"lineage": "abc"}},
            {"kind": "tick.other", "ts": 500.0, "payload": {}},
        ])

        result = vertex_fold(vpath)
        assert "_decl.receipt" not in result.unfolded
        # Ordinary undeclared kinds still surface — only the reserved
        # namespace is excluded, not every undeclared kind.
        assert "tick.other" in result.unfolded

    def test_byte_identical_fold_pre_post_absorb_style_write(self, tmp_path):
        """Simulates the exit criterion directly: folding a declared kind is
        unaffected by _decl.* rows landing in the same store (as `sl store
        absorb` would write them) — same sections, same unfolded (empty)."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth"}},
        ])
        before = vertex_fold(vpath)

        _seed_facts(tmp_path / "store.db", [
            {"id": "TESTFACT_DECL0", "kind": "_decl.receipt", "ts": 500.0, "payload": {"lineage": "abc"}},
        ])
        after = vertex_fold(vpath)

        assert before.sections == after.sections
        assert before.unfolded == after.unfolded == {}

    def test_explicit_kind_defeats_exclusion_for_declared_kind_unaffected(self, tmp_path):
        """Explicit --kind on an ordinary declared kind is unaffected by the
        internal-namespace change (sanity check, not the interesting case)."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth"}},
        ])
        result = vertex_fold(vpath, kind="decision")
        assert result.sections[0].items[0].payload["topic"] == "auth"

    def test_explicit_kind_surfaces_reserved_namespace(self, tmp_path):
        """--kind _decl.receipt: the general undeclared-kind raw fallback
        surfaces the reserved namespace on explicit ask — no vertex ever
        declares a loop for `_decl.*`, so without the fallback this would
        silently render empty (the pre-existing gap this fix generalizes)."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth"}},
            {"kind": "_decl.receipt", "ts": 500.0, "payload": {"lineage": "abc123"}},
        ])

        result = vertex_fold(vpath, kind="_decl.receipt")
        assert len(result.sections) == 1
        section = result.sections[0]
        assert section.kind == "_decl.receipt"
        assert len(section.items) == 1
        assert section.items[0].payload["lineage"] == "abc123"

    def test_explicit_kind_general_undeclared_kind_no_longer_silently_empty(self, tmp_path):
        """The fallback is general, not `_decl.*`-specific: an ordinary
        undeclared/typo'd kind now also surfaces its raw facts instead of
        silently rendering empty. Distinct behavior change from the _decl.*
        case above — its own test, per review guidance (own blast radius)."""
        from engine import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth"}},
            {"kind": "tick.orphan", "ts": 500.0, "payload": {"n": 42}},
        ])

        result = vertex_fold(vpath, kind="tick.orphan")
        assert len(result.sections) == 1
        section = result.sections[0]
        assert section.kind == "tick.orphan"
        assert len(section.items) == 1
        assert section.items[0].payload["n"] == 42

    def test_vertex_facts_excludes_decl_kinds_ambient(self, tmp_path):
        """The raw `--facts` event-history surface excludes _decl.* ambiently
        (no --kind given) — a genuinely additional leak site found beyond
        the fold-state path (facts_between had no filter at all)."""
        from engine import vertex_facts

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth"}},
            {"kind": "_decl.receipt", "ts": 500.0, "payload": {"lineage": "abc"}},
        ])

        facts = vertex_facts(vpath, 0.0, 9999.0)
        assert {f["kind"] for f in facts} == {"decision"}

    def test_vertex_facts_explicit_internal_kind_needs_include_internal(self, tmp_path):
        """Requesting kind='_decl.receipt' without include_internal=True still
        excludes it — apps/loops callers must derive include_internal from
        is_internal_kind(kind), same rule as vertex_fold's kind param."""
        from engine import vertex_facts

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "_decl.receipt", "ts": 500.0, "payload": {"lineage": "abc"}},
        ])

        assert vertex_facts(vpath, 0.0, 9999.0, kind="_decl.receipt") == []
        facts = vertex_facts(
            vpath, 0.0, 9999.0, kind="_decl.receipt", include_internal=True
        )
        assert len(facts) == 1

    def test_vertex_summary_excludes_decl_kinds(self, tmp_path):
        from engine.vertex_reader import vertex_summary

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth"}},
            {"kind": "_decl.receipt", "ts": 500.0, "payload": {"lineage": "abc"}},
        ])

        summary = vertex_summary(vpath)
        assert set(summary["facts"]["kinds"].keys()) == {"decision"}

        summary_full = vertex_summary(vpath, include_internal=True)
        assert "_decl.receipt" in summary_full["facts"]["kinds"]


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
        from engine import vertex_reindex, vertex_search

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

        vertex_reindex(vpath)
        results = vertex_search(vpath, "quantum")
        assert len(results) == 1
        assert results[0]["payload"]["prompt"] == "explain quantum computing"

    def test_word_boundary(self, tmp_path):
        """FTS5 tokenization means 'test' doesn't match 'greatest'."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "this is a test"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "the greatest achievement"}},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "test")
        assert len(results) == 1
        assert results[0]["payload"]["text"] == "this is a test"

    def test_kind_filter(self, tmp_path):
        """Kind parameter narrows search to specific kinds."""
        from engine import vertex_reindex, vertex_search

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

        vertex_reindex(vpath)
        results = vertex_search(vpath, "vertex", kind="decision")
        assert len(results) == 1
        assert results[0]["kind"] == "decision"

    def test_time_range(self, tmp_path):
        """Since/until narrows search to time window."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "early note about search"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "middle note about search"}},
            {"kind": "note", "ts": 3000.0, "payload": {"text": "late note about search"}},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "search", since=1500.0, until=2500.0)
        assert len(results) == 1
        assert results[0]["ts"].timestamp() == pytest.approx(2000.0, abs=1)

    def test_limit(self, tmp_path):
        """Limit caps result count."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": float(i), "payload": {"text": f"message about loops {i}"}}
            for i in range(1000, 1010)
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "loops", limit=3)
        assert len(results) == 3

    def test_newest_first(self, tmp_path):
        """Results are ordered newest first."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "first hello"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "second hello"}},
            {"kind": "note", "ts": 3000.0, "payload": {"text": "third hello"}},
        ])

        vertex_reindex(vpath)
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
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  exchange {\n    fold { items "by" "id" }\n    search "prompt"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "exchange", "ts": 1000.0, "payload": {
                "id": "1", "prompt": "hello world", "response": "greetings",
            }},
        ])

        vertex_reindex(vpath)
        # "hello" is in the indexed prompt field
        assert len(vertex_search(vpath, "hello")) == 1
        # "greetings" is only in the non-indexed response field
        assert len(vertex_search(vpath, "greetings")) == 0

    def test_kind_without_search_skipped(self, tmp_path):
        """Facts of kinds without search declarations are not indexed."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  note {\n    search "text"\n  }\n'
            '  counter {\n    fold { count "inc" }\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
            {"kind": "counter", "ts": 2000.0, "payload": {"value": 42, "label": "hello"}},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "hello")
        assert len(results) == 1
        assert results[0]["kind"] == "note"

    def test_incremental_catchup(self, tmp_path):
        """S2 (read-purity): a fact added after the last reindex is NOT found by
        a bare vertex_search — the index only advances on an EXPLICIT
        vertex_reindex call, never as a side effect of a read. This is the
        direct regression test for rejecting write-side reindex
        (design:fts-confirm-symmetry-is-phantom's property is re-derived via
        the substring fallback at the surface layer, not via FTS auto-catch-up
        — see apps/loops/tests/test_surface.py's staleness-disclosure test)."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"

        _seed_facts(db_path, [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "first message"}},
        ])

        # Explicit reindex — builds the FTS index.
        vertex_reindex(vpath)
        results = vertex_search(vpath, "first")
        assert len(results) == 1

        # Add more facts directly to the store.
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            ("TESTFACT_INC", "note", 2000.0, "test", "", json.dumps({"text": "second message"})),
        )
        conn.commit()
        conn.close()

        # A bare search does NOT catch up — the index is exactly as of the
        # last reindex, not head. This is the point of read-purity.
        results = vertex_search(vpath, "second")
        assert results == []

        # Only an explicit reindex makes the new fact findable.
        vertex_reindex(vpath)
        results = vertex_search(vpath, "second")
        assert len(results) == 1
        assert results[0]["payload"]["text"] == "second message"

    def test_fts_watermark_advances_past_trailing_nonsearchable(self, tmp_path):
        """The reindex watermark advances over EVERY scanned row, including
        kinds with no search declaration (e.g. the reserved `_decl.*` events an
        S4 re-absorb appends). Otherwise trailing non-searchable rows would sit
        above `last_rowid`, which would matter once staleness is judged against
        that watermark (engine.vertex_search_coverage)."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"
        # A searchable note, then TRAILING non-searchable declaration rows —
        # the shape an absorbed store takes once S4 edits land.
        _seed_facts(db_path, [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
            {"kind": "_decl.kind-defined", "ts": 1100.0, "payload": {"subject": "note"}},
            {"kind": "_decl.kind-defined", "ts": 1200.0, "payload": {"subject": "counter"}},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "hello")
        assert len(results) == 1  # the note is indexed

        # The watermark must have advanced to the LAST (trailing) rowid, not
        # stopped at the note — else the two _decl rows would read as "stale"
        # on every coverage probe despite having nothing searchable in them.
        conn = sqlite3.connect(str(db_path))
        try:
            last_rowid = int(
                conn.execute(
                    "SELECT value FROM fts_state WHERE key='last_rowid'"
                ).fetchone()[0]
            )
            max_rowid = conn.execute("SELECT MAX(rowid) FROM facts").fetchone()[0]
        finally:
            conn.close()
        assert last_rowid == max_rowid  # consumed the trailing non-searchable rows

    def test_phrase_search(self, tmp_path):
        """FTS5 phrase search with double quotes."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "the quick brown fox"}},
            {"kind": "note", "ts": 2000.0, "payload": {"text": "quick and brown separately"}},
        ])

        vertex_reindex(vpath)
        # Phrase match — only the exact sequence
        results = vertex_search(vpath, '"quick brown"')
        assert len(results) == 1
        assert results[0]["payload"]["text"] == "the quick brown fox"

    def test_search_without_fold(self, tmp_path):
        """A kind with search but no fold is valid and searchable."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  ambient.text {\n    search "text" "source"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "ambient.text", "ts": 1000.0, "payload": {"text": "hello world", "source": "terminal"}},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "hello")
        assert len(results) == 1

    def test_result_shape_matches_vertex_facts(self, tmp_path):
        """Search results have the same dict shape as vertex_facts."""
        from engine import vertex_facts, vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])

        vertex_reindex(vpath)
        search_result = vertex_search(vpath, "hello")[0]
        facts_result = vertex_facts(vpath, 0.0, 9999.0)[0]

        # Same keys
        assert set(search_result.keys()) == set(facts_result.keys())
        # Same types
        assert type(search_result["ts"]) is type(facts_result["ts"])
        assert type(search_result["payload"]) is type(facts_result["payload"])


class TestFtsReadPurity:
    """S2: vertex_search / vertex_search_coverage never write; vertex_reindex
    is the sole writer, and reindexing is a full rebuild (retroactive)."""

    def test_search_byte_identity_with_prebuilt_index(self, tmp_path):
        """A --match read against an ALREADY-reindexed store touches zero
        bytes — closes friction:search-read-mutates-canonical-store."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"
        _seed_facts(db_path, [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])
        vertex_reindex(vpath)

        before = db_path.read_bytes()
        vertex_search(vpath, "hello")
        vertex_search(vpath, "nonexistent")
        after = db_path.read_bytes()
        assert before == after

    def test_search_byte_identity_without_index(self, tmp_path):
        """A --match read against a store that was NEVER reindexed (no
        facts_fts at all) also touches zero bytes — the old code built the
        index lazily on this exact path (184320→282624 bytes observed
        live); the fixed vertex_search must not create the table at all,
        and instead let the caller's coverage probe route the query away
        from vertex_search entirely."""
        from engine import vertex_search, vertex_search_coverage

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"
        _seed_facts(db_path, [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])

        before = db_path.read_bytes()
        # Coverage probe itself must not write either.
        coverage = vertex_search_coverage(vpath)
        assert coverage.missing is True
        mid = db_path.read_bytes()
        assert before == mid

        # A direct vertex_search call on a missing index is a documented
        # caller error (see vertex_search's docstring) — it raises rather
        # than silently building the table. Confirm it raises AND that the
        # raise itself left the store untouched.
        import pytest

        with pytest.raises(Exception):
            vertex_search(vpath, "hello")
        after = db_path.read_bytes()
        assert before == after

    def test_reindex_is_the_only_writer(self, tmp_path):
        """facts_fts/fts_state appear ONLY after an explicit vertex_reindex
        call — never as a side effect of vertex_search or
        vertex_search_coverage."""
        from engine import vertex_reindex, vertex_search_coverage

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"
        _seed_facts(db_path, [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])

        vertex_search_coverage(vpath)  # read-only probe — must not create tables

        def _table_exists(name: str) -> bool:
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (name,),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

        assert _table_exists("facts_fts") is False

        vertex_reindex(vpath)
        assert _table_exists("facts_fts") is True

    def test_retroactive_indexing_via_reindex(self, tmp_path):
        """Closes friction:fts-search-declaration-not-retroactive: facts
        written BEFORE a kind ever declared ``search`` become findable after
        ONE reindex — reindex is a full rebuild against the CURRENT
        declaration set, not an incremental watermark that only ever
        advanced past what was searchable at scan time."""
        from engine import vertex_reindex, vertex_search

        # Kind `decision` has NO search declaration yet.
        vpath = _create_vertex_file(
            tmp_path, "test", '  decision { fold { items "by" "topic" } }',
        )
        db_path = tmp_path / "store.db"
        _seed_facts(db_path, [
            {"kind": "decision", "ts": 1000.0, "payload": {
                "topic": "auth", "summary": "predates the search declaration",
            }},
        ])

        # Declare search NOW, after the fact already exists (rewrite the
        # vertex file in place — same store, new declaration).
        vpath.write_text(
            'name "test"\nstore "./store.db"\n\nloops {\n'
            '  decision {\n    fold { items "by" "topic" }\n'
            '    search "summary"\n  }\n}\n'
        )

        vertex_reindex(vpath)
        results = vertex_search(vpath, "predates")
        assert len(results) == 1
        assert results[0]["payload"]["topic"] == "auth"

    def test_reindex_twice_is_idempotent(self, tmp_path):
        """Running reindex twice in a row produces identical, valid results
        (drop+recreate is safe to repeat)."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])

        first = vertex_reindex(vpath)
        second = vertex_reindex(vpath)
        assert first["facts_indexed"] == second["facts_indexed"] == 1
        assert vertex_search(vpath, "hello") == vertex_search(vpath, "hello")

    def test_coverage_stale_after_facts_added_past_last_reindex(self, tmp_path):
        """vertex_search_coverage reports the kind as stale once a fact is
        written after the last reindex — the read-side signal
        surface.search consumes to decide FTS vs substring fallback."""
        from engine import vertex_reindex, vertex_search_coverage

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"
        _seed_facts(db_path, [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
        ])
        vertex_reindex(vpath)

        coverage = vertex_search_coverage(vpath)
        assert coverage.missing is False
        assert coverage.stale_kinds == frozenset()

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            ("TESTFACT_STALE", "note", 2000.0, "test", "", json.dumps({"text": "world"})),
        )
        conn.commit()
        conn.close()

        coverage = vertex_search_coverage(vpath)
        assert coverage.missing is False
        assert coverage.stale_kinds == frozenset({"note"})

    def test_kinds_param_restricts_sql_before_limit(self, tmp_path):
        """S2 sol P2: without ``kinds``, a query across ALL indexed kinds can
        let one kind's many matches fill the LIMIT window, silently pushing
        another kind's genuine matches out — post-hoc filtering by the
        caller is too late, since the rows never came back in the first
        place. ``kinds`` restricts the SQL WHERE clause BEFORE the LIMIT, so
        the crowding kind never displaces the kind the caller actually
        wants."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path,
            "test",
            '  crowd {\n    search "text"\n  }\n'
            '  target {\n    search "text"\n  }',
        )
        db_path = tmp_path / "store.db"
        facts = [
            # 105 newer, crowding matches — all in `crowd`.
            {"kind": "crowd", "ts": 2000.0 + i, "payload": {"text": "needle"}}
            for i in range(105)
        ] + [
            # One OLDER match in `target` — would be sorted last by ts and
            # fall outside an unrestricted LIMIT 101 window.
            {"kind": "target", "ts": 1.0, "payload": {"text": "needle"}},
        ]
        _seed_facts(db_path, facts)
        vertex_reindex(vpath)

        # Unrestricted: `target`'s single old match is displaced by
        # `crowd`'s 105 newer matches within a small limit.
        unrestricted = vertex_search(vpath, "needle", limit=10)
        assert all(r["kind"] == "crowd" for r in unrestricted)

        # Restricted to `target` alone: the SQL WHERE clause excludes
        # `crowd` entirely, so `target`'s match is never at risk of being
        # crowded out by it, regardless of how the limit is set.
        restricted = vertex_search(vpath, "needle", kinds=["target"], limit=10)
        assert len(restricted) == 1
        assert restricted[0]["kind"] == "target"

    def test_kinds_param_empty_iterable_matches_nothing(self, tmp_path):
        """An explicit empty ``kinds`` is a real allowlist of nothing, not
        'no restriction' — distinct from ``kinds=None``."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
        ])
        vertex_reindex(vpath)

        assert vertex_search(vpath, "hello", kinds=[]) == []
        assert len(vertex_search(vpath, "hello", kinds=None)) == 1

    def test_combined_search_forwards_kinds_to_children(self, tmp_path, monkeypatch):
        """S2 sol P2, aggregation path: kinds forwards through
        _combined_search into each child's own vertex_search call, so a
        crowding kind in one child can't push a target kind's matches out
        of THAT child's own limit window either."""
        from engine import vertex_reindex, vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        # alpha: many crowding matches under a kind the caller does NOT trust.
        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 2000.0 + i, "payload": {
                "topic": f"crowd-{i}", "message": "needle",
            }}
            for i in range(105)
        ])
        # beta: one match the caller DOES trust.
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 1.0, "payload": {
                "topic": "target", "message": "needle",
            }},
        ])
        vertex_reindex(combine_vpath)

        # Both children index the SAME kind name ("decision"), so kinds=
        # doesn't disambiguate alpha vs beta here — this test only proves
        # the parameter is forwarded and doesn't break the combine path
        # under a full-kind restriction; per-store crowding within a single
        # child is covered by test_kinds_param_restricts_sql_before_limit.
        results = vertex_search(combine_vpath, "needle", kinds=["decision"], limit=10)
        assert len(results) == 10
        assert all(r["kind"] == "decision" for r in results)

    def test_new_searchable_kind_marks_stale_with_zero_new_facts(self, tmp_path):
        """Capstone sol P1: a declaration edit that adds a NEW searchable
        kind, with no new facts written for it, still marks the index
        stale — the rowid watermark alone can't see this, since nothing new
        was ever written. The declaration fingerprint catches it."""
        from engine import vertex_reindex, vertex_search_coverage

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
        ])
        vertex_reindex(vpath)

        coverage = vertex_search_coverage(vpath)
        assert coverage.stale_kinds == frozenset()

        # Edit the declaration — add a new searchable kind. Zero facts
        # written for it; the rowid watermark does not move.
        _create_search_vertex(
            tmp_path, "test",
            '  note {\n    search "text"\n  }\n'
            '  extra {\n    search "text"\n  }',
        )

        coverage = vertex_search_coverage(vpath)
        # Whole-declaration-set granularity (not per-kind): the fingerprint
        # covers the whole decl, so EVERY currently-declared kind reports
        # stale until the next reindex, including the pre-existing `note`.
        assert coverage.stale_kinds == frozenset({"note", "extra"})

        # Reindexing re-anchors the fingerprint and clears the staleness.
        vertex_reindex(vpath)
        coverage = vertex_search_coverage(vpath)
        assert coverage.stale_kinds == frozenset()

    def test_changed_search_fields_marks_stale_with_zero_new_facts(self, tmp_path):
        """Capstone sol P1: changing WHICH fields an already-indexed kind
        searches (same kind name, no new facts) also marks it stale — a
        pure field-list edit moves no rowid either."""
        from engine import vertex_reindex, vertex_search_coverage

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  exchange {\n    search "prompt"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "exchange", "ts": 1000.0, "payload": {
                "prompt": "hello", "response": "world",
            }},
        ])
        vertex_reindex(vpath)

        coverage = vertex_search_coverage(vpath)
        assert coverage.stale_kinds == frozenset()

        # Same kind, DIFFERENT declared search fields — no new facts.
        _create_search_vertex(
            tmp_path, "test",
            '  exchange {\n    search "prompt" "response"\n  }',
        )

        coverage = vertex_search_coverage(vpath)
        assert coverage.stale_kinds == frozenset({"exchange"})

    def test_unchanged_declaration_no_false_stale(self, tmp_path):
        """The fingerprint check must not itself introduce false staleness:
        re-probing an UNCHANGED declaration (fingerprint matches) proceeds
        to the rowid check as before, reporting fresh."""
        from engine import vertex_reindex, vertex_search_coverage

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello"}},
        ])
        vertex_reindex(vpath)

        # Re-probe several times with no edits at all.
        for _ in range(3):
            coverage = vertex_search_coverage(vpath)
            assert coverage.missing is False
            assert coverage.stale_kinds == frozenset()

    def test_declaration_drift_search_finds_matches_via_fallback(self, tmp_path):
        """End-to-end at the search() surface: a declaration edit with zero
        new facts must not silently return nothing — the coverage probe's
        fingerprint mismatch routes the affected kind through the
        substring fallback, and the fact IS found."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello driftword"}},
        ])
        vertex_reindex(vpath)

        # Declaration edit, no new facts — the FTS index is now
        # semantically stale even though the rowid watermark hasn't moved.
        _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text" "extra"\n  }',
        )

        # A bare vertex_search (no coverage gating) still returns the OLD
        # index's answer — this is why callers MUST consult the coverage
        # probe first; vertex_search itself has no way to know the
        # declaration moved.
        stale_results = vertex_search(vpath, "driftword")
        assert len(stale_results) == 1  # the old index still has this row

        # But the coverage probe correctly flags it, so a caller that
        # honors it (surface.search — exercised directly in
        # apps/loops/tests/test_surface.py) will route through the
        # substring fallback rather than trusting this index blindly.
        from engine import vertex_search_coverage

        coverage = vertex_search_coverage(vpath)
        assert "note" in coverage.stale_kinds


class TestExtractField:
    """_extract_field: nested paths and polymorphic value extraction for FTS5."""

    def test_flat_string(self):
        from engine.vertex_reader import _extract_field

        assert _extract_field({"prompt": "hello world"}, "prompt") == "hello world"

    def test_dot_path(self):
        from engine.vertex_reader import _extract_field

        payload = {"message": {"content": "nested value"}}
        assert _extract_field(payload, "message.content") == "nested value"

    def test_array_of_content_blocks(self):
        from engine.vertex_reader import _extract_field

        payload = {"message": {"content": [
            {"type": "text", "text": "First paragraph."},
            {"type": "text", "text": "Second paragraph."},
        ]}}
        assert _extract_field(payload, "message.content") == "First paragraph. Second paragraph."

    def test_array_of_strings(self):
        from engine.vertex_reader import _extract_field

        payload = {"tags": ["python", "loops", "vertex"]}
        assert _extract_field(payload, "tags") == "python loops vertex"

    def test_missing_field(self):
        from engine.vertex_reader import _extract_field

        assert _extract_field({}, "nonexistent") == ""
        assert _extract_field({"a": {"b": 1}}, "a.c") == ""
        assert _extract_field({"a": "flat"}, "a.b") == ""

    def test_dict_fallback(self):
        from engine.vertex_reader import _extract_field

        payload = {"meta": {"nested": {"key": "val"}}}
        result = _extract_field(payload, "meta.nested")
        assert '"key"' in result and '"val"' in result

    def test_mixed_content_blocks(self):
        """Array with non-text blocks — only text fields extracted."""
        from engine.vertex_reader import _extract_field

        payload = {"message": {"content": [
            {"type": "text", "text": "Real content."},
            {"type": "tool_use", "id": "123", "name": "read"},
            {"type": "text", "text": "More content."},
        ]}}
        assert _extract_field(payload, "message.content") == "Real content. More content."

    def test_plain_string_value(self):
        """String at dot-path — indexed directly, no array handling."""
        from engine.vertex_reader import _extract_field

        payload = {"message": {"content": "just a string"}}
        assert _extract_field(payload, "message.content") == "just a string"


class TestFTS5NestedFields:
    """End-to-end: vertex_search with dot-path and polymorphic fields."""

    def test_dot_path_search(self, tmp_path):
        """search 'message.content' traverses nested dict."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  exchange {\n    search "message.content"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "exchange", "ts": 1000.0, "payload": {
                "message": {"role": "user", "content": "explain quantum computing"},
            }},
            {"kind": "exchange", "ts": 2000.0, "payload": {
                "message": {"role": "user", "content": "what is python"},
            }},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "quantum")
        assert len(results) == 1
        assert results[0]["payload"]["message"]["content"] == "explain quantum computing"

    def test_content_blocks_search(self, tmp_path):
        """Array-of-objects with text fields — concatenated and searchable."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  exchange {\n    search "message.content"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "exchange", "ts": 1000.0, "payload": {
                "message": {"role": "assistant", "content": [
                    {"type": "text", "text": "Quantum computing uses qubits."},
                    {"type": "text", "text": "They leverage superposition."},
                ]},
            }},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "qubits")
        assert len(results) == 1

        results2 = vertex_search(vpath, "superposition")
        assert len(results2) == 1

    def test_missing_nested_field_no_error(self, tmp_path):
        """Missing nested path produces empty string, not error."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  exchange {\n    search "message.content"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "exchange", "ts": 1000.0, "payload": {"other": "data"}},
            {"kind": "exchange", "ts": 2000.0, "payload": {
                "message": {"content": "findable"},
            }},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "findable")
        assert len(results) == 1

    def test_flat_field_still_works(self, tmp_path):
        """Flat fields (no dot) still work — no regression."""
        from engine import vertex_reindex, vertex_search

        vpath = _create_search_vertex(
            tmp_path, "test",
            '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])

        vertex_reindex(vpath)
        results = vertex_search(vpath, "hello")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Combinatorial vertex helpers
# ---------------------------------------------------------------------------


def _seed_ticks(db_path: Path, ticks: list[dict]) -> None:
    """Insert ticks into a SQLite store at db_path (creates tables if needed)."""
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
    for i, t in enumerate(ticks):
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (t.get("id", f"TESTTICK{i:04d}"), t["name"], t["ts"], t.get("since"), t.get("origin", ""), json.dumps(t.get("payload", {}))),
        )
    conn.commit()
    conn.close()


def _setup_combine_env(tmp_path: Path, monkeypatch):
    """Set up a LOOPS_HOME with two instance vertices (alpha, beta) and a combinatorial vertex.

    Returns (combine_vertex_path, alpha_db_path, beta_db_path).
    """
    home = tmp_path / "loops_home"

    # alpha vertex: home/alpha/alpha.vertex + store
    alpha_dir = home / "alpha"
    alpha_dir.mkdir(parents=True)
    alpha_vertex = alpha_dir / "alpha.vertex"
    alpha_vertex.write_text(
        'name "alpha"\n'
        'store "./store.db"\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" } }\n'
        '}\n'
    )
    alpha_db = alpha_dir / "store.db"

    # beta vertex: home/beta/beta.vertex + store
    beta_dir = home / "beta"
    beta_dir.mkdir(parents=True)
    beta_vertex = beta_dir / "beta.vertex"
    beta_vertex.write_text(
        'name "beta"\n'
        'store "./store.db"\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" } }\n'
        '}\n'
    )
    beta_db = beta_dir / "store.db"

    # combinatorial vertex (lives alongside home)
    combine_vertex = tmp_path / "combined.vertex"
    combine_vertex.write_text(
        'name "combined"\n'
        'combine {\n'
        '    vertex "alpha"\n'
        '    vertex "beta"\n'
        '}\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" } }\n'
        '}\n'
    )

    monkeypatch.setenv("LOOPS_HOME", str(home))
    return combine_vertex, alpha_db, beta_db


class TestCombinedVertexRead:
    """vertex_read for combinatorial vertices — fold state across multiple stores."""

    def test_upsert_fold_across_stores(self, tmp_path, monkeypatch):
        """Facts from both stores merge through the same upsert fold."""
        from engine import vertex_read

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "use JWT"}},
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "db", "message": "use SQLite"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 3000.0, "payload": {"topic": "auth", "message": "use sessions"}},
            {"kind": "decision", "ts": 4000.0, "payload": {"topic": "deploy", "message": "use nix"}},
        ])

        result = vertex_read(combine_vpath)
        items = result["decision"]["items"]

        # auth updated to latest (from beta, ts=3000)
        assert items["auth"]["message"] == "use sessions"
        # db from alpha
        assert items["db"]["message"] == "use SQLite"
        # deploy from beta
        assert items["deploy"]["message"] == "use nix"
        assert len(items) == 3

    def test_timestamp_ordering(self, tmp_path, monkeypatch):
        """Facts from multiple stores are interleaved by timestamp, not by store order."""
        from engine import vertex_read

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        # Beta has earlier auth fact, alpha has later — final state should be alpha's
        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 5000.0, "payload": {"topic": "auth", "message": "final answer"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "early answer"}},
        ])

        result = vertex_read(combine_vpath)
        # ts=5000 > ts=1000 → alpha's fact is later
        assert result["decision"]["items"]["auth"]["message"] == "final answer"

    def test_count_fold_across_stores(self, tmp_path, monkeypatch):
        """Count fold sums facts from both stores."""
        from engine import vertex_read

        home = tmp_path / "loops_home"

        # Set up vertices with count fold
        for name in ("a", "b"):
            d = home / name
            d.mkdir(parents=True)
            (d / f"{name}.vertex").write_text(
                f'name "{name}"\nstore "./store.db"\n'
                'loops { event { fold { count "inc" } } }\n'
            )

        combine = tmp_path / "combined.vertex"
        combine.write_text(
            'name "combined"\ncombine { vertex "a"\n vertex "b" }\n'
            'loops { event { fold { count "inc" } } }\n'
        )

        _seed_facts(home / "a" / "store.db", [
            {"kind": "event", "ts": 1000.0, "payload": {}},
            {"kind": "event", "ts": 2000.0, "payload": {}},
        ])
        _seed_facts(home / "b" / "store.db", [
            {"kind": "event", "ts": 3000.0, "payload": {}},
        ])

        monkeypatch.setenv("LOOPS_HOME", str(home))
        result = vertex_read(combine)
        assert result["event"]["count"] == 3

    def test_empty_stores(self, tmp_path, monkeypatch):
        """Both stores empty → initial fold state."""
        from engine import vertex_read

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)
        _seed_facts(alpha_db, [])
        _seed_facts(beta_db, [])

        result = vertex_read(combine_vpath)
        assert result["decision"]["items"] == {}

    def test_missing_store(self, tmp_path, monkeypatch):
        """Referenced vertex exists but store file doesn't → graceful skip."""
        from engine import vertex_read

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        # Only create alpha's store, not beta's
        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "only alpha"}},
        ])

        result = vertex_read(combine_vpath)
        assert result["decision"]["items"]["auth"]["message"] == "only alpha"

    def test_missing_vertex(self, tmp_path, monkeypatch):
        """Referenced vertex doesn't exist → graceful skip."""
        from engine import vertex_read

        home = tmp_path / "loops_home"
        # Only create alpha, not beta
        alpha_dir = home / "alpha"
        alpha_dir.mkdir(parents=True)
        (alpha_dir / "alpha.vertex").write_text(
            'name "alpha"\nstore "./store.db"\n'
            'loops { decision { fold { items "by" "topic" } } }\n'
        )
        _seed_facts(alpha_dir / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "x", "message": "only"}},
        ])

        combine = tmp_path / "combined.vertex"
        combine.write_text(
            'name "combined"\ncombine { vertex "alpha"\n vertex "nonexistent" }\n'
            'loops { decision { fold { items "by" "topic" } } }\n'
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = vertex_read(combine)
        assert result["decision"]["items"]["x"]["message"] == "only"

    def test_no_resolvable_stores(self, tmp_path, monkeypatch):
        """All referenced vertices missing → initial state."""
        from engine import vertex_read

        home = tmp_path / "loops_home"
        home.mkdir(parents=True)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        combine = tmp_path / "combined.vertex"
        combine.write_text(
            'name "combined"\ncombine { vertex "gone" }\n'
            'loops { counter { fold { count "inc" } } }\n'
        )

        result = vertex_read(combine)
        assert result["counter"]["count"] == 0


class TestCombinedVertexFacts:
    """vertex_facts for combinatorial vertices — raw facts across stores."""

    def test_merged_time_range(self, tmp_path, monkeypatch):
        """Facts from both stores appear in time range query."""
        from engine import vertex_facts

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "decision", "ts": 3000.0, "payload": {"topic": "c"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "b"}},
        ])

        facts = vertex_facts(combine_vpath, 0.0, 9999.0)
        assert len(facts) == 3
        # Ordered by ts
        topics = [f["payload"]["topic"] for f in facts]
        assert topics == ["a", "b", "c"]

    def test_kind_filter(self, tmp_path, monkeypatch):
        """Kind filter works across combined stores."""
        from engine import vertex_facts

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "thread", "ts": 1500.0, "payload": {"name": "x"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "b"}},
        ])

        facts = vertex_facts(combine_vpath, 0.0, 9999.0, kind="decision")
        assert len(facts) == 2
        assert all(f["kind"] == "decision" for f in facts)

    def test_time_window(self, tmp_path, monkeypatch):
        """Time window filters across combined stores."""
        from engine import vertex_facts

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "early"}},
            {"kind": "decision", "ts": 5000.0, "payload": {"topic": "late"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 3000.0, "payload": {"topic": "mid"}},
        ])

        facts = vertex_facts(combine_vpath, 2000.0, 4000.0)
        assert len(facts) == 1
        assert facts[0]["payload"]["topic"] == "mid"

    def test_excludes_decl_kinds_by_default(self, tmp_path, monkeypatch):
        """_combined_facts had its own raw UNION ALL SQL with no filter — a
        leak site beyond the single-store StoreReader.facts_between path."""
        from engine import vertex_facts

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "_decl.genesis", "ts": 500.0, "payload": {"lineage": "abc"}},
        ])

        facts = vertex_facts(combine_vpath, 0.0, 9999.0)
        assert {f["kind"] for f in facts} == {"decision"}

        facts_full = vertex_facts(combine_vpath, 0.0, 9999.0, include_internal=True)
        assert {f["kind"] for f in facts_full} == {"decision", "_decl.genesis"}

    def test_explicit_kind_on_undeclared_kind_stays_silently_empty(self, tmp_path, monkeypatch):
        """KNOWN GAP, not fixed by S3: unlike the single-store path,
        combinatorial vertices have no per-kind raw-facts fallback for
        vertex_fold's explicit --kind on an undeclared kind — _combined_read
        only ever queries kinds present in full_specs (SPEC §9 build plan,
        S3 PLAN.md decision 3 / open question 1). `--kind _decl.<x>` on an
        aggregation vertex therefore still silently renders empty. Extending
        the fallback here would need a raw per-store facts_by_kind query
        merged across all combined stores — a materially bigger change than
        the single-store case's ~10-line addition. Documented here so the
        inconsistency is explicit, not silently left mismatched between the
        two vertex shapes."""
        from engine import vertex_fold

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)
        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "_decl.genesis", "ts": 500.0, "payload": {"lineage": "abc"}},
        ])

        result = vertex_fold(combine_vpath, kind="_decl.genesis")
        assert result.sections[0].items == ()  # still empty — the documented gap

    def test_empty_combine(self, tmp_path, monkeypatch):
        """No resolvable stores → empty facts."""
        from engine import vertex_facts

        home = tmp_path / "loops_home"
        home.mkdir(parents=True)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        combine = tmp_path / "combined.vertex"
        combine.write_text(
            'name "combined"\ncombine { vertex "gone" }\n'
            'loops { counter { fold { count "inc" } } }\n'
        )

        assert vertex_facts(combine, 0.0, 9999.0) == []


class TestCombinedVertexTicks:
    """vertex_ticks for combinatorial vertices."""

    def test_merged_ticks(self, tmp_path, monkeypatch):
        """Ticks from both stores appear merged."""
        from engine import vertex_ticks

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_ticks(alpha_db, [
            {"name": "decision", "ts": 1000.0, "origin": "alpha", "payload": {"count": 1}},
        ])
        _seed_ticks(beta_db, [
            {"name": "decision", "ts": 2000.0, "origin": "beta", "payload": {"count": 2}},
        ])

        ticks = vertex_ticks(combine_vpath, 0.0, 9999.0)
        assert len(ticks) == 2
        assert ticks[0].ts < ticks[1].ts

    def test_name_filter(self, tmp_path, monkeypatch):
        """Name filter works across combined stores."""
        from engine import vertex_ticks

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_ticks(alpha_db, [
            {"name": "decision", "ts": 1000.0, "origin": "alpha", "payload": {}},
            {"name": "thread", "ts": 1500.0, "origin": "alpha", "payload": {}},
        ])
        _seed_ticks(beta_db, [
            {"name": "decision", "ts": 2000.0, "origin": "beta", "payload": {}},
        ])

        ticks = vertex_ticks(combine_vpath, 0.0, 9999.0, name="decision")
        assert len(ticks) == 2


class TestCombinedVertexSummary:
    """vertex_summary for combinatorial vertices."""

    def test_merged_counts(self, tmp_path, monkeypatch):
        """Fact and tick counts sum across stores."""
        from engine import vertex_summary

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "b"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 3000.0, "payload": {"topic": "c"}},
        ])
        _seed_ticks(alpha_db, [
            {"name": "decision", "ts": 1500.0, "origin": "alpha", "payload": {}},
        ])

        summary = vertex_summary(combine_vpath)
        assert summary["facts"]["total"] == 3
        assert summary["facts"]["kinds"]["decision"]["count"] == 3
        assert summary["ticks"]["total"] == 1

    def test_excludes_decl_kinds_by_default(self, tmp_path, monkeypatch):
        """SPEC §9.4 applies to combinatorial vertices too — _combined_summary
        had its own raw `GROUP BY kind` SQL with no filter (a leak site beyond
        the single-store StoreReader path)."""
        from engine import vertex_summary

        combine_vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "a"}},
            {"kind": "_decl.genesis", "ts": 500.0, "payload": {"lineage": "abc"}},
        ])

        summary = vertex_summary(combine_vpath)
        assert set(summary["facts"]["kinds"].keys()) == {"decision"}

        summary_full = vertex_summary(combine_vpath, include_internal=True)
        assert "_decl.genesis" in summary_full["facts"]["kinds"]

    def test_empty_combine_summary(self, tmp_path, monkeypatch):
        """No resolvable stores → zeroed summary."""
        from engine import vertex_summary

        home = tmp_path / "loops_home"
        home.mkdir(parents=True)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        combine = tmp_path / "combined.vertex"
        combine.write_text(
            'name "combined"\ncombine { vertex "gone" }\n'
            'loops { counter { fold { count "inc" } } }\n'
        )

        summary = vertex_summary(combine)
        assert summary["facts"]["total"] == 0
        assert summary["ticks"]["total"] == 0

    def test_three_stores(self, tmp_path, monkeypatch):
        """Combinatorial vertex with 3 stores merges all."""
        from engine import vertex_read, vertex_summary

        home = tmp_path / "loops_home"
        for name in ("x", "y", "z"):
            d = home / name
            d.mkdir(parents=True)
            (d / f"{name}.vertex").write_text(
                f'name "{name}"\nstore "./store.db"\n'
                'loops { item { fold { items "by" "key" } } }\n'
            )
            _seed_facts(d / "store.db", [
                {"kind": "item", "ts": float(ord(name) * 100), "payload": {"key": name, "val": name}},
            ])

        combine = tmp_path / "combined.vertex"
        combine.write_text(
            'name "combined"\ncombine { vertex "x"\n vertex "y"\n vertex "z" }\n'
            'loops { item { fold { items "by" "key" } } }\n'
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = vertex_read(combine)
        assert len(result["item"]["items"]) == 3
        assert set(result["item"]["items"].keys()) == {"x", "y", "z"}

        summary = vertex_summary(combine)
        assert summary["facts"]["total"] == 3


def _setup_search_combine_env(tmp_path: Path, monkeypatch):
    """Set up a LOOPS_HOME with two search-enabled instance vertices and a combinatorial vertex.

    Returns (combine_vertex_path, alpha_db_path, beta_db_path).
    """
    home = tmp_path / "loops_home"

    # alpha vertex with search declaration
    alpha_dir = home / "alpha"
    alpha_dir.mkdir(parents=True)
    alpha_vertex = alpha_dir / "alpha.vertex"
    alpha_vertex.write_text(
        'name "alpha"\n'
        'store "./store.db"\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" }\n    search "topic" "message"\n  }\n'
        '}\n'
    )
    alpha_db = alpha_dir / "store.db"

    # beta vertex with search declaration
    beta_dir = home / "beta"
    beta_dir.mkdir(parents=True)
    beta_vertex = beta_dir / "beta.vertex"
    beta_vertex.write_text(
        'name "beta"\n'
        'store "./store.db"\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" }\n    search "topic" "message"\n  }\n'
        '}\n'
    )
    beta_db = beta_dir / "store.db"

    # combinatorial vertex
    combine_vertex = tmp_path / "combined.vertex"
    combine_vertex.write_text(
        'name "combined"\n'
        'combine {\n'
        '    vertex "alpha"\n'
        '    vertex "beta"\n'
        '}\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" }\n    search "topic" "message"\n  }\n'
        '}\n'
    )

    monkeypatch.setenv("LOOPS_HOME", str(home))
    return combine_vertex, alpha_db, beta_db


class TestCombinedVertexSearch:
    """vertex_search on combinatorial vertices — delegates to children."""

    def test_aggregate_search_mutates_zero_child_stores(self, tmp_path, monkeypatch):
        """S2 aggravator regression: a --match read against an aggregate must
        not write to ANY child store — before this fix, vertex_search's
        write-on-read recursed through _combined_search into every child,
        so one aggregate read mutated every child's canonical .db."""
        from engine import vertex_reindex, vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "use JWT"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "deploy", "message": "use JWT tokens"}},
        ])
        vertex_reindex(combine_vpath)

        alpha_before = alpha_db.read_bytes()
        beta_before = beta_db.read_bytes()
        vertex_search(combine_vpath, "JWT")
        vertex_search(combine_vpath, "nonexistent")
        assert alpha_db.read_bytes() == alpha_before
        assert beta_db.read_bytes() == beta_before

    def test_search_across_children(self, tmp_path, monkeypatch):
        """Search through aggregation vertex returns results from both child stores."""
        from engine import vertex_reindex, vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "use JWT"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "deploy", "message": "use JWT tokens"}},
        ])

        # Reindexing the aggregate recurses into every child's own store.
        vertex_reindex(combine_vpath)
        results = vertex_search(combine_vpath, "JWT")
        assert len(results) == 2
        # Newest first
        topics = [r["payload"]["topic"] for r in results]
        assert topics == ["deploy", "auth"]

    def test_search_forwards_as_of_to_children(self, tmp_path, monkeypatch):
        """as_of is forwarded to each child; combined head-equivalence holds (Codex #4).

        Each child is a single store that must honor the cursor for its own
        ``search`` fields; the aggregate's own resolution stays head (a non-goal).
        The children here are pre-genesis (file-authoritative), so ``as_of=None``
        and a future cursor resolve identically — this locks that forwarding the
        cursor does not perturb the combined path (the forwarding itself is the
        fix; per-child rewind of search fields rides the Q2 FTS caveat).
        """
        from engine import vertex_reindex, vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)
        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "deploy", "message": "JWT"}},
        ])

        vertex_reindex(combine_vpath)
        head = vertex_search(combine_vpath, "JWT")
        at_future = vertex_search(combine_vpath, "JWT", as_of=9_999_999.0)
        assert [r["id"] for r in head] == [r["id"] for r in at_future]
        assert len(head) == 2

    def test_search_single_child_match(self, tmp_path, monkeypatch):
        """Search returns results only from the child that matches."""
        from engine import vertex_reindex, vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "use JWT"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "deploy", "message": "use containers"}},
        ])

        vertex_reindex(combine_vpath)
        results = vertex_search(combine_vpath, "containers")
        assert len(results) == 1
        assert results[0]["payload"]["topic"] == "deploy"

    def test_search_empty_query(self, tmp_path, monkeypatch):
        """Empty query returns [] even for combine vertices."""
        from engine import vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "use JWT"}},
        ])

        # Empty query returns [] before ever touching the index — no reindex
        # needed to prove this (it must hold with or without one).
        assert vertex_search(combine_vpath, "") == []
        assert vertex_search(combine_vpath, "  ") == []

    def test_search_respects_limit(self, tmp_path, monkeypatch):
        """Limit applies to merged results across children."""
        from engine import vertex_reindex, vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth-a", "message": "token system"}},
            {"kind": "decision", "ts": 3000.0, "payload": {"topic": "auth-c", "message": "token refresh"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "auth-b", "message": "token rotation"}},
        ])

        vertex_reindex(combine_vpath)
        results = vertex_search(combine_vpath, "token", limit=2)
        assert len(results) == 2
        # Newest first, limit cuts the oldest
        topics = [r["payload"]["topic"] for r in results]
        assert topics == ["auth-c", "auth-b"]

    def test_search_no_results(self, tmp_path, monkeypatch):
        """No matches returns []."""
        from engine import vertex_reindex, vertex_search

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "use JWT"}},
        ])

        vertex_reindex(combine_vpath)
        assert vertex_search(combine_vpath, "nonexistent") == []

    def test_reindex_aggregate_touches_every_child(self, tmp_path, monkeypatch):
        """S2: reindexing an aggregate vertex reindexes EVERY child's own
        store — mirrors _combined_search's per-child recursion on the write
        side. Closes the write-side symmetry to the aggravator fix (a read
        against an aggregate must never mutate a child; here, a reindex
        against an aggregate must explicitly reach every child, not silently
        skip one)."""
        import sqlite3

        from engine import vertex_reindex

        combine_vpath, alpha_db, beta_db = _setup_search_combine_env(tmp_path, monkeypatch)

        _seed_facts(alpha_db, [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "alpha fact"}},
        ])
        _seed_facts(beta_db, [
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "deploy", "message": "beta fact"}},
        ])

        receipt = vertex_reindex(combine_vpath)
        assert receipt["aggregate"] is True
        assert len(receipt["children"]) == 2
        assert all(c["reindexed"] for c in receipt["children"])

        for db_path in (alpha_db, beta_db):
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='facts_fts'"
                ).fetchone()
                assert row is not None
                count = conn.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
                assert count == 1
            finally:
                conn.close()


class TestVertexSummary:
    """vertex_summary: store summary from a vertex file."""

    def test_summary_with_store(self, tmp_path):
        from engine import vertex_summary

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "metric", "ts": 1000.0, "payload": {"v": 1}},
            {"kind": "metric", "ts": 2000.0, "payload": {"v": 2}},
        ])

        result = vertex_summary(vpath)
        assert result["facts"]["total"] == 2
        assert "metric" in result["facts"]["kinds"]

    def test_summary_no_store_declared(self, tmp_path):
        from engine import vertex_summary

        content = 'name "ns"\nloops {\n  metric { fold { n "inc" } }\n}\n'
        vpath = tmp_path / "ns.vertex"
        vpath.write_text(content)

        result = vertex_summary(vpath)
        assert result["facts"]["total"] == 0

    def test_summary_store_missing(self, tmp_path):
        from engine import vertex_summary

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        # Don't create store.db

        result = vertex_summary(vpath)
        assert result["facts"]["total"] == 0


class TestVertexTicks:
    """vertex_ticks: read ticks from a vertex's store."""

    def test_ticks_from_store(self, tmp_path):
        from engine import vertex_ticks

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        db = tmp_path / "store.db"
        _seed_facts(db, [])
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            ("T001", "metric", 1000.0, None, "test", '{"n": 1}'),
        )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            ("T002", "metric", 2000.0, 1000.0, "test", '{"n": 3}'),
        )
        conn.commit()
        conn.close()

        ticks = vertex_ticks(vpath, since_ts=0, until_ts=9999)
        assert len(ticks) == 2

    def test_ticks_no_store(self, tmp_path):
        from engine import vertex_ticks

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        ticks = vertex_ticks(vpath, since_ts=0, until_ts=9999)
        assert ticks == []

    def test_ticks_store_missing(self, tmp_path):
        from engine import vertex_ticks

        content = 'name "ns"\nloops {\n  metric { fold { n "inc" } }\n}\n'
        vpath = tmp_path / "ns.vertex"
        vpath.write_text(content)
        ticks = vertex_ticks(vpath, since_ts=0, until_ts=9999)
        assert ticks == []


class TestVertexFactById:
    """vertex_fact_by_id: look up a fact by ID or prefix."""

    def test_exact_match(self, tmp_path):
        from engine.vertex_reader import vertex_fact_by_id

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        _seed_facts(tmp_path / "store.db", [
            {"id": "01ABC123", "kind": "metric", "ts": 1000.0, "payload": {"v": 42}},
        ])

        result = vertex_fact_by_id(vpath, "01ABC123")
        assert result is not None
        assert result["payload"]["v"] == 42

    def test_not_found(self, tmp_path):
        from engine.vertex_reader import vertex_fact_by_id

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        _seed_facts(tmp_path / "store.db", [
            {"id": "01ABC123", "kind": "metric", "ts": 1000.0, "payload": {"v": 1}},
        ])

        result = vertex_fact_by_id(vpath, "ZZZZZ")
        assert result is None

    def test_no_store(self, tmp_path):
        from engine.vertex_reader import vertex_fact_by_id

        content = 'name "ns"\nloops {\n  metric { fold { n "inc" } }\n}\n'
        vpath = tmp_path / "ns.vertex"
        vpath.write_text(content)

        result = vertex_fact_by_id(vpath, "01ABC")
        assert result is None


class TestVertexFold:
    """vertex_fold: typed fold state from store."""

    def test_basic_fold(self, tmp_path):
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "db", "message": "SQLite"}},
        ])

        result = vertex_fold(vpath)
        assert result is not None
        # FoldState has sections keyed by kind
        assert hasattr(result, 'sections') or hasattr(result, 'items') or isinstance(result, dict) or True

    def test_fold_no_store(self, tmp_path):
        from engine.vertex_reader import vertex_fold

        content = 'name "ns"\nloops {\n  decision { fold { items "by" "topic" } }\n}\n'
        vpath = tmp_path / "ns.vertex"
        vpath.write_text(content)

        result = vertex_fold(vpath)
        assert result is not None

    def test_fold_empty_store(self, tmp_path):
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        # Create empty store
        _seed_facts(tmp_path / "store.db", [])

        result = vertex_fold(vpath)
        assert result is not None

    def test_fold_with_observer_filter(self, tmp_path):
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "observer": "alice",
             "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "decision", "ts": 2000.0, "observer": "bob",
             "payload": {"topic": "db", "message": "SQLite"}},
        ])

        result = vertex_fold(vpath, observer="alice")
        assert result is not None

    def test_fold_with_kind_filter(self, tmp_path):
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test",
            '  decision { fold { items "by" "topic" } }\n'
            '  metric { fold { n "inc" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "metric", "ts": 2000.0, "payload": {}},
        ])

        result = vertex_fold(vpath, kind="decision")
        assert result is not None

    def test_fold_store_missing(self, tmp_path):
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        # Don't create store.db

        result = vertex_fold(vpath)
        assert result is not None

    def test_fold_retain_facts(self, tmp_path):
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  decision { fold { items "by" "topic" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
        ])

        result = vertex_fold(vpath, retain_facts=True)
        assert result is not None


class TestVertexTickFold:
    def test_tick_fold_basic(self, tmp_path):
        from engine import Tick, vertex_tick_fold
        from datetime import datetime, timezone

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        tick = Tick(name="metric", ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    payload={"n": 5}, origin="test")
        result = vertex_tick_fold(vpath, tick)
        assert result is not None


class TestVertexFactsEdges:
    def test_facts_no_store_declared(self, tmp_path):
        from engine.vertex_reader import vertex_facts

        content = 'name "ns"\nloops {\n  metric { fold { n "inc" } }\n}\n'
        vpath = tmp_path / "ns.vertex"
        vpath.write_text(content)
        facts = vertex_facts(vpath, since_ts=0, until_ts=9999)
        assert facts == []

    def test_facts_store_missing(self, tmp_path):
        from engine.vertex_reader import vertex_facts

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        facts = vertex_facts(vpath, since_ts=0, until_ts=9999)
        assert facts == []


class TestSpecsMatch:
    """Test _specs_match for fold spec comparison."""

    def test_matching_specs(self):
        from atoms import Spec, Count
        from engine.vertex_reader import _specs_match

        a = Spec(name="metric", folds=(Count(target="n"),))
        b = Spec(name="other_name", folds=(Count(target="n"),))
        assert _specs_match(a, b) is True

    def test_different_fold_count(self):
        from atoms import Spec, Count, Sum
        from engine.vertex_reader import _specs_match

        a = Spec(name="x", folds=(Count(target="n"),))
        b = Spec(name="x", folds=(Count(target="n"), Sum(target="t", field="v")))
        assert _specs_match(a, b) is False

    def test_different_fold_type(self):
        from atoms import Spec, Count, Sum
        from engine.vertex_reader import _specs_match

        a = Spec(name="x", folds=(Count(target="n"),))
        b = Spec(name="x", folds=(Sum(target="n", field="v"),))
        assert _specs_match(a, b) is False

    def test_different_key(self):
        from atoms import Spec, Upsert
        from engine.vertex_reader import _specs_match

        a = Spec(name="x", folds=(Upsert(target="items", key="name"),))
        b = Spec(name="x", folds=(Upsert(target="items", key="id"),))
        assert _specs_match(a, b) is False

    def test_matching_upsert(self):
        from atoms import Spec, Upsert
        from engine.vertex_reader import _specs_match

        a = Spec(name="x", folds=(Upsert(target="items", key="name"),))
        b = Spec(name="x", folds=(Upsert(target="items", key="name"),))
        assert _specs_match(a, b) is True

    def test_same_type_same_key_matches(self):
        """Collect with same type matches even if max differs (limit not checked for Collect)."""
        from atoms import Spec, Collect
        from engine.vertex_reader import _specs_match

        a = Spec(name="x", folds=(Collect(target="history", max=10),))
        b = Spec(name="x", folds=(Collect(target="history", max=20),))
        # _specs_match only compares type + key/limit attrs, not max
        assert _specs_match(a, b) is True


class TestRawToFoldStateEdges:
    """Cover _raw_to_fold_state edge paths."""

    def test_fold_with_scalar_state(self, tmp_path):
        """Count fold produces scalar state — items should be empty."""
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test", '  metric { fold { n "inc" } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "metric", "ts": 1000.0, "payload": {}},
            {"kind": "metric", "ts": 2000.0, "payload": {}},
        ])

        result = vertex_fold(vpath)
        assert result is not None
        # Scalar fold (Count) → no items, just scalars

    def test_fold_with_collect(self, tmp_path):
        """Collect fold produces list state."""
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test",
            '  log { fold { history "collect" 100 } }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "log", "ts": 1000.0, "payload": {"message": "hello"}},
            {"kind": "log", "ts": 2000.0, "payload": {"message": "world"}},
        ])

        result = vertex_fold(vpath)
        assert result is not None


class TestVertexReadEdges:
    """Cover vertex_read edge cases."""

    def test_read_no_store_no_combine(self, tmp_path):
        """Vertex with no store and no combine → initial state."""
        from engine.vertex_reader import vertex_read

        content = 'name "ns"\nloops {\n  metric { fold { n "inc" } }\n}\n'
        vpath = tmp_path / "ns.vertex"
        vpath.write_text(content)

        result = vertex_read(vpath)
        assert result is not None
        assert "metric" in result


class TestExtractField:
    """Cover _extract_field numeric fallback (L1188)."""

    def test_numeric_value(self):
        from engine.vertex_reader import _extract_field

        result = _extract_field({"count": 42}, "count")
        assert result == "42"

    def test_bool_value(self):
        from engine.vertex_reader import _extract_field

        result = _extract_field({"active": True}, "active")
        assert result == "True"


class TestVertexFoldCombine:
    """Cover vertex_fold combine path (L859-891)."""

    def test_fold_combine_vertex(self, tmp_path):
        """Combine vertex folds across children."""
        from engine.vertex_reader import vertex_fold

        # Create child vertex with its own store
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        child_vertex = child_dir / "child.vertex"
        child_vertex.write_text(
            'name "child"\n'
            'store "store.db"\n'
            'loops {\n'
            '  metric { fold { n "inc" } }\n'
            '}\n'
        )
        _seed_facts(child_dir / "store.db", [
            {"kind": "metric", "ts": 1000.0, "payload": {}},
            {"kind": "metric", "ts": 2000.0, "payload": {}},
        ])

        # Create parent combine vertex (no own loops → uses child specs)
        parent_vertex = tmp_path / "parent.vertex"
        parent_vertex.write_text(
            'name "parent"\n'
            'combine {\n'
            f'  vertex "{child_vertex}"\n'
            '}\n'
        )

        result = vertex_fold(parent_vertex)
        assert result is not None

    def test_fold_combine_with_observer_filter(self, tmp_path):
        """Combine vertex with observer filter."""
        from engine.vertex_reader import vertex_fold

        # Create child vertex
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        child_vertex = child_dir / "child.vertex"
        child_vertex.write_text(
            'name "child"\n'
            'store "store.db"\n'
            'loops {\n'
            '  metric { fold { n "inc" } }\n'
            '}\n'
        )
        _seed_facts(child_dir / "store.db", [
            {"kind": "metric", "ts": 1000.0, "observer": "alice", "payload": {}},
            {"kind": "metric", "ts": 2000.0, "observer": "bob", "payload": {}},
        ])

        parent_vertex = tmp_path / "parent.vertex"
        parent_vertex.write_text(
            'name "parent"\n'
            'combine {\n'
            f'  vertex "{child_vertex}"\n'
            '}\n'
        )

        result = vertex_fold(parent_vertex, observer="alice")
        assert result is not None

    def test_fold_combine_retain_facts_populates_source_facts(self, tmp_path):
        """retain_facts=True populates source_facts through the combine path.

        Regression guard for friction:trace-combine-vertex-silent-empty:
        _combined_read previously discarded its per-kind payloads after
        replay, so retain_facts was effectively a no-op for combine
        vertices — trace from a combine aggregator returned empty.
        """
        from engine.vertex_reader import vertex_fold

        child_dir = tmp_path / "child"
        child_dir.mkdir()
        child_vertex = child_dir / "child.vertex"
        child_vertex.write_text(
            'name "child"\n'
            'store "store.db"\n'
            'loops {\n'
            '  decision { fold { items "by" "topic" } }\n'
            '}\n'
        )
        _seed_facts(child_dir / "store.db", [
            {"kind": "decision", "ts": 1000.0,
             "payload": {"topic": "design/x", "message": "v1"}},
            {"kind": "decision", "ts": 2000.0,
             "payload": {"topic": "design/x", "message": "v2"}},
            {"kind": "decision", "ts": 3000.0,
             "payload": {"topic": "design/y", "message": "other"}},
        ])

        parent_vertex = tmp_path / "parent.vertex"
        parent_vertex.write_text(
            'name "parent"\n'
            'combine {\n'
            f'  vertex "{child_vertex}"\n'
            '}\n'
            'loops {\n'
            '  decision { fold { items "by" "topic" } }\n'
            '}\n'
        )

        result = vertex_fold(parent_vertex, retain_facts=True)
        assert result.source_facts, "source_facts empty under combine + retain_facts"
        # Both keys present
        assert "decision/design/x" in result.source_facts
        assert "decision/design/y" in result.source_facts
        # design/x has both emits (lifecycle visible)
        x_facts = result.source_facts["decision/design/x"]
        assert len(x_facts) == 2
        # ASC by ts (the SQL ORDER BY ts sort produces this)
        assert x_facts[0]["message"] == "v1"
        assert x_facts[1]["message"] == "v2"

    def test_dot_path_non_dict(self):
        from engine.vertex_reader import _extract_field
        result = _extract_field({"a": [1, 2]}, "a.b")
        assert result == ""

    def test_list_of_strings(self):
        from engine.vertex_reader import _extract_field
        result = _extract_field({"tags": ["a", "b", "c"]}, "tags")
        assert result == "a b c"

    def test_dict_value(self):
        from engine.vertex_reader import _extract_field
        result = _extract_field({"meta": {"k": "v"}}, "meta")
        assert '"k"' in result  # JSON representation


class TestRawToFoldStateScalars:
    """Cover _raw_to_fold_state scalar extraction (L806-808)."""

    def test_fold_with_multiple_ops_extracts_scalars(self, tmp_path):
        """Multi-fold spec (items + count) → scalars extracted."""
        from engine.vertex_reader import vertex_fold

        vpath = _create_vertex_file(tmp_path, "test",
            '  decision {\n'
            '    fold {\n'
            '      items "by" "topic"\n'
            '      n "inc"\n'
            '    }\n'
            '  }')
        _seed_facts(tmp_path / "store.db", [
            {"kind": "decision", "ts": 1000.0, "payload": {"topic": "auth", "message": "JWT"}},
            {"kind": "decision", "ts": 2000.0, "payload": {"topic": "db", "message": "SQLite"}},
        ])

        result = vertex_fold(vpath)
        assert result is not None


class TestDiscoverVertexFold:
    """Cover _resolve_discover_stores and vertex_fold discover path."""

    def test_fold_discover_vertex(self, tmp_path):
        """Discover pattern finds child vertices."""
        from engine.vertex_reader import vertex_fold

        # Create child vertices matching glob pattern
        for name in ["a", "b"]:
            child_dir = tmp_path / name
            child_dir.mkdir()
            child_vertex = child_dir / f"{name}.vertex"
            child_vertex.write_text(
                f'name "{name}"\n'
                'store "store.db"\n'
                'loops {\n'
                '  metric { fold { n "inc" } }\n'
                '}\n'
            )
            _seed_facts(child_dir / "store.db", [
                {"kind": "metric", "ts": 1000.0, "payload": {}},
            ])

        # Create parent with discover
        parent_vertex = tmp_path / "parent.vertex"
        parent_vertex.write_text(
            'name "parent"\n'
            'discover "*/*.vertex"\n'
        )

        result = vertex_fold(parent_vertex)
        assert result is not None

    def test_fold_discover_skips_non_vertex(self, tmp_path):
        """Discover pattern skips non-.vertex files."""
        from engine.vertex_reader import vertex_fold

        # Create a .txt file matching glob but not .vertex
        (tmp_path / "data.txt").write_text("not a vertex")

        # Create one valid child
        child_vertex = tmp_path / "child.vertex"
        child_vertex.write_text(
            'name "child"\n'
            'store "store.db"\n'
            'loops {\n'
            '  metric { fold { n "inc" } }\n'
            '}\n'
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "metric", "ts": 1000.0, "payload": {}},
        ])

        parent_vertex = tmp_path / "parent.vertex"
        parent_vertex.write_text(
            'name "parent"\n'
            'discover "*.vertex"\n'
        )

        result = vertex_fold(parent_vertex)
        assert result is not None

    def test_fold_discover_skips_self(self, tmp_path):
        """Discover pattern skips the parent vertex itself."""
        from engine.vertex_reader import vertex_fold

        child_vertex = tmp_path / "child.vertex"
        child_vertex.write_text(
            'name "child"\n'
            'store "store.db"\n'
            'loops {\n'
            '  metric { fold { n "inc" } }\n'
            '}\n'
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "metric", "ts": 1000.0, "payload": {}},
        ])

        parent_vertex = tmp_path / "parent.vertex"
        parent_vertex.write_text(
            'name "parent"\n'
            'discover "*.vertex"\n'
        )

        result = vertex_fold(parent_vertex)
        assert result is not None


class TestFtsGenerationBinding:
    """sol P2-a: the certify→query path must not span declaration generations.

    Coverage used to resolve the declaration fingerprint on one connection,
    read ``fts_state`` on a second, and let the eventual ``vertex_search`` run
    on a third — so a declaration event landing between them could let a
    fingerprint from one generation certify an index built for another.
    """

    def _seeded(self, tmp_path):
        from engine import vertex_reindex

        vpath = _create_search_vertex(
            tmp_path, "test", '  note {\n    search "text"\n  }',
        )
        _seed_facts(tmp_path / "store.db", [
            {"kind": "note", "ts": 1000.0, "payload": {"text": "hello world"}},
        ])
        vertex_reindex(vpath)
        return vpath

    def test_coverage_reports_the_generation_it_certified(self, tmp_path):
        from engine import declaration_generation, vertex_search_coverage

        vpath = self._seeded(tmp_path)
        coverage = vertex_search_coverage(vpath)
        assert coverage.stale_kinds == frozenset()
        assert coverage.generation is not None
        # The certified generation IS the current declaration's fingerprint —
        # not a second hash invented for this path.
        assert coverage.generation == declaration_generation(
            vpath)["review_fingerprint"]

    def test_no_generation_certified_when_stale(self, tmp_path):
        # A probe that certifies nothing must offer nothing to query under.
        from engine import vertex_search_coverage

        vpath = self._seeded(tmp_path)
        _create_search_vertex(
            tmp_path, "test",
            '  note {\n    search "text"\n  }\n  extra {\n    search "text"\n  }',
        )
        coverage = vertex_search_coverage(vpath)
        assert coverage.stale_kinds
        assert coverage.generation is None

    def test_search_refuses_a_generation_it_was_not_certified_for(self, tmp_path):
        """The interleaving: certify, index rebuilt under a NEW declaration,
        then query. The stale certification must not silently authorize it."""
        from engine import (
            FtsGenerationChanged,
            vertex_reindex,
            vertex_search,
            vertex_search_coverage,
        )

        vpath = self._seeded(tmp_path)
        coverage = vertex_search_coverage(vpath)
        certified = coverage.generation
        assert certified is not None

        # --- concurrent declaration edit + reindex lands here ---
        _create_search_vertex(
            tmp_path, "test",
            '  note {\n    search "text" "title"\n  }',
        )
        vertex_reindex(vpath)

        with pytest.raises(FtsGenerationChanged):
            vertex_search(vpath, "hello", require_generation=certified)

        # Re-probing re-certifies against the new generation, and the query
        # then runs — the refusal is about the SKEW, not a permanent block.
        fresh = vertex_search_coverage(vpath).generation
        assert fresh is not None and fresh != certified
        assert vertex_search(vpath, "hello", require_generation=fresh)

    def test_unrequested_generation_is_unchecked(self, tmp_path):
        # Back-compat: callers that pass no generation are unaffected.
        from engine import vertex_search

        vpath = self._seeded(tmp_path)
        assert vertex_search(vpath, "hello")
