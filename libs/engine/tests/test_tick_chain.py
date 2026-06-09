"""Tick hash chain — tamper-evidence at the store layer.

Covers design/tick-chain-at-store-layer: prev_hash linkage, explicit
id-based fact windows, window_hash commitments, pre-chain era migration,
and the documented chain-head scope boundary.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact

from engine import Tick
from engine.sqlite_store import SqliteStore


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "chain.db"


def make_store(path: Path) -> SqliteStore[Fact]:
    return SqliteStore(path=path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)


def emit(store: SqliteStore[Fact], n: int, *, kind: str = "note") -> list[str]:
    """Append n facts, return their assigned ids."""
    return [
        store.append(Fact.of(kind, "tester", body=f"fact-{i}"))
        for i in range(n)
    ]


def tick(store: SqliteStore[Fact], name: str = "boundary") -> None:
    store.append_tick(
        Tick(name=name, ts=datetime.now(UTC), payload={"n": store.total}, origin="test")
    )


class TestChainedAppend:
    def test_clean_store_verifies(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)
        emit(store, 2)
        tick(store)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["ticks"] == 2
        assert report["chained"] == 2
        assert report["legacy"] == 0
        assert report["covered_facts"] == 4
        assert report["uncovered_facts"] == 0
        assert report["breaks"] == []

    def test_first_tick_in_new_store_covers_all_prior_facts(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 3)
        tick(store)

        row = store._conn.execute(
            "SELECT window_start, fact_cursor FROM ticks"
        ).fetchone()
        assert row[0] == ""  # window opens at the beginning of the store
        assert store.verify_chain()["covered_facts"] == 3

    def test_live_edge_is_uncovered_not_broken(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)
        emit(store, 1)  # after the last tick — uncovered live edge

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 2
        assert report["uncovered_facts"] == 1

    def test_chain_continues_across_reopen(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)
        store.close()

        store2 = make_store(tmp_db)
        emit(store2, 1)
        tick(store2)

        report = store2.verify_chain()
        assert report["ok"] is True
        assert report["chained"] == 2

    def test_empty_store_tick_verifies(self, tmp_db: Path):
        store = make_store(tmp_db)
        tick(store)
        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 0


class TestTamperDetection:
    def test_modified_fact_breaks_window(self, tmp_db: Path):
        store = make_store(tmp_db)
        ids = emit(store, 2)
        tick(store)

        store._conn.execute(
            "UPDATE facts SET payload = ? WHERE id = ?",
            (json.dumps({"body": "rewritten history"}), ids[0]),
        )
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash" in b["reason"] for b in report["breaks"])

    def test_deleted_fact_breaks_window(self, tmp_db: Path):
        store = make_store(tmp_db)
        ids = emit(store, 3)
        tick(store)

        store._conn.execute("DELETE FROM facts WHERE id = ?", (ids[1],))
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash" in b["reason"] for b in report["breaks"])

    def test_inserted_fact_breaks_window(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)

        # "0"*26 sorts before any real ULID — lands inside the first window
        store.append(Fact.of("note", "intruder", body="backdated"), id_override="0" * 26)

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash" in b["reason"] for b in report["breaks"])

    def test_modified_tick_breaks_successor_link(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        store._conn.execute(
            "UPDATE ticks SET payload = ? WHERE name = ?",
            (json.dumps({"n": 999}), "first"),
        )
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("prev_hash" in b["reason"] for b in report["breaks"])

    def test_deleted_tick_breaks_chain(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        store._conn.execute("DELETE FROM ticks WHERE name = ?", ("first",))
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False

    def test_chain_head_unanchored_documented_boundary(self, tmp_db: Path):
        """The newest tick row is NOT self-verifying — known delta-1 scope.

        An attacker rewriting the head row's payload escapes detection
        because prev_hash only protects rows with a successor. This test
        pins the boundary so delta 2 (tick-signing) flips it deliberately.
        """
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store, "only")

        store._conn.execute(
            "UPDATE ticks SET payload = ? WHERE name = ?",
            (json.dumps({"n": 999}), "only"),
        )
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is True  # documented gap, not a regression


LEGACY_SCHEMA = (
    """CREATE TABLE facts (
        id       TEXT NOT NULL PRIMARY KEY,
        kind     TEXT NOT NULL,
        ts       REAL NOT NULL,
        observer TEXT NOT NULL,
        origin   TEXT NOT NULL DEFAULT '',
        payload  TEXT NOT NULL CHECK (json_valid(payload))
    )""",
    """CREATE TABLE ticks (
        id       TEXT NOT NULL PRIMARY KEY,
        name     TEXT NOT NULL,
        ts       REAL NOT NULL,
        since    REAL,
        origin   TEXT NOT NULL,
        payload  TEXT NOT NULL CHECK (json_valid(payload))
    )""",
)


def make_legacy_db(path: Path) -> None:
    """A pre-chain database: old schema, one fact, one tick."""
    conn = sqlite3.connect(str(path))
    for stmt in LEGACY_SCHEMA:
        conn.execute(stmt)
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
        ("01HZZZZZZZZZZZZZZZZZZZZZZZ", "note", 1700000000.0, "tester", "", '{"body": "old"}'),
    )
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
        ("01HZZZZZZZZZZZZZZZZZZZZZZX", "old-boundary", 1700000001.0, None, "test", '{"n": 1}'),
    )
    conn.commit()
    conn.close()


class TestPreChainMigration:
    def test_legacy_rows_tolerated_and_columns_added(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["legacy"] == 1
        assert report["chained"] == 1

    def test_first_chained_tick_after_legacy_claims_no_coverage(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)

        row = store._conn.execute(
            "SELECT window_start, fact_cursor FROM ticks WHERE window_hash IS NOT NULL"
        ).fetchone()
        assert row[0] == row[1]  # epoch marker: empty window, no false claims
        assert store.verify_chain()["covered_facts"] == 0

    def test_coverage_resumes_after_epoch(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)  # epoch tick, covers nothing
        emit(store, 2)
        tick(store)  # covers the 2 facts after the epoch

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 2

    def test_verify_on_pure_legacy_store_is_read_only(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["legacy"] == 1
        assert report["chained"] == 0

        # verify must NOT migrate schema — that's the write path's job
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(ticks)")}
        assert "window_hash" not in cols
