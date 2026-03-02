"""Tests for store.receive — create-or-merge with SQLite validation."""

from __future__ import annotations

import json
import sqlite3

import pytest
import sqlite_ulid

from store.receive import ReceiveResult, receive_store


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


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_BASE_TS = 1700000000.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReceiveCreate:
    """Target doesn't exist — copy source as new store."""

    def test_creates_new_store(self, tmp_path):
        source = tmp_path / "source.db"
        target = tmp_path / "target.db"
        _make_store(source, facts=[
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
        ], ticks=[
            {"name": "check", "ts": _BASE_TS + 2, "origin": "vertex",
             "payload": {"n": 1}},
        ])

        result = receive_store(target, source)

        assert isinstance(result, ReceiveResult)
        assert result.status == "created"
        assert result.facts == 1
        assert result.ticks == 1
        assert target.exists()
        assert _count(target, "facts") == 1
        assert _count(target, "ticks") == 1

    def test_creates_parent_directories(self, tmp_path):
        source = tmp_path / "source.db"
        target = tmp_path / "deep" / "nested" / "target.db"
        _make_store(source, facts=[
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
        ])

        result = receive_store(target, source)

        assert result.status == "created"
        assert target.exists()


class TestReceiveMerge:
    """Target exists — merge source into it."""

    def test_merges_new_facts(self, tmp_path):
        source = tmp_path / "source.db"
        target = tmp_path / "target.db"

        _make_store(target, facts=[
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
        ])
        _make_store(source, facts=[
            {"kind": "deploy", "ts": _BASE_TS + 2, "observer": "ci",
             "payload": {"sha": "abc"}},
        ])

        result = receive_store(target, source)

        assert result.status == "merged"
        assert result.facts == 1  # 1 new fact added
        assert _count(target, "facts") == 2

    def test_skips_duplicates(self, tmp_path):
        source = tmp_path / "source.db"
        target = tmp_path / "target.db"

        shared_id = "01h0000000000000000000test"
        fact = {"id": shared_id, "kind": "health", "ts": _BASE_TS + 1,
                "observer": "alice", "payload": {"status": "ok"}}

        _make_store(target, facts=[fact])
        _make_store(source, facts=[fact])

        result = receive_store(target, source)

        assert result.status == "merged"
        assert result.facts == 0  # duplicate skipped
        assert _count(target, "facts") == 1


class TestReceiveValidation:
    """SQLite magic byte validation."""

    def test_rejects_non_sqlite(self, tmp_path):
        source = tmp_path / "not_a_db.db"
        target = tmp_path / "target.db"
        source.write_text("this is not a database")

        with pytest.raises(ValueError, match="Not a valid SQLite"):
            receive_store(target, source)

    def test_rejects_empty_file(self, tmp_path):
        source = tmp_path / "empty.db"
        target = tmp_path / "target.db"
        source.write_bytes(b"")

        with pytest.raises(ValueError, match="Not a valid SQLite"):
            receive_store(target, source)

    def test_rejects_truncated_header(self, tmp_path):
        source = tmp_path / "truncated.db"
        target = tmp_path / "target.db"
        source.write_bytes(b"SQLite fo")

        with pytest.raises(ValueError, match="Not a valid SQLite"):
            receive_store(target, source)


class TestReceiveErrors:
    """Error conditions."""

    def test_source_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            receive_store(tmp_path / "target.db", tmp_path / "nope.db")
