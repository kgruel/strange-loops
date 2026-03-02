"""Tests for store.compact — VACUUM + PRAGMA optimize."""

from __future__ import annotations

import json
import sqlite3

import pytest
import sqlite_ulid

from store.compact import CompactResult, compact_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(path, facts=None):
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
            "INSERT INTO facts (kind, ts, observer, origin, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (f["kind"], f["ts"], f["observer"], f.get("origin", ""),
             json.dumps(f.get("payload", {}))),
        )

    conn.commit()
    conn.close()


_BASE_TS = 1700000000.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCompact:
    """Compact operation basics."""

    def test_returns_compact_result(self, tmp_path):
        db = tmp_path / "store.db"
        _make_store(db)

        result = compact_store(db)

        assert isinstance(result, CompactResult)
        assert result.before_bytes > 0
        assert result.after_bytes > 0
        assert result.saved_bytes == result.before_bytes - result.after_bytes

    def test_compact_after_deletes(self, tmp_path):
        """Deleting rows + VACUUM should reclaim space."""
        db = tmp_path / "store.db"
        # Insert many facts to create substantial data
        facts = [
            {"kind": "health", "ts": _BASE_TS + i, "observer": "alice",
             "payload": {"data": "x" * 200}}
            for i in range(100)
        ]
        _make_store(db, facts=facts)

        # Delete most rows to create reclaimable space
        conn = sqlite3.connect(str(db))
        conn.execute("DELETE FROM facts WHERE ts > ?", (_BASE_TS + 5,))
        conn.commit()
        conn.close()

        result = compact_store(db)

        # After VACUUM, space should be reclaimed
        assert result.after_bytes <= result.before_bytes
        assert result.after_bytes > 0

    def test_compact_empty_store(self, tmp_path):
        db = tmp_path / "store.db"
        _make_store(db)

        result = compact_store(db)

        assert result.after_bytes > 0  # schema still takes space
        assert result.saved_bytes >= 0

    def test_removes_wal_sidecar(self, tmp_path):
        """VACUUM should consolidate WAL into the main file."""
        db = tmp_path / "store.db"
        _make_store(db, facts=[
            {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice",
             "payload": {"status": "ok"}},
        ])

        # WAL file might exist after writes
        compact_store(db)

        # After VACUUM, WAL should be empty or gone
        wal = tmp_path / "store.db-wal"
        if wal.exists():
            assert wal.stat().st_size == 0


class TestCompactErrors:
    """Error conditions."""

    def test_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compact_store(tmp_path / "nope.db")
