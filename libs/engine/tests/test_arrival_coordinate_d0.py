"""Tests for WP-1a / WP-1b / D0 — The projected arrival coordinate, mirrored mode + arrival mode + write-site closure.

Gates covered:
- G-D0-1: Permuted-insert harness (index rows inserted in permuted record order; read equivalence).
- G-D0-2: Deliberately rebuilt index (preserves rowids; reads identical).
- G-D0-3: Migration of existing batch-bearing arrival-canonical index.
- G-D0-4: Interrupted migration (reopen recovers cleanly, no observable half-state).
- G-D0-5: Invariant enforcement by the table (NOT NULL and UNIQUE on coordinates).
- G-D0-6: Ordinary legacy opens migrate (sqlite and jsonl canonical).
- G-D0-7: ArrivalStore public constructor migration on unmigrated batch-bearing index.
- G-D0-8: Rederivation migration equivalence with ArrivalStore public constructor.
- G-D0-9: Trigger survival (AFTER INSERT triggers preserved and fire after rebuild).
- G-D0-10: FTS / rowid survival (FTS index and state watermark preserved across rebuild).
- G-D0-11: Mis-mode refusal (mirrored mode refuses arrival-canonical store).
- G-D0-12: Cross-table id collision (fact and tick sharing same id string).
- G-D0-13: Dependent-view survival closure-deep (v1 over facts, v2 over v1, INSTEAD OF triggers).
- Provider-mismatch refusal: Provider walk disagreeing with index refuses with rederive recommendation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import pytest
from atoms import Fact
from engine import Tick
from engine.arrival import ArrivalLog, ResumeMark
from engine.arrival_projection import rederive_projections, rows_of_record
from engine.arrival_store import (
    ARRIVAL_LINEAGE_KEY,
    ARRIVAL_OFFSET_KEY,
    ARRIVAL_ORDINAL_KEY,
    ArrivalCanonicalUnsupported,
    ArrivalStore,
)
from engine.arrival_body import (
    body_of_batch,
    body_of_fact_row,
    body_of_tick_row,
)
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
from tests.conftest import Custodian


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

    def test_permuted_vs_ordered_index_reads_equivalence(self, tmp_path: Path) -> None:
        """G-D0-1: Reads ordered by (arrival_ordinal, arrival_seq) answer identically on
        permuted vs ordered index representations.
        """
        ord_db = tmp_path / "ordered.db"
        perm_db = tmp_path / "permuted_equiv.db"

        # 1. Ordered index: physical insertion order matches arrival coordinate order
        conn_ord = sqlite3.connect(str(ord_db))
        for stmt in _SCHEMA_STMTS if "_SCHEMA_STMTS" in globals() else ():
            conn_ord.execute(stmt)
        _create_legacy_db(ord_db)
        ensure_coordinate_schema(conn_ord, mode="mirrored")
        conn_ord.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES ('f-alpha', 'note', 100.0, 'kyle', '', '{\"m\": 1}', NULL, 1, 0)"
        )
        conn_ord.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES ('f-beta', 'note', 101.0, 'kyle', '', '{\"m\": 2}', NULL, 2, 0)"
        )
        conn_ord.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES ('f-gamma', 'note', 102.0, 'kyle', '', '{\"m\": 3}', NULL, 3, 0)"
        )
        conn_ord.commit()

        # 2. Permuted index: physical insertion order is reversed relative to arrival coordinate order
        conn_perm = sqlite3.connect(str(perm_db))
        _create_legacy_db(perm_db)
        ensure_coordinate_schema(conn_perm, mode="mirrored")
        conn_perm.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES ('f-gamma', 'note', 102.0, 'kyle', '', '{\"m\": 3}', NULL, 3, 0)"
        )
        conn_perm.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES ('f-alpha', 'note', 100.0, 'kyle', '', '{\"m\": 1}', NULL, 1, 0)"
        )
        conn_perm.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES ('f-beta', 'note', 101.0, 'kyle', '', '{\"m\": 2}', NULL, 2, 0)"
        )
        conn_perm.commit()

        # 3. Read queries ordered by coordinate axis on both databases
        facts_ord = conn_ord.execute(
            "SELECT id, kind, ts, payload, arrival_ordinal, arrival_seq FROM facts ORDER BY arrival_ordinal, arrival_seq"
        ).fetchall()
        facts_perm = conn_perm.execute(
            "SELECT id, kind, ts, payload, arrival_ordinal, arrival_seq FROM facts ORDER BY arrival_ordinal, arrival_seq"
        ).fetchall()

        conn_ord.close()
        conn_perm.close()

        # Reads answer byte-identically
        assert facts_perm == facts_ord
        assert [f[0] for f in facts_perm] == ["f-alpha", "f-beta", "f-gamma"]
        assert [f[4] for f in facts_perm] == [1, 2, 3]


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


# ---------------------------------------------------------------------------
# G-D0-3: Batch-bearing arrival-canonical migration
# ---------------------------------------------------------------------------


class TestBatchBearingArrivalMigration:
    def test_batch_bearing_arrival_canonical_index_migration(self, tmp_path: Path) -> None:
        """G-D0-3: Migration of an existing batch-bearing arrival-canonical index assigns
        coordinates equal to the log's (a batch of N rows shares one ordinal with seq 0..N-1;
        ordinal=rowid would be WRONG and the test must discriminate that); subsequent
        catch-up appends collide with nothing.
        """
        custodian = Custodian(tmp_path, "kyle")
        log_path = tmp_path / "batch_bearing.arrival"
        db_path = tmp_path / "batch_bearing.db"

        # 1. Mint arrival log
        log = ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=custodian.signer,
            key=custodian.public,
        )

        # Ordinal 1: Single fact record
        f1_row = ("f-001", "note", 1000.0, "kyle", "", json.dumps({"n": 1}), None)
        _, mark1 = log.append_marked(
            "fact",
            body_of_fact_row(f1_row),
            observer="kyle",
            origin="",
            at=1000.0,
            signer=custodian.signer,
        )

        # Ordinal 2: Batch record with 3 facts
        f2_rows = [
            ("f-002-a", "note", 1001.0, "kyle", "", json.dumps({"n": 2, "sub": 0}), None),
            ("f-002-b", "note", 1002.0, "kyle", "", json.dumps({"n": 2, "sub": 1}), None),
            ("f-002-c", "note", 1003.0, "kyle", "", json.dumps({"n": 2, "sub": 2}), None),
        ]
        _, mark2 = log.append_marked(
            "batch",
            body_of_batch(f2_rows),
            observer="kyle",
            origin="",
            at=1001.0,
            signer=custodian.signer,
        )

        # Ordinal 3: Tick record
        t1_row = ("t-001", "seal", 1004.0, 0.0, "t", "{}", "", "", "", "h", None)
        _, mark3 = log.append_marked(
            "tick",
            body_of_tick_row(t1_row),
            observer="seal",
            origin="t",
            at=1004.0,
        )

        # 2. Create unmigrated SQLite index (without arrival coordinates)
        _create_legacy_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            f1_row,
        )
        for r in f2_rows:
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
                r,
            )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t1_row,
        )
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_LINEAGE_KEY, mark3.arrival_lineage),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_OFFSET_KEY, mark3.arrival_offset),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_ORDINAL_KEY, mark3.arrival_ordinal),
        )
        conn.commit()

        # 3. Provider closure walking log
        def provider() -> Iterator[tuple[str, str, int, int]]:
            for record in log.walk():
                if record["ord"] > mark3.arrival_ordinal:
                    break
                ord_val = record["ord"]
                for seq, (t, row) in enumerate(rows_of_record(record)):
                    table = "facts" if t == "fact" else "ticks"
                    yield table, row[0], ord_val, seq

        # 4. Run migration in mode='arrival'
        ensure_coordinate_schema(conn, mode="arrival", coordinates=provider)
        conn.close()

        # 5. Verify coordinates in migrated database
        conn = sqlite3.connect(str(db_path))
        meta = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        fact_rows = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid"
        ).fetchall()
        tick_rows = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM ticks ORDER BY rowid"
        ).fetchall()
        conn.close()

        assert meta is not None and meta[0] == "arrival"
        assert len(fact_rows) == 4
        # Single fact at ord 1
        assert fact_rows[0] == (1, "f-001", 1, 0)
        # Batch of 3 facts at ord 2 — ALL THREE SHARE arrival_ordinal=2 with seq 0, 1, 2!
        # Notice: rowids are 2, 3, 4 while ordinals are 2, 2, 2 (NOT rowid backfill)
        assert fact_rows[1] == (2, "f-002-a", 2, 0)
        assert fact_rows[2] == (3, "f-002-b", 2, 1)
        assert fact_rows[3] == (4, "f-002-c", 2, 2)
        # Tick at ord 3
        assert tick_rows[0] == (1, "t-001", 3, 0)

        # 6. Subsequent catch-up / append via ArrivalStore
        store = ArrivalStore(
            path=db_path,
            log_path=log_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
            fact_signer=custodian.signer,
        )
        assert store.total == 4
        new_fid = store.append(Fact.of("note", "kyle", msg="catch-up-append"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        new_fact = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts WHERE id = ?",
            (new_fid,),
        ).fetchone()
        conn.close()

        assert new_fact == (5, new_fid, 4, 0)


# ---------------------------------------------------------------------------
# G-D0-7: ArrivalStore public constructor migration on unmigrated batch-bearing index
# ---------------------------------------------------------------------------


class TestArrivalStorePublicOpenMigration:
    def test_unmigrated_batch_bearing_index_opens_via_arrival_store(self, tmp_path: Path) -> None:
        """G-D0-7: An existing UNMIGRATED batch-bearing arrival-canonical index opened
        through ArrivalStore's public constructor migrates coordinates from log, enforces
        constraints, and appends land correctly after.
        """
        custodian = Custodian(tmp_path, "kyle")
        log_path = tmp_path / "route3.arrival"
        db_path = tmp_path / "route3.db"

        # 1. Mint arrival log
        log = ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=custodian.signer,
            key=custodian.public,
        )

        # Ordinal 1: Single fact
        f1_row = ("f-001", "note", 1000.0, "kyle", "", json.dumps({"n": 1}), None)
        _, mark1 = log.append_marked(
            "fact",
            body_of_fact_row(f1_row),
            observer="kyle",
            origin="",
            at=1000.0,
            signer=custodian.signer,
        )

        # Ordinal 2: Batch of 3 facts
        f2_rows = [
            ("f-002-a", "note", 1001.0, "kyle", "", json.dumps({"n": 2, "sub": 0}), None),
            ("f-002-b", "note", 1002.0, "kyle", "", json.dumps({"n": 2, "sub": 1}), None),
            ("f-002-c", "note", 1003.0, "kyle", "", json.dumps({"n": 2, "sub": 2}), None),
        ]
        _, mark2 = log.append_marked(
            "batch",
            body_of_batch(f2_rows),
            observer="kyle",
            origin="",
            at=1001.0,
            signer=custodian.signer,
        )

        # Ordinal 3: Tick
        t1_row = ("t-001", "seal", 1004.0, 0.0, "t", "{}", "", "", "", "h", None)
        _, mark3 = log.append_marked(
            "tick",
            body_of_tick_row(t1_row),
            observer="seal",
            origin="t",
            at=1004.0,
        )

        # 2. Create unmigrated SQLite index
        _create_legacy_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            f1_row,
        )
        for r in f2_rows:
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
                r,
            )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t1_row,
        )
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_LINEAGE_KEY, mark3.arrival_lineage),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_OFFSET_KEY, mark3.arrival_offset),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_ORDINAL_KEY, mark3.arrival_ordinal),
        )
        conn.commit()
        conn.close()

        # 3. Open directly through ArrivalStore's public constructor (Route 3)
        store = ArrivalStore(
            path=db_path,
            log_path=log_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
            fact_signer=custodian.signer,
        )
        assert store.total == 4

        # 4. Verify coordinates and constraints
        conn = sqlite3.connect(str(db_path))
        meta = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        fact_rows = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid"
        ).fetchall()
        tick_rows = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM ticks ORDER BY rowid"
        ).fetchall()

        assert meta is not None and meta[0] == "arrival"
        assert fact_rows[0] == (1, "f-001", 1, 0)
        assert fact_rows[1] == (2, "f-002-a", 2, 0)
        assert fact_rows[2] == (3, "f-002-b", 2, 1)
        assert fact_rows[3] == (4, "f-002-c", 2, 2)
        assert tick_rows[0] == (1, "t-001", 3, 0)

        # Verify UNIQUE constraint is enforced
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('dup-fact', 'note', 1005.0, 'kyle', '', '{}', NULL, 2, 1)"
            )

        # Verify NOT NULL constraint is enforced
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('null-fact', 'note', 1005.0, 'kyle', '', '{}', NULL, NULL, 0)"
            )
        conn.close()

        # 5. Subsequent append via public API lands correctly
        new_fid = store.append(Fact.of("note", "kyle", msg="route3-append"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        new_row = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts WHERE id = ?",
            (new_fid,),
        ).fetchone()
        conn.close()

        assert new_row == (5, new_fid, 4, 0)


# ---------------------------------------------------------------------------
# G-D0-8: Rederivation migration equivalence
# ---------------------------------------------------------------------------


class TestRederiveProjectionsMigrationEquivalence:
    def test_rederive_projections_matches_arrival_store_migration(self, tmp_path: Path) -> None:
        """G-D0-8: The same unmigrated batch-bearing fixture through rederive_projections
        yields resulting coordinates and schema state identical to ArrivalStore public migration (G-D0-7).
        """
        custodian = Custodian(tmp_path, "kyle")

        def setup_fixture(name: str) -> tuple[Path, Path]:
            log_path = tmp_path / f"{name}.arrival"
            db_path = tmp_path / f"{name}.db"
            log = ArrivalLog.mint(
                log_path,
                observer="kyle",
                signer=custodian.signer,
                key=custodian.public,
            )

            f1_row = ("f-001", "note", 1000.0, "kyle", "", json.dumps({"n": 1}), None)
            log.append_marked(
                "fact",
                body_of_fact_row(f1_row),
                observer="kyle",
                origin="",
                at=1000.0,
                signer=custodian.signer,
            )

            f2_rows = [
                ("f-002-a", "note", 1001.0, "kyle", "", json.dumps({"n": 2, "sub": 0}), None),
                ("f-002-b", "note", 1002.0, "kyle", "", json.dumps({"n": 2, "sub": 1}), None),
                ("f-002-c", "note", 1003.0, "kyle", "", json.dumps({"n": 2, "sub": 2}), None),
            ]
            log.append_marked(
                "batch",
                body_of_batch(f2_rows),
                observer="kyle",
                origin="",
                at=1001.0,
                signer=custodian.signer,
            )

            t1_row = ("t-001", "seal", 1004.0, 0.0, "t", "{}", "", "", "", "h", None)
            _, mark3 = log.append_marked(
                "tick",
                body_of_tick_row(t1_row),
                observer="seal",
                origin="t",
                at=1004.0,
            )

            _create_legacy_db(db_path)
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
                f1_row,
            )
            for r in f2_rows:
                conn.execute(
                    "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    r,
                )
            conn.execute(
                "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                t1_row,
            )
            conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO store_meta (key, value) VALUES (?, ?)",
                (ARRIVAL_LINEAGE_KEY, mark3.arrival_lineage),
            )
            conn.execute(
                "INSERT INTO store_meta (key, value) VALUES (?, ?)",
                (ARRIVAL_OFFSET_KEY, mark3.arrival_offset),
            )
            conn.execute(
                "INSERT INTO store_meta (key, value) VALUES (?, ?)",
                (ARRIVAL_ORDINAL_KEY, mark3.arrival_ordinal),
            )
            conn.commit()
            conn.close()
            return log_path, db_path

        log_a, db_a = setup_fixture("store_a")
        log_b, db_b = setup_fixture("store_b")

        # Migrate A via ArrivalStore public constructor (Route 3)
        store_a = ArrivalStore(
            path=db_a,
            log_path=log_a,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store_a.close()

        # Migrate B via rederive_projections (Route 4)
        rederive_projections(log_b)

        # Compare both databases
        conn_a = sqlite3.connect(str(db_a))
        conn_b = sqlite3.connect(str(db_b))

        facts_a = conn_a.execute(
            "SELECT rowid, id, kind, ts, observer, origin, payload, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid"
        ).fetchall()
        facts_b = conn_b.execute(
            "SELECT rowid, id, kind, ts, observer, origin, payload, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid"
        ).fetchall()

        ticks_a = conn_a.execute(
            "SELECT rowid, id, name, ts, since, origin, payload, arrival_ordinal, arrival_seq FROM ticks ORDER BY rowid"
        ).fetchall()
        ticks_b = conn_b.execute(
            "SELECT rowid, id, name, ts, since, origin, payload, arrival_ordinal, arrival_seq FROM ticks ORDER BY rowid"
        ).fetchall()

        meta_a = conn_a.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        meta_b = conn_b.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()

        conn_a.close()
        conn_b.close()

        assert facts_a == facts_b
        assert ticks_a == ticks_b
        assert meta_a == meta_b == ("arrival",)


# ---------------------------------------------------------------------------
# G-D0-12: Cross-table ID collision
# ---------------------------------------------------------------------------


class TestCrossTableIdCollision:
    def test_cross_table_id_collision_assigned_distinct_coordinates(self, tmp_path: Path) -> None:
        """G-D0-12: An arrival fixture containing a fact and a tick sharing the same id string
        from different records assigns each its own distinct correct coordinate.
        """
        custodian = Custodian(tmp_path, "kyle")
        log_path = tmp_path / "cross_collision.arrival"
        db_path = tmp_path / "cross_collision.db"

        log = ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=custodian.signer,
            key=custodian.public,
        )

        shared_id = "shared-item-id-999"

        # Ordinal 1: Fact with shared_id
        f_row = (shared_id, "note", 1000.0, "kyle", "", json.dumps({"n": 1}), None)
        _, mark1 = log.append_marked(
            "fact",
            body_of_fact_row(f_row),
            observer="kyle",
            origin="",
            at=1000.0,
            signer=custodian.signer,
        )

        # Ordinal 2: Tick with shared_id
        t_row = (shared_id, "seal", 2000.0, 0.0, "t", "{}", "", "", "", "h", None)
        _, mark2 = log.append_marked(
            "tick",
            body_of_tick_row(t_row),
            observer="seal",
            origin="t",
            at=2000.0,
        )

        # Create unmigrated SQLite index
        _create_legacy_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            f_row,
        )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t_row,
        )
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_LINEAGE_KEY, mark2.arrival_lineage),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_OFFSET_KEY, mark2.arrival_offset),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_ORDINAL_KEY, mark2.arrival_ordinal),
        )
        conn.commit()

        # Coordinate provider yielding composite (table, row_id, ord, seq)
        def provider() -> Iterator[tuple[str, str, int, int]]:
            for record in log.walk():
                ord_val = record["ord"]
                for seq, (t, row) in enumerate(rows_of_record(record)):
                    table = "facts" if t == "fact" else "ticks"
                    yield table, row[0], ord_val, seq

        # Run migration
        ensure_coordinate_schema(conn, mode="arrival", coordinates=provider)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        fact_coord = conn.execute(
            "SELECT id, arrival_ordinal, arrival_seq FROM facts WHERE id = ?",
            (shared_id,),
        ).fetchone()
        tick_coord = conn.execute(
            "SELECT id, arrival_ordinal, arrival_seq FROM ticks WHERE id = ?",
            (shared_id,),
        ).fetchone()
        conn.close()

        assert fact_coord == (shared_id, 1, 0)
        assert tick_coord == (shared_id, 2, 0)


# ---------------------------------------------------------------------------
# Provider Mismatch Refusal
# ---------------------------------------------------------------------------


class TestProviderMismatchRefusal:
    def test_provider_fewer_rows_refuses(self, tmp_path: Path) -> None:
        """Provider walk yielding fewer rows than index refuses with rederive recommendation."""
        db_path = _create_legacy_db(tmp_path / "mismatch_fewer.db")
        _populate_legacy_facts(db_path, 3)

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('arrival_lineage', '01TESTLIN')"
        )

        # Provider only yields 2 facts when index has 3
        def provider() -> Iterator[tuple[str, str, int, int]]:
            yield "facts", "fact-000", 1, 0
            yield "facts", "fact-001", 2, 0

        with pytest.raises(ArrivalCanonicalUnsupported, match="rederive_projections"):
            ensure_coordinate_schema(conn, mode="arrival", coordinates=provider)
        conn.close()

    def test_provider_more_rows_refuses(self, tmp_path: Path) -> None:
        """Provider walk yielding extra rows not in index refuses with rederive recommendation."""
        db_path = _create_legacy_db(tmp_path / "mismatch_more.db")
        _populate_legacy_facts(db_path, 2)

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('arrival_lineage', '01TESTLIN')"
        )

        # Provider yields 3 facts when index has 2
        def provider() -> Iterator[tuple[str, str, int, int]]:
            yield "facts", "fact-000", 1, 0
            yield "facts", "fact-001", 2, 0
            yield "facts", "fact-002", 3, 0

        with pytest.raises(ArrivalCanonicalUnsupported, match="rederive_projections"):
            ensure_coordinate_schema(conn, mode="arrival", coordinates=provider)
        conn.close()

    def test_provider_differing_id_refuses(self, tmp_path: Path) -> None:
        """Provider walk yielding non-matching id refuses with rederive recommendation."""
        db_path = _create_legacy_db(tmp_path / "mismatch_id.db")
        _populate_legacy_facts(db_path, 2)

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('arrival_lineage', '01TESTLIN')"
        )

        # Provider yields different id
        def provider() -> Iterator[tuple[str, str, int, int]]:
            yield "facts", "fact-000", 1, 0
            yield "facts", "fact-OTHER", 2, 0

        with pytest.raises(ArrivalCanonicalUnsupported, match="rederive_projections"):
            ensure_coordinate_schema(conn, mode="arrival", coordinates=provider)
        conn.close()


# ---------------------------------------------------------------------------
# G-1: Divergent Legacy Index Rederivation & Strict Open Refusal
# ---------------------------------------------------------------------------


class TestDivergentLegacyRederivation:
    def test_rederivation_over_divergent_legacy_index_succeeds(
        self, tmp_path: Path
    ) -> None:
        """G-1: Rederivation over a divergent legacy (no-coordinate) index with a forged
        out-of-band row succeeds, purges the forged row, and produces log-faithful coordinates.
        """
        custodian = Custodian(tmp_path, "kyle")
        log_path = tmp_path / "divergent.arrival"
        db_path = tmp_path / "divergent.db"

        log = ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=custodian.signer,
            key=custodian.public,
        )

        f1_row = ("f-001", "note", 1000.0, "kyle", "", json.dumps({"n": 1}), None)
        log.append_marked(
            "fact",
            body_of_fact_row(f1_row),
            observer="kyle",
            origin="",
            at=1000.0,
            signer=custodian.signer,
        )

        t1_row = ("t-001", "seal", 1004.0, 0.0, "t", "{}", "", "", "", "h", None)
        _, mark2 = log.append_marked(
            "tick",
            body_of_tick_row(t1_row),
            observer="seal",
            origin="t",
            at=1004.0,
        )

        # Build legacy SQLite database (without arrival_ordinal / arrival_seq)
        _create_legacy_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            f1_row,
        )
        # Inject forged out-of-band row not present in the arrival log
        forged_row = ("f-forged-999", "note", 9999.0, "evil", "", json.dumps({"forged": True}), None)
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            forged_row,
        )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t1_row,
        )
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_LINEAGE_KEY, mark2.arrival_lineage),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_OFFSET_KEY, mark2.arrival_offset),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_ORDINAL_KEY, mark2.arrival_ordinal),
        )
        conn.commit()
        conn.close()

        # Public rederive_projections must succeed, purge forgery, produce log-faithful coordinates
        result = rederive_projections(log_path)
        assert result.records == 3
        assert result.facts == 1
        assert result.ticks == 1

        conn = sqlite3.connect(str(db_path))
        facts = conn.execute(
            "SELECT id, kind, ts, observer, origin, payload, arrival_ordinal, arrival_seq FROM facts ORDER BY arrival_ordinal, arrival_seq"
        ).fetchall()
        ticks = conn.execute(
            "SELECT id, name, ts, since, origin, payload, arrival_ordinal, arrival_seq FROM ticks ORDER BY arrival_ordinal, arrival_seq"
        ).fetchall()
        meta_axis = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        conn.close()

        # Assert forged row is purged
        assert len(facts) == 1
        assert facts[0][0] == "f-001"
        assert facts[0][6] == 1  # arrival_ordinal
        assert facts[0][7] == 0  # arrival_seq

        assert len(ticks) == 1
        assert ticks[0][0] == "t-001"
        assert ticks[0][6] == 2  # arrival_ordinal
        assert ticks[0][7] == 0  # arrival_seq

        assert meta_axis == ("arrival",)

    def test_rederivation_over_legacy_index_without_stamped_ordinal_succeeds(
        self, tmp_path: Path
    ) -> None:
        """G-1: Rederivation over a legacy index with rows but NO stamped ordinal mark
        succeeds with log-faithful coordinates.
        """
        custodian = Custodian(tmp_path, "kyle")
        log_path = tmp_path / "no_ordinal.arrival"
        db_path = tmp_path / "no_ordinal.db"

        log = ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=custodian.signer,
            key=custodian.public,
        )

        f1_row = ("f-100", "note", 1000.0, "kyle", "", json.dumps({"n": 100}), None)
        log.append_marked(
            "fact",
            body_of_fact_row(f1_row),
            observer="kyle",
            origin="",
            at=1000.0,
            signer=custodian.signer,
        )

        t1_row = ("t-100", "seal", 1004.0, 0.0, "t", "{}", "", "", "", "h", None)
        log.append_marked(
            "tick",
            body_of_tick_row(t1_row),
            observer="seal",
            origin="t",
            at=1004.0,
        )

        # Build legacy SQLite database with rows, but store_meta lacks ARRIVAL_ORDINAL_KEY
        _create_legacy_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            f1_row,
        )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t1_row,
        )
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_LINEAGE_KEY, log.lineage()),
        )
        # Note: NO ARRIVAL_ORDINAL_KEY or ARRIVAL_OFFSET_KEY inserted
        conn.commit()
        conn.close()

        # Public rederive_projections must succeed and populate log-faithful coordinates
        result = rederive_projections(log_path)
        assert result.records == 3
        assert result.facts == 1
        assert result.ticks == 1

        conn = sqlite3.connect(str(db_path))
        facts = conn.execute(
            "SELECT id, arrival_ordinal, arrival_seq FROM facts ORDER BY arrival_ordinal, arrival_seq"
        ).fetchall()
        ticks = conn.execute(
            "SELECT id, arrival_ordinal, arrival_seq FROM ticks ORDER BY arrival_ordinal, arrival_seq"
        ).fetchall()
        meta_axis = conn.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        conn.close()

        assert facts == [("f-100", 1, 0)]
        assert ticks == [("t-100", 2, 0)]
        assert meta_axis == ("arrival",)

    def test_arrival_store_init_on_divergent_fixture_refuses(
        self, tmp_path: Path
    ) -> None:
        """G-1: ArrivalStore.__init__ on the divergent fixture still refuses (strict path unaffected)."""
        custodian = Custodian(tmp_path, "kyle")
        log_path = tmp_path / "divergent_strict.arrival"
        db_path = tmp_path / "divergent_strict.db"

        log = ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=custodian.signer,
            key=custodian.public,
        )

        f1_row = ("f-001", "note", 1000.0, "kyle", "", json.dumps({"n": 1}), None)
        log.append_marked(
            "fact",
            body_of_fact_row(f1_row),
            observer="kyle",
            origin="",
            at=1000.0,
            signer=custodian.signer,
        )

        t1_row = ("t-001", "seal", 1004.0, 0.0, "t", "{}", "", "", "", "h", None)
        _, mark2 = log.append_marked(
            "tick",
            body_of_tick_row(t1_row),
            observer="seal",
            origin="t",
            at=1004.0,
        )

        # Build legacy SQLite database with forged out-of-band row
        _create_legacy_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            f1_row,
        )
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("f-forged-999", "note", 9999.0, "evil", "", json.dumps({"forged": True}), None),
        )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t1_row,
        )
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_LINEAGE_KEY, mark2.arrival_lineage),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_OFFSET_KEY, mark2.arrival_offset),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)",
            (ARRIVAL_ORDINAL_KEY, mark2.arrival_ordinal),
        )
        conn.commit()
        conn.close()

        # ArrivalStore constructor MUST refuse with rederive_projections recommendation
        with pytest.raises(ArrivalCanonicalUnsupported, match="rederive_projections"):
            ArrivalStore(
                path=db_path,
                log_path=log_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )


# ---------------------------------------------------------------------------
# SOL-WP1-01: Structural Schema Verification & Refusal on Marked Incomplete
# ---------------------------------------------------------------------------


class TestSolWp101StructuralVerification:
    def test_foreign_partial_schema_no_marker_rebuilt_correctly(
        self, tmp_path: Path
    ) -> None:
        """Foreign partial schema without marker (arrival_ordinal present, no arrival_seq / no
        constraints) is detected as unmigrated and rebuilt correctly with full constraints.
        """
        db_path = tmp_path / "foreign_partial.db"
        conn = sqlite3.connect(str(db_path))
        # Foreign partial schema: arrival_ordinal is nullable, no arrival_seq, no UNIQUE constraint
        conn.executescript(
            """
            CREATE TABLE facts (
                id TEXT NOT NULL PRIMARY KEY,
                kind TEXT NOT NULL,
                ts REAL NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                signature TEXT,
                arrival_ordinal INTEGER
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
                signature TEXT,
                arrival_ordinal INTEGER
            );
            CREATE INDEX idx_ticks_name ON ticks(name);
            CREATE INDEX idx_ticks_ts ON ticks(ts);
            """
        )
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal) "
            "VALUES ('f-partial-1', 'note', 1000.0, 'kyle', '', '{\"m\": 1}', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, window_start, fact_cursor, window_hash, signature, arrival_ordinal) "
            "VALUES ('t-partial-1', 'seal', 2000.0, 0.0, 't', '{}', '', '', '', 'h', NULL, NULL)"
        )
        conn.commit()
        conn.close()

        # Open via SqliteStore public constructor
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        assert store.total == 1
        new_fid = store.append(Fact.of("note", "kyle", msg="post_rebuild"))
        store.close()

        # Verify schema constraints and data
        conn = sqlite3.connect(str(db_path))
        meta = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        assert meta == ("mirrored",)

        # Check facts columns and NOT NULL
        fact_cols = {
            r[1]: {"notnull": bool(r[3]), "pk": bool(r[5])}
            for r in conn.execute("PRAGMA table_info(facts)")
        }
        assert fact_cols["arrival_ordinal"]["notnull"] is True
        assert fact_cols["arrival_seq"]["notnull"] is True

        # Check ticks columns and NOT NULL
        tick_cols = {
            r[1]: {"notnull": bool(r[3]), "pk": bool(r[5])}
            for r in conn.execute("PRAGMA table_info(ticks)")
        }
        assert tick_cols["arrival_ordinal"]["notnull"] is True
        assert tick_cols["arrival_seq"]["notnull"] is True

        # Check UNIQUE constraint on facts
        fact_unique = False
        for idx_row in conn.execute("PRAGMA index_list(facts)"):
            if idx_row[2]:
                idx_name = idx_row[1]
                idx_cols = [
                    r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})")
                ]
                if idx_cols == ["arrival_ordinal", "arrival_seq"]:
                    fact_unique = True
                    break
        assert fact_unique is True

        # Check UNIQUE constraint on ticks
        tick_unique = False
        for idx_row in conn.execute("PRAGMA index_list(ticks)"):
            if idx_row[2]:
                idx_name = idx_row[1]
                idx_cols = [
                    r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})")
                ]
                if idx_cols == ["arrival_ordinal", "arrival_seq"]:
                    tick_unique = True
                    break
        assert tick_unique is True

        # Check existing and new row coordinates
        rows = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid"
        ).fetchall()
        assert rows[0] == (1, "f-partial-1", 1, 0)
        assert rows[1] == (2, new_fid, 2, 0)

        # Constraint enforcement: duplicate coordinate rejected
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('f-dup', 'note', 1001.0, 'kyle', '', '{}', NULL, 1, 0)"
            )
        # Constraint enforcement: NULL coordinate rejected
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES ('f-null', 'note', 1002.0, 'kyle', '', '{}', NULL, NULL, 0)"
            )

        conn.close()

    @pytest.mark.parametrize(
        ("facts_coord_ddl", "expected_defect"),
        [
            pytest.param(
                "arrival_ordinal INTEGER NOT NULL",
                "facts lacks arrival_seq column",
                id="missing-seq",
            ),
            pytest.param(
                "arrival_ordinal INTEGER,\n"
                "                arrival_seq INTEGER NOT NULL,\n"
                "                UNIQUE (arrival_ordinal, arrival_seq)",
                "facts lacks NOT NULL on arrival_ordinal",
                id="nullable-ordinal",
            ),
            pytest.param(
                "arrival_ordinal INTEGER NOT NULL,\n"
                "                arrival_seq INTEGER,\n"
                "                UNIQUE (arrival_ordinal, arrival_seq)",
                "facts lacks NOT NULL on arrival_seq",
                id="nullable-seq",
            ),
            pytest.param(
                "arrival_ordinal INTEGER NOT NULL,\n"
                "                arrival_seq INTEGER NOT NULL",
                "facts lacks UNIQUE (arrival_ordinal, arrival_seq)",
                id="missing-unique",
            ),
        ],
    )
    def test_marker_present_deep_defects_refuse_loudly(
        self, tmp_path: Path, facts_coord_ddl: str, expected_defect: str
    ) -> None:
        """R5-1: the marker-present refusal is pinned for every DEEP defect
        dimension of SOL-WP1-01, not just total column absence — a facts table
        that would have passed the old shallow column-exists check must still
        refuse, naming the specific structural defect.
        """
        db_path = tmp_path / "stamped_deep_defect.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            f"""
            CREATE TABLE facts (
                id TEXT NOT NULL PRIMARY KEY,
                kind TEXT NOT NULL,
                ts REAL NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                signature TEXT,
                {facts_coord_ddl}
            );
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
                signature TEXT,
                arrival_ordinal INTEGER NOT NULL,
                arrival_seq INTEGER NOT NULL,
                UNIQUE (arrival_ordinal, arrival_seq)
            );
            CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO store_meta (key, value) VALUES ('coordinate_axis', 'mirrored');
            """
        )
        conn.commit()
        schema_before = conn.execute(
            "SELECT name, sql FROM sqlite_schema ORDER BY name"
        ).fetchall()
        conn.close()

        conn = sqlite3.connect(str(db_path))
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
            ensure_coordinate_schema(conn, mode="mirrored")
        conn.close()

        err_msg = str(exc_info.value)
        assert expected_defect in err_msg
        assert "coordinate_axis marker disagrees with table structure" in err_msg

        # Store must NOT be modified — no auto-rebuild on a marked store.
        conn = sqlite3.connect(str(db_path))
        schema_after = conn.execute(
            "SELECT name, sql FROM sqlite_schema ORDER BY name"
        ).fetchall()
        conn.close()
        assert schema_after == schema_before

    def test_standalone_unique_index_does_not_satisfy_table_custody(
        self, tmp_path: Path
    ) -> None:
        """SOL-WP1-02: a standalone CREATE UNIQUE INDEX (origin 'c') is not the
        table-level UNIQUE constraint D0 requires — it can be dropped without a
        rebuild, so the invariant would not live in the table. A marked store
        whose only uniqueness comes from such an index must refuse.
        """
        db_path = tmp_path / "standalone_unique_index.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE facts (
                id TEXT NOT NULL PRIMARY KEY,
                kind TEXT NOT NULL,
                ts REAL NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                signature TEXT,
                arrival_ordinal INTEGER NOT NULL,
                arrival_seq INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX foreign_coordinate_unique
                ON facts(arrival_ordinal, arrival_seq);
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
                signature TEXT,
                arrival_ordinal INTEGER NOT NULL,
                arrival_seq INTEGER NOT NULL,
                UNIQUE (arrival_ordinal, arrival_seq)
            );
            CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO store_meta (key, value) VALUES ('coordinate_axis', 'mirrored');
            """
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(str(db_path))
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
            ensure_coordinate_schema(conn, mode="mirrored")
        conn.close()
        assert "facts lacks UNIQUE (arrival_ordinal, arrival_seq)" in str(
            exc_info.value
        )

    def test_marker_present_structure_incomplete_refuses_loudly(
        self, tmp_path: Path
    ) -> None:
        """A store with coordinate_axis stamped by hand on incomplete/legacy tables raises
        ArrivalCanonicalUnsupported naming the table and defect, and leaves the store unmodified.
        """
        db_path = _create_legacy_db(tmp_path / "stamped_incomplete.db")
        fids = _populate_legacy_facts(db_path, 2)

        # Stamp coordinate_axis by hand on legacy database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('coordinate_axis', 'mirrored')"
        )
        conn.commit()

        # Capture schema before
        facts_schema_before = conn.execute(
            "SELECT sql FROM sqlite_schema WHERE type='table' AND name='facts'"
        ).fetchone()[0]
        conn.close()

        # Direct ensure_coordinate_schema must raise ArrivalCanonicalUnsupported with loud location claim
        conn = sqlite3.connect(str(db_path))
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
            ensure_coordinate_schema(conn, mode="mirrored")
        conn.close()

        err_msg = str(exc_info.value)
        assert "facts lacks arrival_ordinal column" in err_msg
        assert "coordinate_axis marker disagrees with table structure" in err_msg
        assert "out-of-band interference" in err_msg

        # Opening via SqliteStore and attempting write must also refuse
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info_store:
            store.append(Fact.of("note", "kyle", msg="attempt"))
        store.close()

        err_msg_store = str(exc_info_store.value)
        assert "facts lacks arrival_ordinal column" in err_msg_store
        assert "coordinate_axis marker disagrees with table structure" in err_msg_store
        assert "out-of-band interference" in err_msg_store

        # Store must NOT be modified
        conn = sqlite3.connect(str(db_path))
        facts_schema_after = conn.execute(
            "SELECT sql FROM sqlite_schema WHERE type='table' AND name='facts'"
        ).fetchone()[0]
        cols_after = [r[1] for r in conn.execute("PRAGMA table_info(facts)")]
        rows_after = conn.execute("SELECT id FROM facts ORDER BY rowid").fetchall()
        conn.close()

        assert facts_schema_after == facts_schema_before
        assert "arrival_ordinal" not in cols_after
        assert "arrival_seq" not in cols_after
        assert [r[0] for r in rows_after] == fids

    def test_marker_present_structure_complete_fast_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When marker is present and structure is complete, no rebuild happens (fast path)."""
        db_path = tmp_path / "complete_fast.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        f0 = store.append(Fact.of("note", "kyle", n=0))
        store.close()

        # On reopen, monkeypatch _rebuild_table to fail if called
        import engine.sqlite_store as sqlmod

        def forbid_rebuild(*args: Any, **kwargs: Any) -> None:
            pytest.fail(
                "_rebuild_table was invoked on already complete and marked database"
            )

        monkeypatch.setattr(sqlmod, "_rebuild_table", forbid_rebuild)

        reopened = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        assert reopened.total == 1
        f1 = reopened.append(Fact.of("note", "kyle", n=1))
        reopened.close()

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid"
        ).fetchall()
        meta = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        conn.close()

        assert meta == ("mirrored",)
        assert rows[0] == (1, f0, 1, 0)
        assert rows[1] == (2, f1, 2, 0)


class TestSolHigh01UnmarkedStructurallyCompleteValidation:
    """SOL-HIGH-01: In mode="arrival", a structurally-complete but UNMARKED index
    does not earn the stamp on structure alone — validate its coordinates against
    the provider (staging join agreement check) before stamping; disagreement refuses
    toward rederive_projections exactly like the rebuild path. Correct coordinates
    + removed marker validates and stamps with zero rebuild.
    """

    def test_unmarked_structurally_complete_shifted_coordinates_refuses_rederive(
        self, tmp_path: Path
    ) -> None:
        import base64

        sample_key = base64.b64encode(b"\x00" * 32).decode()
        sample_sig = base64.b64encode(b"\x01" * 64).decode()

        log_path = tmp_path / "shifted.arrival"
        ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: sample_sig,
            key=sample_key,
        )
        store = ArrivalStore(
            path=log_path.with_suffix(".db"),
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("note", "kyle", text="one"))
        store.append(Fact.of("note", "kyle", text="two"))
        store.close()

        db_path = log_path.with_suffix(".db")
        conn = sqlite3.connect(str(db_path))
        try:
            # Sol's reproduction: remove coordinate_axis marker, shift coordinates from (1,0),(2,0) to (0,0),(1,0)
            conn.execute("DELETE FROM store_meta WHERE key = 'coordinate_axis'")
            conn.execute("UPDATE facts SET arrival_ordinal = arrival_ordinal - 1")
            conn.commit()
        finally:
            conn.close()

        # Reopening must refuse toward rederive_projections
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
            ArrivalStore(
                path=db_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )

        err_msg = str(exc_info.value)
        assert "index coordinates do not match arrival log" in err_msg
        assert "rederive_projections" in err_msg

    def test_unmarked_structurally_complete_correct_coordinates_stamped_zero_rebuild(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import base64

        sample_key = base64.b64encode(b"\x00" * 32).decode()
        sample_sig = base64.b64encode(b"\x01" * 64).decode()

        log_path = tmp_path / "correct_unmarked.arrival"
        ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: sample_sig,
            key=sample_key,
        )
        store = ArrivalStore(
            path=log_path.with_suffix(".db"),
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("note", "kyle", text="one"))
        store.append(Fact.of("note", "kyle", text="two"))
        store.close()

        db_path = log_path.with_suffix(".db")
        conn = sqlite3.connect(str(db_path))
        try:
            # Remove coordinate_axis marker, but leave correct coordinates intact
            conn.execute("DELETE FROM store_meta WHERE key = 'coordinate_axis'")
            conn.commit()
        finally:
            conn.close()

        # Forbid _rebuild_table on reopen
        import engine.sqlite_store as sqlmod

        def forbid_rebuild(*args: Any, **kwargs: Any) -> None:
            pytest.fail("_rebuild_table was invoked on structurally-complete matching index")

        monkeypatch.setattr(sqlmod, "_rebuild_table", forbid_rebuild)

        reopened = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        assert reopened.total == 2
        reopened.close()

        conn = sqlite3.connect(str(db_path))
        meta = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        conn.close()

        assert meta == ("arrival",)


class TestSolHigh02IdentifierQuotingInRebuild:
    """SOL-HIGH-02: trigger/view/index names with spaces or special characters
    interpolated into DROP/re-create statements must be properly quoted.
    Sol's fixture: trigger "facts audit trigger", view "facts view", index "facts kind index"
    migrates successfully and artifacts survive.
    """

    def test_rebuild_migrates_identifiers_with_spaces(self, tmp_path: Path) -> None:
        import engine.sqlite_store as sqlmod

        db_path = tmp_path / "spaces.db"
        conn = sqlite3.connect(str(db_path))
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
            CREATE INDEX "facts kind index" ON facts(kind);
            CREATE VIEW "facts view" AS SELECT id, kind, ts, observer FROM facts;
            CREATE TRIGGER "facts audit trigger" AFTER INSERT ON facts BEGIN
                SELECT 1;
            END;
            INSERT INTO facts (id, kind, ts, observer, origin, payload, signature)
            VALUES ('f1', 'note', 1700000000.0, 'kyle', '', '{}', NULL);
            """
        )

        ensure_coordinate_schema(conn, mode="mirrored")
        conn.commit()

        # Check that table schema was migrated
        valid, defect = sqlmod._verify_coordinate_schema(conn, "facts")
        assert valid, defect

        # Check that index, view, and trigger survived
        idx = conn.execute(
            "SELECT name FROM sqlite_schema WHERE type='index' AND name='facts kind index'"
        ).fetchone()
        assert idx is not None

        view = conn.execute(
            "SELECT name FROM sqlite_schema WHERE type='view' AND name='facts view'"
        ).fetchone()
        assert view is not None

        trigger = conn.execute(
            "SELECT name FROM sqlite_schema WHERE type='trigger' AND name='facts audit trigger'"
        ).fetchone()
        assert trigger is not None

        # Check that rows survived with coordinates
        row = conn.execute("SELECT id, arrival_ordinal, arrival_seq FROM facts").fetchone()
        assert row == ("f1", 1, 0)
        conn.close()


class TestSolHigh06CoordinateAxisModeMismatch:
    """SOL-HIGH-06: A fresh ArrivalStore's coordinate_axis marker must read 'arrival',
    a fresh SqliteStore must read 'mirrored', and a hand-stamped mismatch on a NON-empty
    store must refuse loudly with ArrivalCanonicalUnsupported naming both modes.
    Empty store allows correcting marker to requested mode.
    """

    def test_fresh_arrival_store_stamped_arrival(self, tmp_path: Path) -> None:
        import base64

        sample_key = base64.b64encode(b"\x00" * 32).decode()
        sample_sig = base64.b64encode(b"\x01" * 64).decode()

        log_path = tmp_path / "fresh.arrival"
        ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: sample_sig,
            key=sample_key,
        )
        db_path = log_path.with_suffix(".db")
        store = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.close()

        conn = sqlite3.connect(str(db_path))
        meta = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        conn.close()

        assert meta == ("arrival",)

    def test_fresh_sqlite_store_stamped_mirrored(self, tmp_path: Path) -> None:
        db_path = tmp_path / "fresh_sqlite.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.close()

        conn = sqlite3.connect(str(db_path))
        meta = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        conn.close()

        assert meta == ("mirrored",)

    def test_hand_stamped_mismatch_non_empty_store_refuses_loudly(
        self, tmp_path: Path
    ) -> None:
        # Case A: Mirrored store with rows hand-stamped with coordinate_axis='arrival'
        db_path = tmp_path / "mismatch_mirrored.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("note", "kyle", text="fact1"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE store_meta SET value = 'arrival' WHERE key = 'coordinate_axis'"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(str(db_path))
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
            ensure_coordinate_schema(conn, mode="mirrored")
        conn.close()

        err_msg = str(exc_info.value)
        assert "coordinate_axis marker 'arrival' disagrees with requested mode 'mirrored'" in err_msg
        assert "non-empty store" in err_msg

        # Case B: Arrival store with rows hand-stamped with coordinate_axis='mirrored'
        import base64

        sample_key = base64.b64encode(b"\x00" * 32).decode()
        sample_sig = base64.b64encode(b"\x01" * 64).decode()

        log_path = tmp_path / "mismatch_arrival.arrival"
        ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: sample_sig,
            key=sample_key,
        )
        arr_db_path = log_path.with_suffix(".db")
        arr_store = ArrivalStore(
            path=arr_db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        arr_store.append(Fact.of("note", "kyle", text="arrival fact"))
        arr_store.close()

        conn = sqlite3.connect(str(arr_db_path))
        conn.execute(
            "UPDATE store_meta SET value = 'mirrored' WHERE key = 'coordinate_axis'"
        )
        conn.commit()
        conn.close()

        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info_arr:
            ArrivalStore(
                path=arr_db_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )

        err_msg_arr = str(exc_info_arr.value)
        assert "coordinate_axis marker 'mirrored' disagrees with requested mode 'arrival'" in err_msg_arr
        assert "non-empty store" in err_msg_arr

    def test_empty_store_mode_mismatch_corrected(self, tmp_path: Path) -> None:
        from engine.sqlite_store import _SCHEMA_STMTS

        db_path = tmp_path / "empty_correct.db"
        conn = sqlite3.connect(str(db_path))
        for stmt in _SCHEMA_STMTS:
            conn.execute(stmt)
        conn.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('coordinate_axis', 'mirrored')"
        )
        conn.commit()

        # In mode 'arrival' on empty store, correcting stamp to 'arrival' is permitted
        ensure_coordinate_schema(conn, mode="arrival", coordinates=lambda: iter([]))
        meta = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        conn.close()

        assert meta == ("arrival",)


class TestSolHigh07EmptyIndexConsultsProvider:
    """SOL-HIGH-07: The all_empty path must consult the provider in mode='arrival'.
    If the provider yields zero rows, it stamps; if the provider yields ANY rows,
    it refuses toward rederive_projections.
    """

    def test_empty_index_with_populated_log_refuses_rederive(
        self, tmp_path: Path
    ) -> None:
        import base64

        sample_key = base64.b64encode(b"\x00" * 32).decode()
        sample_sig = base64.b64encode(b"\x01" * 64).decode()

        log_path = tmp_path / "empty_index_pop_log.arrival"
        ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: sample_sig,
            key=sample_key,
        )
        db_path = log_path.with_suffix(".db")
        store = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("note", "kyle", text="fact one"))
        store.append(Fact.of("note", "kyle", text="fact two"))
        store.close()

        # Sol's reproduction: delete projected rows and marker, retain resume mark
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM facts")
        conn.execute("DELETE FROM store_meta WHERE key = 'coordinate_axis'")
        conn.commit()
        conn.close()

        # Reopening ArrivalStore must refuse toward rederive_projections, NOT silently stamp
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
            ArrivalStore(
                path=db_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )

        err_msg = str(exc_info.value)
        assert "rederive_projections" in err_msg
        assert "index content does not match arrival log coordinates" in err_msg


class TestSolHigh08EmptyLegacyIndexPublicConstructor:
    """SOL-HIGH-08: Opening an empty legacy arrival index through the public ArrivalStore
    constructor must rebuild tables with coordinate columns, stamp coordinate_axis='arrival',
    and succeed without TypeError. Appends work after migration.
    """

    def test_empty_legacy_arrival_index_migrates_stamps_and_appends(
        self, tmp_path: Path
    ) -> None:
        import base64

        sample_key = base64.b64encode(b"\x00" * 32).decode()
        sample_sig = base64.b64encode(b"\x01" * 64).decode()

        log_path = tmp_path / "empty_legacy.arrival"
        ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: sample_sig,
            key=sample_key,
        )
        db_path = log_path.with_suffix(".db")
        _create_legacy_db(db_path)

        # Open through public ArrivalStore constructor
        store = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        # Verify schema migrated and stamped
        conn = sqlite3.connect(str(db_path))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        meta = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        conn.close()

        assert "arrival_ordinal" in cols
        assert "arrival_seq" in cols
        assert meta == ("arrival",)

        # Appends work after migration
        f1 = store.append(Fact.of("note", "kyle", text="first fact after migration"))
        assert f1 is not None
        assert store.total == 1
        store.close()

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id, arrival_ordinal, arrival_seq FROM facts"
        ).fetchone()
        conn.close()
        assert row == (f1, 1, 0)


class TestSolHigh09ArrivalStampGatekeeperByConstruction:
    """SOL-HIGH-09: A single gatekeeper path (_stamp_arrival_axis) owns writing
    coordinate_axis='arrival' into store_meta by construction. Every arrival-stamping
    branch (mismatch-correction, all_empty/no tables, already_migrated, post-rebuild)
    MUST invoke the gatekeeper, ensuring provider agreement is verified on every path.
    """

    def test_structural_ratchet_single_arrival_stamp_in_store_meta(self) -> None:
        """Structural ratchet: exactly ONE write site of literal 'arrival' into store_meta
        remains in sqlite_store.py, located strictly inside _stamp_arrival_axis.

        NOTE: This ratchet is a residue locator for the literal 'arrival' write into store_meta,
        not proof of provider-agreement correctness alone. The behavioral gates own the verdict.
        """
        import ast
        import re

        store_file = (
            Path(__file__).parent.parent / "src" / "engine" / "sqlite_store.py"
        )
        content = store_file.read_text()

        # 1. Regex check: Scan for SQL INSERT / UPDATE statements writing literal 'arrival' into store_meta
        arrival_meta_writes = re.findall(
            r"INSERT\s+OR\s+REPLACE\s+INTO\s+store_meta[^\n;]*?'coordinate_axis',\s*'arrival'",
            content,
            re.IGNORECASE,
        )
        assert len(arrival_meta_writes) == 1, (
            f"Expected exactly 1 SQL write of 'arrival' into store_meta, found {len(arrival_meta_writes)}: "
            f"{arrival_meta_writes}"
        )

        # 2. AST check: Scan all function definitions for SQL execution writing literal 'arrival' to store_meta
        tree = ast.parse(content)
        functions_with_arrival_stamp: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Call):
                        call_str = ast.unparse(subnode)
                        if (
                            "store_meta" in call_str
                            and "coordinate_axis" in call_str
                            and "arrival" in call_str
                            and ("INSERT" in call_str or "UPDATE" in call_str)
                        ):
                            functions_with_arrival_stamp.append(node.name)
                            break

        assert functions_with_arrival_stamp == ["_stamp_arrival_axis"], (
            f"Expected only '_stamp_arrival_axis' to write 'arrival' to store_meta, "
            f"but found: {functions_with_arrival_stamp}"
        )

    def test_sol_r3_reproduction_empty_index_with_flipped_marker_refuses(
        self, tmp_path: Path
    ) -> None:
        """Sol's r3 reproduction: populated log + retained resume mark, index rows deleted,
        marker flipped to 'mirrored' -> reopening through ArrivalStore or calling
        ensure_coordinate_schema MUST refuse with ArrivalCanonicalUnsupported and advise
        running rederive_projections, never accept as valid-empty.
        """
        import base64

        sample_key = base64.b64encode(b"\x00" * 32).decode()
        sample_sig = base64.b64encode(b"\x01" * 64).decode()

        log_path = tmp_path / "sol_r3_repro.arrival"
        ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: sample_sig,
            key=sample_key,
        )
        db_path = log_path.with_suffix(".db")
        store = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("note", "kyle", text="first fact"))
        store.append(Fact.of("note", "kyle", text="second fact"))
        store.close()

        # Sol's reproduction: delete index rows, flip marker to 'mirrored', keep resume mark
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM facts")
        conn.execute(
            "UPDATE store_meta SET value = 'mirrored' WHERE key = 'coordinate_axis'"
        )
        conn.commit()
        conn.close()

        # Reopening through ArrivalStore MUST refuse with rederive_projections recommendation
        with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
            ArrivalStore(
                path=db_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )

        err_msg = str(exc_info.value)
        assert "rederive_projections" in err_msg
        assert "index content does not match arrival log coordinates" in err_msg
        assert "facts has 0 rows, log has 2" in err_msg

    def test_all_four_arrival_stamping_branches_refuse_on_provider_mismatch(
        self, tmp_path: Path
    ) -> None:
        """Every arrival-stamping branch (1: mismatch-correction, 2: all_empty,
        3: already_migrated, 4: post-rebuild) must refuse when provider disagrees with index.
        """
        from engine.sqlite_store import ensure_coordinate_schema

        def provider_with_rows() -> Iterator[tuple[str, str, int, int]]:
            yield "facts", "f-001", 1, 0
            yield "facts", "f-002", 2, 0

        # Branch 1: Mismatch correction on empty index when provider has rows -> refuses
        db1 = tmp_path / "branch1.db"
        _create_legacy_db(db1)
        conn1 = sqlite3.connect(str(db1))
        ensure_coordinate_schema(conn1, mode="mirrored")
        conn1.execute("DELETE FROM facts")
        conn1.commit()
        with pytest.raises(ArrivalCanonicalUnsupported) as exc1:
            ensure_coordinate_schema(conn1, mode="arrival", coordinates=provider_with_rows)
        assert "index content does not match arrival log coordinates" in str(exc1.value)
        conn1.close()

        # Branch 2: all_empty / not existing_tables when provider has rows -> refuses
        db2 = tmp_path / "branch2.db"
        conn2 = sqlite3.connect(str(db2))
        with pytest.raises(ArrivalCanonicalUnsupported) as exc2:
            ensure_coordinate_schema(conn2, mode="arrival", coordinates=provider_with_rows)
        assert "log has 2 facts rows but table does not exist" in str(exc2.value)
        conn2.close()

        # Branch 3: already_migrated when provider has row count mismatch -> refuses
        db3 = tmp_path / "branch3.db"
        _create_legacy_db(db3)
        conn3 = sqlite3.connect(str(db3))
        ensure_coordinate_schema(conn3, mode="mirrored")
        conn3.execute("DELETE FROM store_meta WHERE key = 'coordinate_axis'")
        conn3.commit()
        with pytest.raises(ArrivalCanonicalUnsupported) as exc3:
            ensure_coordinate_schema(conn3, mode="arrival", coordinates=provider_with_rows)
        assert "index content does not match arrival log coordinates" in str(exc3.value)
        conn3.close()

        # Branch 4: post-rebuild of legacy tables when provider has row count mismatch -> refuses
        db4 = tmp_path / "branch4.db"
        _create_legacy_db(db4)
        _populate_legacy_facts(db4, 3)
        conn4 = sqlite3.connect(str(db4))
        with pytest.raises(ArrivalCanonicalUnsupported) as exc4:
            ensure_coordinate_schema(conn4, mode="arrival", coordinates=provider_with_rows)
        assert "index content does not match arrival log coordinates" in str(exc4.value)
        conn4.close()

    def test_all_four_arrival_stamping_branches_succeed_when_provider_agrees(
        self, tmp_path: Path
    ) -> None:
        """Every arrival-stamping branch (1: mismatch-correction, 2: all_empty,
        3: already_migrated, 4: post-rebuild) must succeed and stamp 'arrival' when provider agrees.
        """
        from engine.sqlite_store import ensure_coordinate_schema

        empty_provider = lambda: iter([])

        # Branch 1: Mismatch correction on empty index when provider is empty -> stamps 'arrival'
        db1 = tmp_path / "agree_branch1.db"
        _create_legacy_db(db1)
        conn1 = sqlite3.connect(str(db1))
        ensure_coordinate_schema(conn1, mode="mirrored")
        conn1.execute("DELETE FROM facts")
        conn1.commit()
        ensure_coordinate_schema(conn1, mode="arrival", coordinates=empty_provider)
        meta1 = conn1.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        assert meta1 == ("arrival",)
        conn1.close()

        # Branch 2: all_empty / not existing_tables when provider is empty -> stamps 'arrival'
        db2 = tmp_path / "agree_branch2.db"
        conn2 = sqlite3.connect(str(db2))
        ensure_coordinate_schema(conn2, mode="arrival", coordinates=empty_provider)
        meta2 = conn2.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        assert meta2 == ("arrival",)
        conn2.close()

        # Branch 3: already_migrated when provider matches rows -> stamps 'arrival'
        db3 = tmp_path / "agree_branch3.db"
        _create_legacy_db(db3)
        conn3 = sqlite3.connect(str(db3))
        ensure_coordinate_schema(conn3, mode="mirrored")
        conn3.execute("DELETE FROM store_meta WHERE key = 'coordinate_axis'")
        conn3.execute("DELETE FROM facts")
        conn3.execute("INSERT INTO facts (id, kind, ts, observer, origin, payload, arrival_ordinal, arrival_seq) VALUES ('f1', 'n', 1.0, 'k', '', '{}', 1, 0)")
        conn3.commit()
        def provider_f1() -> Iterator[tuple[str, str, int, int]]:
            yield "facts", "f1", 1, 0
        ensure_coordinate_schema(conn3, mode="arrival", coordinates=provider_f1)
        meta3 = conn3.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        assert meta3 == ("arrival",)
        conn3.close()

        # Branch 4: post-rebuild of legacy tables when provider matches -> rebuilds and stamps 'arrival'
        db4 = tmp_path / "agree_branch4.db"
        _create_legacy_db(db4)
        conn4 = sqlite3.connect(str(db4))
        conn4.execute("INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES ('f1', 'n', 1.0, 'k', '', '{}')")
        conn4.commit()
        ensure_coordinate_schema(conn4, mode="arrival", coordinates=provider_f1)
        meta4 = conn4.execute("SELECT value FROM store_meta WHERE key = 'coordinate_axis'").fetchone()
        assert meta4 == ("arrival",)
        conn4.close()


