"""Tests for store.merge — combine stores with ULID-based dedup."""

from __future__ import annotations

import json
import sqlite3

import pytest
import sqlite_ulid

from store.merge import MergeResult, merge_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(path, facts=None, ticks=None):
    """Create a store DB and populate it with test data."""
    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_ulid.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.executescript("""\
        CREATE TABLE facts (
            id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
            kind     TEXT NOT NULL,
            ts       REAL NOT NULL,
            observer TEXT NOT NULL,
            origin   TEXT NOT NULL DEFAULT '',
            payload  TEXT NOT NULL CHECK (json_valid(payload))
        );
        CREATE INDEX idx_facts_kind ON facts(kind);
        CREATE INDEX idx_facts_ts   ON facts(ts);
        CREATE TABLE ticks (
            id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
            name     TEXT NOT NULL,
            ts       REAL NOT NULL,
            since    REAL,
            origin   TEXT NOT NULL,
            payload  TEXT NOT NULL CHECK (json_valid(payload))
        );
        CREATE INDEX idx_ticks_name ON ticks(name);
        CREATE INDEX idx_ticks_ts   ON ticks(ts);
    """)

    for f in (facts or []):
        if "id" in f:
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f["id"], f["kind"], f["ts"], f["observer"], f.get("origin", ""),
                 json.dumps(f.get("payload", {}))),
            )
        else:
            conn.execute(
                "INSERT INTO facts (kind, ts, observer, origin, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (f["kind"], f["ts"], f["observer"], f.get("origin", ""),
                 json.dumps(f.get("payload", {}))),
            )

    for t in (ticks or []):
        if "id" in t:
            conn.execute(
                "INSERT INTO ticks (id, name, ts, since, origin, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t["id"], t["name"], t["ts"], t.get("since"), t["origin"],
                 json.dumps(t.get("payload", {}))),
            )
        else:
            conn.execute(
                "INSERT INTO ticks (name, ts, since, origin, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (t["name"], t["ts"], t.get("since"), t["origin"],
                 json.dumps(t.get("payload", {}))),
            )

    conn.commit()
    conn.close()


def _count(path, table):
    """Count rows in a table."""
    conn = sqlite3.connect(str(path))
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _read_fact_ids(path):
    """Read all fact ULIDs."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT id FROM facts ORDER BY id").fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_BASE_TS = 1700000000.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMergeNewFacts:
    """Merge disjoint stores — all facts are new."""

    def test_all_new(self, tmp_path):
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        _make_store(target, facts=[
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
        ])
        _make_store(source, facts=[
            {"kind": "deploy", "ts": _BASE_TS + 2, "observer": "ci",
             "payload": {"sha": "abc"}},
        ])

        result = merge_store(target, source)

        assert isinstance(result, MergeResult)
        assert result.facts_added == 1
        assert result.facts_skipped == 0
        assert _count(target, "facts") == 2

    def test_merge_ticks(self, tmp_path):
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        _make_store(target, ticks=[
            {"name": "check", "ts": _BASE_TS + 1, "origin": "v1",
             "payload": {"n": 1}},
        ])
        _make_store(source, ticks=[
            {"name": "check", "ts": _BASE_TS + 2, "origin": "v1",
             "payload": {"n": 2}},
        ])

        result = merge_store(target, source)

        assert result.ticks_added == 1
        assert result.ticks_skipped == 0
        assert _count(target, "ticks") == 2


class TestMergeDuplicates:
    """Merge stores with overlapping ULIDs — dedup via INSERT OR IGNORE."""

    def test_exact_duplicate_skipped(self, tmp_path):
        """Same ULID in both stores → skipped."""
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        shared_id = "01h0000000000000000000test"
        fact = {"id": shared_id, "kind": "health", "ts": _BASE_TS + 1,
                "observer": "alice", "payload": {"status": "ok"}}

        _make_store(target, facts=[fact])
        _make_store(source, facts=[fact])

        result = merge_store(target, source)

        assert result.facts_added == 0
        assert result.facts_skipped == 1
        assert _count(target, "facts") == 1

    def test_mixed_new_and_duplicate(self, tmp_path):
        """Some ULIDs overlap, some are new."""
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        shared_id = "01h0000000000000000000test"
        shared = {"id": shared_id, "kind": "health", "ts": _BASE_TS + 1,
                  "observer": "alice", "payload": {"status": "ok"}}

        _make_store(target, facts=[shared])
        _make_store(source, facts=[
            shared,
            {"kind": "deploy", "ts": _BASE_TS + 2, "observer": "ci",
             "payload": {"sha": "def"}},
        ])

        result = merge_store(target, source)

        assert result.facts_added == 1
        assert result.facts_skipped == 1
        assert _count(target, "facts") == 2


class TestMergeDryRun:
    """dry_run=True computes counts but doesn't persist."""

    def test_dry_run_no_changes(self, tmp_path):
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        _make_store(target, facts=[
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
        ])
        _make_store(source, facts=[
            {"kind": "deploy", "ts": _BASE_TS + 2, "observer": "ci",
             "payload": {"sha": "abc"}},
        ])

        result = merge_store(target, source, dry_run=True)

        assert result.facts_added == 1  # would have been added
        assert _count(target, "facts") == 1  # but target unchanged


class TestMergeEmpty:
    """Edge cases — empty stores."""

    def test_empty_source(self, tmp_path):
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        _make_store(target, facts=[
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
        ])
        _make_store(source)

        result = merge_store(target, source)

        assert result.facts_added == 0
        assert result.facts_skipped == 0
        assert _count(target, "facts") == 1

    def test_empty_target(self, tmp_path):
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        _make_store(target)
        _make_store(source, facts=[
            {"kind": "deploy", "ts": _BASE_TS + 2, "observer": "ci",
             "payload": {"sha": "abc"}},
        ])

        result = merge_store(target, source)

        assert result.facts_added == 1
        assert _count(target, "facts") == 1

    def test_both_empty(self, tmp_path):
        target = tmp_path / "target.db"
        source = tmp_path / "source.db"

        _make_store(target)
        _make_store(source)

        result = merge_store(target, source)

        assert result.facts_added == 0
        assert result.ticks_added == 0


class TestMergeErrors:
    """Error conditions."""

    def test_target_not_found(self, tmp_path):
        source = tmp_path / "source.db"
        _make_store(source)

        with pytest.raises(FileNotFoundError):
            merge_store(tmp_path / "nope.db", source)

    def test_source_not_found(self, tmp_path):
        target = tmp_path / "target.db"
        _make_store(target)

        with pytest.raises(FileNotFoundError):
            merge_store(target, tmp_path / "nope.db")


class TestSliceMergeRoundTrip:
    """Integration: slice → merge round-trip preserves data."""

    def test_roundtrip(self, tmp_path):
        from store.slice import slice_store

        original = tmp_path / "original.db"
        sliced = tmp_path / "sliced.db"
        merged = tmp_path / "merged.db"

        facts = [
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
            {"kind": "deploy", "ts": _BASE_TS + 2, "observer": "ci",
             "payload": {"sha": "abc"}},
        ]
        ticks = [
            {"name": "check", "ts": _BASE_TS + 1.5, "since": _BASE_TS,
             "origin": "vertex", "payload": {"n": 1}},
        ]
        _make_store(original, facts=facts, ticks=ticks)

        # Slice out health facts
        slice_result = slice_store(original, sliced, kinds=["health"])
        assert slice_result.facts == 1

        # Merge sliced back into a fresh target
        _make_store(merged)
        merge_result = merge_store(merged, sliced)
        assert merge_result.facts_added == 1

        # ULIDs match
        orig_ids = _read_fact_ids(original)
        merged_ids = _read_fact_ids(merged)
        sliced_ids = _read_fact_ids(sliced)
        assert merged_ids == sliced_ids
        assert sliced_ids[0] in orig_ids
