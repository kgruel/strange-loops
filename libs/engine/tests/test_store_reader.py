"""Tests for StoreReader — read-only inspector for SqliteStore databases."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from engine.store_reader import StoreReader

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS facts (
    id TEXT NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL,
    ts REAL NOT NULL,
    observer TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts);

CREATE TABLE IF NOT EXISTS ticks (
    id TEXT NOT NULL PRIMARY KEY,
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
        "INSERT INTO facts (id, kind, ts, observer, payload) VALUES (?, ?, ?, ?, ?)",
        ("01FACT_PAGE_A", "page", 100.0, "scraper", '{"url": "a"}'),
    )
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, payload) VALUES (?, ?, ?, ?, ?)",
        ("01FACT_PAGE_B", "page", 200.0, "scraper", '{"url": "b"}'),
    )
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, payload) VALUES (?, ?, ?, ?, ?)",
        ("01FACT_ERROR1", "error", 150.0, "scraper", '{"msg": "fail"}'),
    )
    # Three ticks, two names
    for i, (name, ts, payload) in enumerate([
        ("scrape", 1000.0, {"n": 1}),
        ("scrape", 2000.0, {"n": 2}),
        ("health", 1500.0, {}),
    ]):
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (f"01TICK_{i}", name, ts, None, "v1", json.dumps(payload)),
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
                "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (f"01TICK_LIM{i}", "m", float(i * 100), None, "v", json.dumps(i)),
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


class TestTicksBetween:
    def test_returns_ticks_in_range(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            ticks = reader.ticks_between(900.0, 1600.0)
            assert len(ticks) == 2
            names = [t.name for t in ticks]
            assert "scrape" in names
            assert "health" in names

    def test_filters_by_name(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            ticks = reader.ticks_between(0, float("inf"), name="scrape")
            assert len(ticks) == 2
            assert all(t.name == "scrape" for t in ticks)

    def test_name_and_range_combined(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            ticks = reader.ticks_between(1500.0, 2500.0, name="scrape")
            assert len(ticks) == 1
            assert ticks[0].payload == {"n": 2}

    def test_empty_range(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            ticks = reader.ticks_between(5000.0, 6000.0)
            assert ticks == []

    def test_unknown_name(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            ticks = reader.ticks_between(0, float("inf"), name="nonexistent")
            assert ticks == []

    def test_ordered_by_ts(self, tmp_db: Path):
        conn = sqlite3.connect(str(tmp_db))
        for i, ts in enumerate([300.0, 100.0, 200.0]):
            conn.execute(
                "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (f"01TICK_ORD{i}", "x", ts, None, "v", json.dumps({"t": ts})),
            )
        conn.commit()
        conn.close()

        with StoreReader(tmp_db) as reader:
            ticks = reader.ticks_between(0, 500.0)
            timestamps = [t.ts.timestamp() for t in ticks]
            assert timestamps == sorted(timestamps)


class TestFactById:
    def test_exact_match(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            fact = reader.fact_by_id("01FACT_PAGE_A")
            assert fact is not None
            assert fact["id"] == "01FACT_PAGE_A"
            assert fact["kind"] == "page"
            assert fact["payload"] == {"url": "a"}

    def test_prefix_match(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            fact = reader.fact_by_id("01FACT_ERROR")
            assert fact is not None
            assert fact["id"] == "01FACT_ERROR1"
            assert fact["kind"] == "error"

    def test_prefix_ambiguous(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            # "01FACT_PAGE" matches both PAGE_A and PAGE_B
            with pytest.raises(ValueError, match="Ambiguous"):
                reader.fact_by_id("01FACT_PAGE")

    def test_not_found(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            assert reader.fact_by_id("NONEXISTENT") is None

    def test_facts_include_id(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            facts = reader.facts_between(0, 300.0)
            assert all("id" in f for f in facts)
            ids = {f["id"] for f in facts}
            assert "01FACT_PAGE_A" in ids


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


class TestTickTimestamps:
    def test_returns_timestamps_desc(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            ts = reader.tick_timestamps("scrape")
            assert ts == [2000.0, 1000.0]

    def test_with_limit(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            ts = reader.tick_timestamps("scrape", limit=1)
            assert ts == [2000.0]

    def test_unknown_name(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            assert reader.tick_timestamps("missing") == []


class TestFreshness:
    def test_returns_latest_ts(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            f = reader.freshness
            assert f is not None
            assert isinstance(f, datetime)
            # ts=200.0 is the max fact ts in populated_db
            assert f.timestamp() == pytest.approx(200.0, abs=1)

    def test_empty_store_returns_none(self, tmp_db: Path):
        with StoreReader(tmp_db) as reader:
            assert reader.freshness is None


class TestResolveEntityId:
    def test_finds_matching_fact(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            id_ = reader.resolve_entity_id("page", "url", "b")
            assert id_ == "01FACT_PAGE_B"

    def test_returns_none_when_no_match(self, populated_db: Path):
        with StoreReader(populated_db) as reader:
            assert reader.resolve_entity_id("page", "url", "missing") is None


# ---------------------------------------------------------------------------
# Containment-stat queries (ls-as-stat-over-containment) — fact_key_stats,
# fact_observer_stats, fact_density_by_kind, signed_counts
# ---------------------------------------------------------------------------


@pytest.fixture
def keyed_db(tmp_path: Path) -> Path:
    """A store with namespaced fold keys, an orphan, and a signature column."""
    db_path = tmp_path / "keyed.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA.replace(
        "payload TEXT NOT NULL\n);",
        "payload TEXT NOT NULL,\n    signature TEXT\n);",
    ))
    rows = [
        # id, kind, ts, observer, payload, signature
        ("d1", "decision", 100.0, "kyle", '{"topic": "design/a"}', "sig"),
        ("d2", "decision", 300.0, "kyle", '{"topic": "design/b"}', "sig"),
        ("d3", "decision", 200.0, "meta", '{"topic": "design/a"}', None),
        ("d4", "decision", 400.0, "kyle", '{"topic": "arch/x"}', "sig"),
        ("d5", "decision", 250.0, "kyle", '{}', None),  # orphan — no topic
    ]
    conn.executemany(
        "INSERT INTO facts (id, kind, ts, observer, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?)", rows,
    )
    conn.commit()
    conn.close()
    return db_path


class TestFactKeyStats:
    def test_groups_by_fold_key(self, keyed_db: Path):
        with StoreReader(keyed_db) as reader:
            ks = reader.fact_key_stats("decision", "topic")
        assert ks["design/a"]["count"] == 2
        assert ks["design/b"]["count"] == 1
        assert ks["arch/x"]["count"] == 1
        # latest is the MAX ts of the group (design/a: 100, 200 -> 200)
        assert ks["design/a"]["latest"].timestamp() == pytest.approx(200.0, abs=1)

    def test_none_bucket_collects_orphans(self, keyed_db: Path):
        """A fact missing the fold key groups under None — the orphan diagnostic."""
        with StoreReader(keyed_db) as reader:
            ks = reader.fact_key_stats("decision", "topic")
        assert None in ks
        assert ks[None]["count"] == 1

    def test_count_descending(self, keyed_db: Path):
        with StoreReader(keyed_db) as reader:
            ks = reader.fact_key_stats("decision", "topic")
        counts = [v["count"] for v in ks.values()]
        assert counts == sorted(counts, reverse=True)


class TestFactObserverStats:
    def test_groups_by_observer(self, keyed_db: Path):
        with StoreReader(keyed_db) as reader:
            obs = reader.fact_observer_stats("decision")
        assert obs["kyle"]["count"] == 4
        assert obs["meta"]["count"] == 1


class TestFactDensityByKind:
    def test_buckets_activity_on_shared_axis(self, keyed_db: Path):
        with StoreReader(keyed_db) as reader:
            # span 100..400, 3 buckets -> width 100 each
            dens = reader.fact_density_by_kind(since=100.0, until=400.0, buckets=3)
        # decision facts at ts 100,200,250,300,400 -> buckets [0,1,1,2,2]
        assert dens["decision"] == [1, 2, 2]
        assert sum(dens["decision"]) == 5

    def test_window_excludes_out_of_range(self, keyed_db: Path):
        with StoreReader(keyed_db) as reader:
            dens = reader.fact_density_by_kind(since=250.0, until=400.0, buckets=2)
        # only ts 250,300,400 in window
        assert sum(dens["decision"]) == 3


class TestSignedCounts:
    def test_counts_signed_when_column_present(self, keyed_db: Path):
        with StoreReader(keyed_db) as reader:
            sc = reader.signed_counts()
        # 3 of 5 facts have a non-NULL signature
        assert sc == (3, 5)

    def test_returns_none_when_column_absent(self, populated_db: Path):
        """Pre-signature schemas (no signature column) return None, not raise."""
        with StoreReader(populated_db) as reader:
            assert reader.signed_counts() is None


@pytest.fixture
def decl_db(tmp_db: Path) -> Path:
    """Database mixing ordinary kinds with the reserved `_decl.*` namespace.

    S3 (SPEC §9.4): every read surface excludes `_decl.*` by default, with
    an explicit escape hatch. This fixture exercises both.
    """
    conn = sqlite3.connect(str(tmp_db))
    rows = [
        ("01FACT_DEC1", "decision", 100.0, "kyle", '{"topic": "auth"}'),
        ("01FACT_DEC2", "decision", 200.0, "kyle", '{"topic": "auth"}'),
        ("01FACT_GEN1", "_decl.genesis", 50.0, "kyle", '{"lineage": "abc123secret"}'),
        ("01FACT_KDEF1", "_decl.kind-defined", 60.0, "kyle", '{"subject": "decision"}'),
    ]
    for row_id, kind, ts, observer, payload in rows:
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, payload) VALUES (?, ?, ?, ?, ?)",
            (row_id, kind, ts, observer, payload),
        )
    conn.commit()
    conn.close()
    return tmp_db


class TestInternalKindExclusion:
    """SPEC §9.4 — `_decl.*` excluded by default, `include_internal=True` defeats it."""

    def test_fact_kind_stats_excludes_by_default(self, decl_db: Path):
        with StoreReader(decl_db) as reader:
            stats = reader.fact_kind_stats()
        assert set(stats.keys()) == {"decision"}

    def test_fact_kind_stats_include_internal_defeat(self, decl_db: Path):
        with StoreReader(decl_db) as reader:
            stats = reader.fact_kind_stats(include_internal=True)
        assert set(stats.keys()) == {"decision", "_decl.genesis", "_decl.kind-defined"}
        assert stats["_decl.genesis"]["count"] == 1

    def test_summary_excludes_by_default(self, decl_db: Path):
        with StoreReader(decl_db) as reader:
            s = reader.summary()
        assert set(s["facts"]["kinds"].keys()) == {"decision"}
        # total is the RAW fact count, not narrowed by the kinds exclusion —
        # only the per-kind breakdown is filtered.
        assert s["facts"]["total"] == 4

    def test_summary_include_internal_defeat(self, decl_db: Path):
        with StoreReader(decl_db) as reader:
            s = reader.summary(include_internal=True)
        assert "_decl.genesis" in s["facts"]["kinds"]

    def test_facts_between_excludes_by_default(self, decl_db: Path):
        with StoreReader(decl_db) as reader:
            facts = reader.facts_between(0.0, 1000.0)
        assert {f["kind"] for f in facts} == {"decision"}

    def test_facts_between_include_internal_defeat(self, decl_db: Path):
        with StoreReader(decl_db) as reader:
            facts = reader.facts_between(0.0, 1000.0, include_internal=True)
        assert {f["kind"] for f in facts} == {"decision", "_decl.genesis", "_decl.kind-defined"}

    def test_facts_between_explicit_internal_kind_needs_defeat(self, decl_db: Path):
        """Narrowing to an internal kind WITHOUT the defeat still returns empty —
        the ambient exclusion applies to the kind filter too, not just the
        no-kind ambient case. Callers must pass include_internal explicitly."""
        with StoreReader(decl_db) as reader:
            facts = reader.facts_between(0.0, 1000.0, kind="_decl.genesis")
        assert facts == []

        with StoreReader(decl_db) as reader:
            facts = reader.facts_between(
                0.0, 1000.0, kind="_decl.genesis", include_internal=True
            )
        assert len(facts) == 1
        assert facts[0]["kind"] == "_decl.genesis"
