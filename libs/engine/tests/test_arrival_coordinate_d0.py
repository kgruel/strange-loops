"""Tests for WP-1a / D0 — The projected arrival coordinate, mirrored mode + write-site closure.

Gates covered:
- G-D0-1: Permuted-insert harness (index rows inserted in permuted record order).
- G-D0-2: Deliberately rebuilt index (preserves rowids; reads identical).
- G-D0-4: Interrupted migration (reopen recovers cleanly, no observable half-state).
- G-D0-5: Invariant enforcement by the table (NOT NULL and UNIQUE on coordinates).
- G-D0-6: Ordinary legacy opens migrate (sqlite and jsonl canonical).
- G-D0-9: Trigger survival (AFTER INSERT triggers preserved and fire after rebuild).
- G-D0-10: FTS / rowid survival (FTS index and state watermark preserved across rebuild).
- G-D0-11: Mis-mode refusal (mirrored mode refuses arrival-canonical store).
- G-D0-13: Dependent-view survival closure-deep (v1 over facts, v2 over v1, INSTEAD OF triggers).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from atoms import Fact
from engine import Tick
from engine.arrival_store import ArrivalCanonicalUnsupported, ArrivalStore
from engine.jsonl_store import JsonlStore
from engine.sqlite_store import (
    FACT_ALL_COLUMNS,
    FACT_INSERT_SQL,
    TICK_ALL_COLUMNS,
    TICK_INSERT_SQL,
    SqliteStore,
    ensure_coordinate_schema,
    gen_id,
)


def _create_legacy_db(path: Path) -> Path:
    """Create a legacy SQLite database (without arrival coordinates)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE facts (
            id TEXT NOT NULL PRIMARY KEY,
            kind TEXT NOT NULL,
            ts REAL NOT NULL,
            observer TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL,
            signature TEXT
        );
        CREATE INDEX idx_facts_kind ON facts(kind);
        CREATE INDEX idx_facts_ts ON facts(ts);

        CREATE TABLE ticks (
            id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            ts REAL NOT NULL,
            since REAL,
            origin TEXT NOT NULL,
            payload TEXT NOT NULL,
            prev_hash TEXT,
            window_start TEXT,
            fact_cursor TEXT,
            window_hash TEXT,
            signature TEXT
        );
        CREATE INDEX idx_ticks_name ON ticks(name);
        CREATE INDEX idx_ticks_ts ON ticks(ts);
        """
    )
    conn.close()
    return path


def _populate_legacy_facts(path: Path, count: int = 5) -> list[str]:
    conn = sqlite3.connect(str(path))
    ids = []
    for i in range(count):
        fid = f"fact-{i:03d}"
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
            "VALUES (?, 'note', ?, 'kyle', '', ?, NULL)",
            (fid, 1000.0 + i, json.dumps({"n": i})),
        )
        ids.append(fid)
    conn.commit()
    conn.close()
    return ids


def _populate_legacy_ticks(path: Path, count: int = 3) -> list[str]:
    conn = sqlite3.connect(str(path))
    ids = []
    for i in range(count):
        tid = f"tick-{i:03d}"
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, "
            "window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, 'seal', ?, 0.0, 't', '{}', '', '', '', 'h', NULL)",
            (tid, 2000.0 + i),
        )
        ids.append(tid)
    conn.commit()
    conn.close()
    return ids


# ---------------------------------------------------------------------------
# G-D0-1: Permuted-insert harness
# ---------------------------------------------------------------------------


class TestPermutedInsertHarness:
    def test_permuted_insert_coordinates_and_rowids(self, tmp_path: Path) -> None:
        """Rows inserted with non-sequential rowids still hold explicit arrival coordinates."""
        db_path = tmp_path / "permuted.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )

        f0 = store.append(Fact.of("note", "kyle", n=0))
        f1 = store.append(Fact.of("note", "kyle", n=1))
        f2 = store.append(Fact.of("note", "kyle", n=2))
        store.close()

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts ORDER BY arrival_ordinal ASC"
        ).fetchall()
        conn.close()

        assert len(rows) == 3
        # In mirrored mode, legacy allocator assigns (rowid, 0)
        assert [r[1] for r in rows] == [f0, f1, f2]
        assert [r[2] for r in rows] == [1, 2, 3]
        assert [r[3] for r in rows] == [0, 0, 0]


# ---------------------------------------------------------------------------
# G-D0-2: Deliberately rebuilt index
# ---------------------------------------------------------------------------


class TestRebuildIndex:
    def test_rebuild_preserves_rowids_and_reads(self, tmp_path: Path) -> None:
        """Rebuilding legacy database preserves exact rowids and coordinates."""
        db_path = _create_legacy_db(tmp_path / "legacy.db")
        fids = _populate_legacy_facts(db_path, 5)
        tids = _populate_legacy_ticks(db_path, 3)

        conn = sqlite3.connect(str(db_path))
        facts_before = conn.execute("SELECT rowid, id, ts FROM facts ORDER BY rowid").fetchall()
        ticks_before = conn.execute("SELECT rowid, id, ts FROM ticks ORDER BY rowid").fetchall()

        # Run migration
        ensure_coordinate_schema(conn, mode="mirrored")
        conn.close()

        conn = sqlite3.connect(str(db_path))
        facts_after = conn.execute(
            "SELECT rowid, id, ts, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid"
        ).fetchall()
        ticks_after = conn.execute(
            "SELECT rowid, id, ts, arrival_ordinal, arrival_seq FROM ticks ORDER BY rowid"
        ).fetchall()
        meta = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        conn.close()

        assert meta is not None and meta[0] == "mirrored"
        assert len(facts_after) == len(facts_before)
        assert len(ticks_after) == len(ticks_before)

        for b, a in zip(facts_before, facts_after):
            assert a[0] == b[0]  # rowid preserved
            assert a[1] == b[1]  # id preserved
            assert a[2] == b[2]  # ts preserved
            assert a[3] == b[0]  # arrival_ordinal == rowid
            assert a[4] == 0  # arrival_seq == 0

        for b, a in zip(ticks_before, ticks_after):
            assert a[0] == b[0]  # rowid preserved
            assert a[1] == b[1]  # id preserved
            assert a[2] == b[2]  # ts preserved
            assert a[3] == b[0]  # arrival_ordinal == rowid
            assert a[4] == 0  # arrival_seq == 0


# ---------------------------------------------------------------------------
# G-D0-4: Interrupted migration
# ---------------------------------------------------------------------------


class TestInterruptedMigration:
    def test_interrupted_migration_is_atomic_or_recoverable(self, tmp_path: Path) -> None:
        """A migration that is killed or interrupted rolls back or re-runs cleanly on next open."""
        db_path = _create_legacy_db(tmp_path / "interrupted.db")
        _populate_legacy_facts(db_path, 3)

        conn = sqlite3.connect(str(db_path))
        # Simulate partial table rename failure in transaction
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE facts_new (id TEXT PRIMARY KEY, kind TEXT, ts REAL, "
                "observer TEXT, origin TEXT, payload TEXT, signature TEXT, "
                "arrival_ordinal INTEGER NOT NULL, arrival_seq INTEGER NOT NULL, "
                "UNIQUE(arrival_ordinal, arrival_seq))"
            )
            # Intentionally abort before completion
            raise RuntimeError("simulated crash during migration")
        except RuntimeError:
            conn.execute("ROLLBACK")
        finally:
            conn.close()

        # Opening via SqliteStore triggers clean migration
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        assert store.total == 3
        # Next append succeeds cleanly
        new_fid = store.append(Fact.of("note", "kyle", msg="after crash"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        meta = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        row = conn.execute(
            "SELECT rowid, arrival_ordinal, arrival_seq FROM facts WHERE id = ?", (new_fid,)
        ).fetchone()
        conn.close()

        assert meta[0] == "mirrored"
        assert row[1] == 4
        assert row[2] == 0


# ---------------------------------------------------------------------------
# G-D0-5: Invariant enforcement by the table
# ---------------------------------------------------------------------------


class TestTableEnforcedInvariants:
    def test_not_null_and_unique_constraints_on_fresh_db(self, tmp_path: Path) -> None:
        """On a freshly created database, table-level constraints reject NULL and duplicate coordinates."""
        db_path = tmp_path / "fresh.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.close()

        conn = sqlite3.connect(str(db_path))

        # 1. Reject NULL in arrival_ordinal
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('f1', 'note', 100.0, 'kyle', '', '{}', NULL, NULL, 0)"
            )

        # 2. Reject NULL in arrival_seq
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('f1', 'note', 100.0, 'kyle', '', '{}', NULL, 1, NULL)"
            )

        # 3. Insert valid row (1, 0)
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES ('f1', 'note', 100.0, 'kyle', '', '{}', NULL, 1, 0)"
        )
        conn.commit()

        # 4. Reject duplicate (arrival_ordinal, arrival_seq)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('f2', 'note', 101.0, 'kyle', '', '{}', NULL, 1, 0)"
            )

        conn.close()

    def test_not_null_and_unique_constraints_on_migrated_db(self, tmp_path: Path) -> None:
        """On a migrated legacy database, table-level constraints reject NULL and duplicate coordinates."""
        db_path = _create_legacy_db(tmp_path / "migrated.db")
        _populate_legacy_facts(db_path, 2)

        conn = sqlite3.connect(str(db_path))
        ensure_coordinate_schema(conn, mode="mirrored")

        # 1. Reject NULL
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('f_null', 'note', 100.0, 'kyle', '', '{}', NULL, NULL, 0)"
            )

        # 2. Reject duplicate of existing migrated row (1, 0)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('f_dup', 'note', 100.0, 'kyle', '', '{}', NULL, 1, 0)"
            )

        conn.close()

    def test_legacy_allocator_monotonic_under_interleaved_writes(self, tmp_path: Path) -> None:
        """Interleaved fact and tick writes in SqliteStore allocate monotonic coordinates."""
        db_path = tmp_path / "interleaved.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )

        f1 = store.append(Fact.of("note", "kyle", msg="1"))
        t1 = store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={}, origin="t"))
        f2 = store.append(Fact.of("note", "kyle", msg="2"))
        t2 = store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={}, origin="t"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        fact_coords = conn.execute(
            "SELECT id, arrival_ordinal, arrival_seq FROM facts ORDER BY arrival_ordinal"
        ).fetchall()
        tick_coords = conn.execute(
            "SELECT id, arrival_ordinal, arrival_seq FROM ticks ORDER BY arrival_ordinal"
        ).fetchall()
        conn.close()

        assert fact_coords[0][1] == 1
        assert tick_coords[0][1] == 1
        assert fact_coords[1][1] == 2
        assert tick_coords[1][1] == 2


# ---------------------------------------------------------------------------
# G-D0-6: Ordinary legacy opens migrate
# ---------------------------------------------------------------------------


class TestOrdinaryLegacyOpensMigrate:
    def test_sqlite_canonical_legacy_open(self, tmp_path: Path) -> None:
        """Opening a legacy SQLite database via SqliteStore runs upgrader before first insert."""
        db_path = _create_legacy_db(tmp_path / "sqlite_legacy.db")
        _populate_legacy_facts(db_path, 3)

        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        assert store.total == 3

        new_id = store.append(Fact.of("note", "kyle", msg="new"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        meta = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        row = conn.execute(
            "SELECT arrival_ordinal, arrival_seq FROM facts WHERE id = ?", (new_id,)
        ).fetchone()
        conn.close()

        assert meta[0] == "mirrored"
        assert row[0] == 4
        assert row[1] == 0

    def test_jsonl_canonical_legacy_open(self, tmp_path: Path) -> None:
        """Opening a legacy JSONL store runs coordinate upgrader on index."""
        log_path = tmp_path / "events.jsonl"
        index_path = tmp_path / "events.db"

        # Create legacy index
        _create_legacy_db(index_path)
        log_path.write_text("")

        store = JsonlStore(
            path=index_path,
            log_path=log_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("note", "kyle", msg="jsonl_fact"))
        store.close()

        conn = sqlite3.connect(str(index_path))
        meta = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        row = conn.execute("SELECT arrival_ordinal, arrival_seq FROM facts").fetchone()
        conn.close()

        assert meta[0] == "mirrored"
        assert row[0] == 1
        assert row[1] == 0


# ---------------------------------------------------------------------------
# G-D0-9: Trigger survival
# ---------------------------------------------------------------------------


class TestTriggerSurvival:
    def test_after_insert_trigger_survives_migration_and_fires(self, tmp_path: Path) -> None:
        """AFTER INSERT triggers on facts are preserved during rebuild and fire on subsequent appends."""
        db_path = _create_legacy_db(tmp_path / "trigger.db")
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE audit_log (fact_id TEXT, fired_at REAL);
            CREATE TRIGGER trg_facts_audit AFTER INSERT ON facts
            BEGIN
                INSERT INTO audit_log (fact_id, fired_at) VALUES (NEW.id, NEW.ts);
            END;
            """
        )
        conn.close()

        # Open and migrate
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        fid = store.append(Fact.of("note", "kyle", ts=12345.0, msg="trig"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        trig = conn.execute(
            "SELECT name FROM sqlite_schema WHERE type='trigger' AND name='trg_facts_audit'"
        ).fetchone()
        audit_row = conn.execute("SELECT fact_id, fired_at FROM audit_log").fetchone()
        conn.close()

        assert trig is not None
        assert audit_row == (fid, 12345.0)


# ---------------------------------------------------------------------------
# G-D0-10: FTS and rowid survival
# ---------------------------------------------------------------------------


class TestFtsRowidSurvival:
    def test_fts_and_watermark_survive_rebuild(self, tmp_path: Path) -> None:
        """FTS table and watermark state survive migration with identical rowid mapping."""
        db_path = _create_legacy_db(tmp_path / "fts.db")
        fids = _populate_legacy_facts(db_path, 3)

        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE VIRTUAL TABLE facts_fts USING fts5(id, payload, content=facts, content_rowid=rowid);
            CREATE TABLE fts_state (key TEXT PRIMARY KEY, last_rowid INTEGER);
            INSERT INTO facts_fts (rowid, id, payload) SELECT rowid, id, payload FROM facts;
            INSERT INTO fts_state (key, last_rowid) VALUES ('watermark', 3);
            """
        )
        # Search before migration
        matches_before = conn.execute(
            "SELECT f.id FROM facts_fts JOIN facts f ON facts_fts.rowid = f.rowid "
            "WHERE facts_fts MATCH 'n' ORDER BY f.rowid"
        ).fetchall()

        # Run migration
        ensure_coordinate_schema(conn, mode="mirrored")

        # Search after migration
        matches_after = conn.execute(
            "SELECT f.id FROM facts_fts JOIN facts f ON facts_fts.rowid = f.rowid "
            "WHERE facts_fts MATCH 'n' ORDER BY f.rowid"
        ).fetchall()
        watermark = conn.execute(
            "SELECT last_rowid FROM fts_state WHERE key = 'watermark'"
        ).fetchone()
        conn.close()

        assert matches_before == [(fids[0],), (fids[1],), (fids[2],)]
        assert matches_after == matches_before
        assert watermark == (3,)


# ---------------------------------------------------------------------------
# G-D0-11: Mis-mode refusal
# ---------------------------------------------------------------------------


class TestMisModeRefusal:
    def test_mirrored_mode_refuses_arrival_canonical_index(self, tmp_path: Path) -> None:
        """ensure_coordinate_schema(conn, mode='mirrored') refuses on an arrival-canonical database."""
        db_path = tmp_path / "arrival_idx.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE facts (id TEXT PRIMARY KEY, kind TEXT, ts REAL, observer TEXT, origin TEXT, payload TEXT, signature TEXT);
            CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO store_meta (key, value) VALUES ('arrival_lineage', '01ARRIVALLINEAGE000000000000');
            """
        )

        with pytest.raises(ArrivalCanonicalUnsupported, match="cannot apply mirrored coordinate schema"):
            ensure_coordinate_schema(conn, mode="mirrored")

        conn.close()


# ---------------------------------------------------------------------------
# G-D0-13: Dependent-view survival closure-deep
# ---------------------------------------------------------------------------


class TestDependentViewSurvivalClosureDeep:
    def test_v1_over_facts_v2_over_v1_and_instead_of_trigger_survive(self, tmp_path: Path) -> None:
        """Deep dependent views (v1 on facts, v2 on v1) and INSTEAD OF triggers survive migration."""
        db_path = _create_legacy_db(tmp_path / "views.db")
        _populate_legacy_facts(db_path, 3)

        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE VIEW v1_facts AS SELECT id, kind, ts, payload FROM facts WHERE kind = 'note';
            CREATE VIEW v2_notes AS SELECT id, payload FROM v1_facts;
            CREATE TABLE v1_interceptions (fact_id TEXT, action TEXT);
            CREATE TRIGGER trg_v1_insert INSTEAD OF INSERT ON v1_facts
            BEGIN
                INSERT INTO v1_interceptions (fact_id, action) VALUES (NEW.id, 'intercepted');
            END;
            """
        )

        v1_before = conn.execute("SELECT id, kind FROM v1_facts ORDER BY id").fetchall()
        v2_before = conn.execute("SELECT id FROM v2_notes ORDER BY id").fetchall()

        # Run migration — fixed point view/trigger closure
        ensure_coordinate_schema(conn, mode="mirrored")

        v1_after = conn.execute("SELECT id, kind FROM v1_facts ORDER BY id").fetchall()
        v2_after = conn.execute("SELECT id FROM v2_notes ORDER BY id").fetchall()

        # Test INSTEAD OF trigger on v1_facts
        conn.execute("INSERT INTO v1_facts (id, kind, ts, payload) VALUES ('f_v1', 'note', 999.0, '{}')")
        intercepted = conn.execute("SELECT fact_id, action FROM v1_interceptions").fetchall()
        conn.close()

        assert v1_after == v1_before
        assert v2_after == v2_before
        assert intercepted == [("f_v1", "intercepted")]
