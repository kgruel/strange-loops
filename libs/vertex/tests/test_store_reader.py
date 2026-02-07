"""Tests for StoreReader — read-only inspector for SqliteStore databases."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vertex import Tick
from vertex.store_reader import StoreReader

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS facts (
    rowid INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    ts REAL NOT NULL,
    observer TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts);

CREATE TABLE IF NOT EXISTS ticks (
    rowid INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ts REAL NOT NULL,
    since REAL,
    origin TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name);
CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts);
"""


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Create an empty store database with the expected schema."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    conn.close()
    return db_path


@pytest.fixture
def populated_db(tmp_db: Path) -> Path:
    """Database with facts and ticks for summary/recent tests."""
    conn = sqlite3.connect(str(tmp_db))
    # Two kinds of facts
    conn.execute(
        "INSERT INTO facts (kind, ts, observer, payload) VALUES (?, ?, ?, ?)",
        ("page", 100.0, "scraper", '{"url": "a"}'),
    )
    conn.execute(
        "INSERT INTO facts (kind, ts, observer, payload) VALUES (?, ?, ?, ?)",
        ("page", 200.0, "scraper", '{"url": "b"}'),
    )
    conn.execute(
        "INSERT INTO facts (kind, ts, observer, payload) VALUES (?, ?, ?, ?)",
        ("error", 150.0, "scraper", '{"msg": "fail"}'),
    )
    # Three ticks, two names
    for name, ts, payload in [
        ("scrape", 1000.0, {"n": 1}),
        ("scrape", 2000.0, {"n": 2}),
        ("health", 1500.0, {}),
    ]:
        conn.execute(
            "INSERT INTO ticks (name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?)",
            (name, ts, None, "v1", json.dumps(payload)),
        )
    conn.commit()
    conn.close()
    return tmp_db


class TestSummary:
    def test_summary_empty_store(self, tmp_db: Path):
        with StoreReader(tmp_db) as reader:
            s = reader.summary()
            assert s["facts"]["total"] == 0
            assert s["facts"]["kinds"] == {}
            assert s["ticks"]["total"] == 0
            assert s["ticks"]["names"] == {}

    def test_summary_shape(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            s = reader.summary()
            assert s["facts"]["total"] == 3
            assert set(s["facts"]["kinds"].keys()) == {"page", "error"}
            assert s["facts"]["kinds"]["page"]["count"] == 2
            assert s["facts"]["kinds"]["error"]["count"] == 1

            assert s["ticks"]["total"] == 3
            assert set(s["ticks"]["names"].keys()) == {"scrape", "health"}
            assert s["ticks"]["names"]["scrape"]["count"] == 2
            assert s["ticks"]["names"]["health"]["count"] == 1

            # Timestamps are datetimes, not floats
            assert isinstance(s["facts"]["kinds"]["page"]["earliest"], datetime)
            assert isinstance(s["ticks"]["names"]["scrape"]["latest"], datetime)


class TestRecentTicks:
    def test_recent_ticks_ordered_desc(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            recent = reader.recent_ticks("scrape", 2)
            assert len(recent) == 2
            assert recent[0].payload == {"n": 2}  # newest first
            assert recent[1].payload == {"n": 1}

    def test_recent_ticks_limits(self, tmp_db: Path):
        conn = sqlite3.connect(str(tmp_db))
        for i in range(10):
            conn.execute(
                "INSERT INTO ticks (name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?)",
                ("m", float(i * 100), None, "v", json.dumps(i)),
            )
        conn.commit()
        conn.close()

        with StoreReader(tmp_db) as reader:
            assert len(reader.recent_ticks("m", 3)) == 3
            assert len(reader.recent_ticks("m", 100)) == 10

    def test_recent_ticks_unknown_name(self, tmp_db: Path):
        with StoreReader(tmp_db) as reader:
            assert reader.recent_ticks("nonexistent", 5) == []


class TestRecentFacts:
    def test_recent_facts_ordered_desc(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            recent = reader.recent_facts("page", 2)
            assert len(recent) == 2
            assert recent[0]["payload"]["url"] == "b"  # newest first (ts=200)
            assert recent[1]["payload"]["url"] == "a"  # ts=100

    def test_recent_facts_returns_datetimes(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            recent = reader.recent_facts("page", 1)
            assert isinstance(recent[0]["ts"], datetime)

    def test_recent_facts_unknown_kind(self, tmp_db: Path):
        with StoreReader(tmp_db) as reader:
            assert reader.recent_facts("nonexistent", 5) == []


class TestFileNotFound:
    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            StoreReader(tmp_path / "does_not_exist.db")


class TestReadOnly:
    def test_read_only(self, tmp_db: Path):
        with StoreReader(tmp_db) as reader:
            with pytest.raises(sqlite3.OperationalError):
                reader._conn.execute(
                    "INSERT INTO facts (kind, ts, observer, payload) VALUES (?, ?, ?, ?)",
                    ("x", 1.0, "x", "{}"),
                )
