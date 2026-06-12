"""Tests for store.merge — combine stores with id-PK dedup."""

from __future__ import annotations

import json
import sqlite3

import pytest
from ulid import ULID

from store.merge import MergeResult, merge_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(path, facts=None, ticks=None):
    """Create a store DB and populate it with test data.

    Post-2026-05-16 shape: no schema DEFAULT (ulid()), ids supplied
    explicitly via python-ulid (same primitive as engine.SqliteStore).
    """
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.executescript("""\
        CREATE TABLE facts (
            id       TEXT NOT NULL PRIMARY KEY,
            kind     TEXT NOT NULL,
            ts       REAL NOT NULL,
            observer TEXT NOT NULL,
            origin   TEXT NOT NULL DEFAULT '',
            payload  TEXT NOT NULL CHECK (json_valid(payload))
        );
        CREATE INDEX idx_facts_kind ON facts(kind);
        CREATE INDEX idx_facts_ts   ON facts(ts);
        CREATE TABLE ticks (
            id       TEXT NOT NULL PRIMARY KEY,
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
        fact_id = f.get("id") or str(ULID())
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fact_id, f["kind"], f["ts"], f["observer"], f.get("origin", ""),
             json.dumps(f.get("payload", {}))),
        )

    for t in (ticks or []):
        tick_id = t.get("id") or str(ULID())
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tick_id, t["name"], t["ts"], t.get("since"), t["origin"],
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


class TestMergeViaProductionEmitPath:
    """Regression bar: exercise merge through engine.SqliteStore.append().

    The 2026-03-15 → 2026-05-16 uuid4 regression survived two months because
    every test in this file constructs fixtures via sqlite_ulid.load(conn)
    rather than through SqliteStore.append() — so the production id path was
    never exercised here. This class closes that gap: any future regression
    in _gen_id that breaks merge semantics will fail one of these tests.

    Asserts both surviving properties:
    - INSERT OR IGNORE dedup on PK (slice→merge round-trip yields same id)
    - ORDER BY id ≈ chronological emission order after cross-store merge
    """

    @staticmethod
    def _engine_store(path):
        """Construct a store via the production write path."""
        from engine.sqlite_store import SqliteStore

        def _serialize(f):
            return {"kind": f["kind"], "ts": f["ts"], "observer": f["observer"],
                    "origin": f.get("origin", ""), "payload": f.get("payload", {})}

        return SqliteStore(path=path, serialize=_serialize, deserialize=lambda d: d)

    def test_slice_merge_roundtrip_via_engine_emit(self, tmp_path):
        """Emit via SqliteStore.append() → slice → merge → ids preserved + dedup works."""
        from store.slice import slice_store

        original = tmp_path / "original.db"
        sliced = tmp_path / "sliced.db"
        merged = tmp_path / "merged.db"

        emitted_ids: list[str] = []
        with self._engine_store(original) as store:
            for i in range(3):
                fact_id = store.append({
                    "kind": "health",
                    "ts": _BASE_TS + i,
                    "observer": "alice",
                    "payload": {"i": i},
                })
                emitted_ids.append(fact_id)

        slice_result = slice_store(original, sliced, kinds=["health"])
        assert slice_result.facts == 3

        # Fresh empty target — construct via engine so schema matches production
        with self._engine_store(merged):
            pass

        merge_result = merge_store(merged, sliced)
        assert merge_result.facts_added == 3
        assert merge_result.facts_skipped == 0

        # Slice preserves IDs end-to-end
        merged_ids = _read_fact_ids(merged)
        assert sorted(merged_ids) == sorted(emitted_ids)

    def test_merge_dedup_via_engine_emit(self, tmp_path):
        """Merging the same sliced source twice → second merge dedups all."""
        from store.slice import slice_store

        original = tmp_path / "original.db"
        sliced = tmp_path / "sliced.db"
        target = tmp_path / "target.db"

        with self._engine_store(original) as store:
            for i in range(4):
                store.append({
                    "kind": "deploy",
                    "ts": _BASE_TS + i,
                    "observer": "ci",
                    "payload": {"sha": f"abc{i}"},
                })

        slice_store(original, sliced, kinds=["deploy"])

        with self._engine_store(target):
            pass

        # First merge: all added
        first = merge_store(target, sliced)
        assert first.facts_added == 4
        assert first.facts_skipped == 0

        # Second merge of same source: all should dedup (ids match)
        second = merge_store(target, sliced)
        assert second.facts_added == 0, (
            f"dedup failed — second merge added {second.facts_added} facts, "
            "indicating slice did not preserve ids or merge is not dedup'ing "
            "on PK. This is the failure mode the uuid4 regression would have "
            "produced if slice had regenerated ids (it didn't, which is why "
            "the dedup case survived). Still load-bearing as a regression bar."
        )
        assert second.facts_skipped == 4

    def test_cross_store_merge_orders_chronologically(self, tmp_path):
        """After merging two stores, ORDER BY id ≈ chronological emission.

        This is the property that uuid4 silently broke. Without time-sortable
        ids, querying the merged store for 'what happened in what order across
        these stores' returns random order.
        """
        import sqlite3
        import time as _time

        store_a_path = tmp_path / "a.db"
        store_b_path = tmp_path / "b.db"
        merged_path = tmp_path / "merged.db"

        emission_order: list[str] = []
        with self._engine_store(store_a_path) as a, self._engine_store(store_b_path) as b:
            for i in range(4):
                emission_order.append(a.append({
                    "kind": "evt", "ts": _BASE_TS, "observer": "a", "payload": {"i": i},
                }))
                _time.sleep(0.002)
                emission_order.append(b.append({
                    "kind": "evt", "ts": _BASE_TS, "observer": "b", "payload": {"i": i},
                }))
                _time.sleep(0.002)

        # Merge a → merged, then b → merged
        with self._engine_store(merged_path):
            pass
        merge_store(merged_path, store_a_path)
        merge_store(merged_path, store_b_path)

        conn = sqlite3.connect(str(merged_path))
        try:
            id_order = [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY id").fetchall()]
        finally:
            conn.close()

        assert id_order == emission_order, (
            "ORDER BY id after cross-store merge does not match emission order. "
            "Under uuid4 this fails (random ids); under ULID it passes "
            "(millisecond-timestamp prefix interleaves across stores)."
        )


class TestMergeFoldCommutativity:
    """merge(A,B) and merge(B,A) must re-fold to the same state.

    Fold replay orders by (ts, id) — a store-independent total order — so
    the direction of a merge changes the witness history (rowid) but never
    the semantics. Pinned against the loops-go oracle finding that scan-
    order insertion + rowid replay made merge non-commutative for
    order-sensitive folds (thread:python-bugs-from-go-oracle).
    """

    @staticmethod
    def _engine_store(path):
        from engine.sqlite_store import SqliteStore

        def _serialize(f):
            return {"kind": f["kind"], "ts": f["ts"], "observer": f["observer"],
                    "origin": f.get("origin", ""), "payload": f.get("payload", {})}

        return SqliteStore(path=path, serialize=_serialize, deserialize=lambda d: d)

    def _emit(self, path, facts):
        with self._engine_store(path) as store:
            for ts, payload in facts:
                store.append({
                    "kind": "event", "ts": ts, "observer": "x",
                    "payload": payload,
                })

    @staticmethod
    def _replayed(path):
        """Replay via the production raw path, return ordered payload list."""
        from engine.sqlite_store import SqliteStore

        with SqliteStore(path=path, serialize=lambda d: d,
                         deserialize=lambda d: d) as store:
            return [p for _, p in store.since_raw(0)]

    def test_merge_direction_does_not_change_fold_order(self, tmp_path):
        a_facts = [(_BASE_TS + 0, {"n": "a0"}), (_BASE_TS + 2, {"n": "a1"})]
        b_facts = [(_BASE_TS + 1, {"n": "b0"}), (_BASE_TS + 3, {"n": "b1"})]

        a1, b1 = tmp_path / "a1.db", tmp_path / "b1.db"
        a2, b2 = tmp_path / "a2.db", tmp_path / "b2.db"
        self._emit(a1, a_facts)
        self._emit(b1, b_facts)
        self._emit(a2, a_facts)
        self._emit(b2, b_facts)

        merge_store(a1, b1)  # A ← B
        merge_store(b2, a2)  # B ← A

        order_ab = [p["n"] for p in self._replayed(a1)]
        order_ba = [p["n"] for p in self._replayed(b2)]
        assert order_ab == order_ba == ["a0", "b0", "a1", "b1"]


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
