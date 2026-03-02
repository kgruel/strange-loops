"""Tests for store.slice — filtered export of facts/ticks."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest
import sqlite_ulid

from store.slice import SliceResult, slice_store


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
        conn.execute(
            "INSERT INTO facts (kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?)",
            (f["kind"], f["ts"], f["observer"], f.get("origin", ""),
             json.dumps(f.get("payload", {}))),
        )

    for t in (ticks or []):
        conn.execute(
            "INSERT INTO ticks (name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?)",
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


def _read_facts(path):
    """Read all facts as dicts."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute(
        "SELECT id, kind, ts, observer, origin, payload FROM facts ORDER BY ts"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "kind": r[1], "ts": r[2], "observer": r[3],
         "origin": r[4], "payload": json.loads(r[5])}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_BASE_TS = 1700000000.0

SAMPLE_FACTS = [
    {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice", "origin": "sensor",
     "payload": {"status": "ok"}},
    {"kind": "health", "ts": _BASE_TS + 2, "observer": "bob", "origin": "sensor",
     "payload": {"status": "warn"}},
    {"kind": "ui.key", "ts": _BASE_TS + 3, "observer": "alice", "origin": "keyboard",
     "payload": {"key": "a"}},
    {"kind": "ui.action", "ts": _BASE_TS + 4, "observer": "alice", "origin": "keyboard",
     "payload": {"action": "paste"}},
    {"kind": "deploy", "ts": _BASE_TS + 5, "observer": "ci", "origin": "github",
     "payload": {"sha": "abc123"}},
]

SAMPLE_TICKS = [
    {"name": "health.check", "ts": _BASE_TS + 2.5, "since": _BASE_TS, "origin": "vertex",
     "payload": {"count": 2}},
    {"name": "health.check", "ts": _BASE_TS + 5.5, "since": _BASE_TS + 2.5, "origin": "vertex",
     "payload": {"count": 1}},
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSliceFull:
    """Slice with no filters copies everything."""

    def test_full_copy(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS, ticks=SAMPLE_TICKS)

        result = slice_store(src, tgt)

        assert isinstance(result, SliceResult)
        assert result.facts == 5
        assert result.ticks == 2
        assert result.size_bytes > 0
        assert _count(tgt, "facts") == 5
        assert _count(tgt, "ticks") == 2

    def test_preserves_ulids(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        src_facts = _read_facts(src)
        slice_store(src, tgt)
        tgt_facts = _read_facts(tgt)

        assert [f["id"] for f in src_facts] == [f["id"] for f in tgt_facts]


class TestSliceSince:
    """Slice with since= filter."""

    def test_since_filters_facts(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS, ticks=SAMPLE_TICKS)

        result = slice_store(src, tgt, since=_BASE_TS + 3)

        assert result.facts == 3  # ui.key, ui.action, deploy
        assert result.ticks == 1  # second tick only (ts=5.5)

    def test_since_exclusive_boundary(self, tmp_path):
        """since is inclusive (>=)."""
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, since=_BASE_TS + 3)

        facts = _read_facts(tgt)
        assert all(f["ts"] >= _BASE_TS + 3 for f in facts)


class TestSliceBefore:
    """Slice with before= filter."""

    def test_before_filters_facts(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS, ticks=SAMPLE_TICKS)

        result = slice_store(src, tgt, before=_BASE_TS + 3)

        assert result.facts == 2  # health x2
        assert result.ticks == 1  # first tick only (ts=2.5)


class TestSliceSinceAndBefore:
    """Combined time range."""

    def test_range(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, since=_BASE_TS + 2, before=_BASE_TS + 4)

        assert result.facts == 2  # health(bob), ui.key


class TestSliceKinds:
    """Slice with kinds= filter."""

    def test_exact_kind(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, kinds=["deploy"])

        assert result.facts == 1

    def test_kind_prefix(self, tmp_path):
        """kinds=["ui"] matches "ui.key" and "ui.action"."""
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, kinds=["ui"])

        assert result.facts == 2
        facts = _read_facts(tgt)
        assert {f["kind"] for f in facts} == {"ui.key", "ui.action"}

    def test_multiple_kinds(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, kinds=["health", "deploy"])

        assert result.facts == 3  # 2 health + 1 deploy


class TestSliceObservers:
    """Slice with observers= filter."""

    def test_single_observer(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, observers=["alice"])

        assert result.facts == 3  # health, ui.key, ui.action

    def test_multiple_observers(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, observers=["alice", "ci"])

        assert result.facts == 4


class TestSliceOrigins:
    """Slice with origins= filter."""

    def test_single_origin(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, origins=["github"])

        assert result.facts == 1


class TestSliceCombined:
    """Combined filters."""

    def test_kinds_and_since(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, kinds=["health"], since=_BASE_TS + 1.5)

        assert result.facts == 1  # bob's health only


class TestSliceEmpty:
    """Edge cases — empty stores, no matches."""

    def test_empty_source(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src)

        result = slice_store(src, tgt)

        assert result.facts == 0
        assert result.ticks == 0

    def test_no_matches(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)

        result = slice_store(src, tgt, kinds=["nonexistent"])

        assert result.facts == 0


class TestSliceErrors:
    """Error conditions."""

    def test_source_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            slice_store(tmp_path / "nope.db", tmp_path / "target.db")

    def test_target_already_exists(self, tmp_path):
        src = tmp_path / "source.db"
        tgt = tmp_path / "target.db"
        _make_store(src, facts=SAMPLE_FACTS)
        _make_store(tgt)  # target exists

        with pytest.raises(FileExistsError):
            slice_store(src, tgt)
