"""Tests for SqliteStore — SQLite-backed append-only event store."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from vertex import Store
from vertex.sqlite_store import SqliteStore

from tests.helpers import (
    TimestampedEvent,
    deserialize_timestamped,
    serialize_timestamped,
)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def make_store(path: Path) -> SqliteStore[TimestampedEvent]:
    return SqliteStore(
        path=path,
        serialize=serialize_timestamped,
        deserialize=deserialize_timestamped,
    )


# --- Fact-shaped helpers (SqliteStore extracts kind/ts/observer/payload) ---

def serialize_fact(e: TimestampedEvent) -> dict:
    return {"kind": "test", "ts": e.ts, "observer": "test", "payload": {"value": e.value}}


def deserialize_fact(d: dict) -> TimestampedEvent:
    return TimestampedEvent(value=d["payload"]["value"], ts=d["ts"])


def make_fact_store(path: Path) -> SqliteStore[TimestampedEvent]:
    return SqliteStore(
        path=path,
        serialize=serialize_fact,
        deserialize=deserialize_fact,
    )


class TestProtocol:
    def test_sqlite_store_is_store(self, tmp_db: Path):
        store = make_fact_store(tmp_db)
        assert isinstance(store, Store)
        store.close()


class TestAppendAndSince:
    def test_since_zero_returns_all(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            store.append(TimestampedEvent(value=2, ts=200.0))

            result = store.since(0)
            assert len(result) == 2
            assert result[0].value == 1
            assert result[1].value == 2

    def test_since_cursor_skips_earlier(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            store.append(TimestampedEvent(value=2, ts=200.0))
            store.append(TimestampedEvent(value=3, ts=300.0))

            # rowid 1 and 2 inserted, since(2) should skip them
            result = store.since(2)
            assert len(result) == 1
            assert result[0].value == 3

    def test_since_beyond_total_returns_empty(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            assert store.since(10) == []

    def test_total_property(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            assert store.total == 0
            store.append(TimestampedEvent(value=1, ts=100.0))
            assert store.total == 1
            store.append(TimestampedEvent(value=2, ts=200.0))
            assert store.total == 2


class TestBetween:
    def test_returns_events_in_range(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            store.append(TimestampedEvent(value=2, ts=200.0))
            store.append(TimestampedEvent(value=3, ts=300.0))

            result = store.between(150.0, 250.0)
            assert len(result) == 1
            assert result[0].value == 2

    def test_inclusive_boundaries(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            store.append(TimestampedEvent(value=2, ts=200.0))
            store.append(TimestampedEvent(value=3, ts=300.0))

            result = store.between(100.0, 300.0)
            assert len(result) == 3

    def test_excludes_outside_range(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            result = store.between(400.0, 500.0)
            assert result == []

    def test_with_datetime(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
            t3 = datetime(2025, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

            store.append(TimestampedEvent(value=1, ts=t1.timestamp()))
            store.append(TimestampedEvent(value=2, ts=t2.timestamp()))
            store.append(TimestampedEvent(value=3, ts=t3.timestamp()))

            result = store.between(t1, t2)
            assert len(result) == 2

    def test_empty_store(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            result = store.between(0.0, 1000.0)
            assert result == []


class TestPersistence:
    def test_survives_close_and_reopen(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=10, ts=100.0))
            store.append(TimestampedEvent(value=20, ts=200.0))

        with make_fact_store(tmp_db) as store2:
            assert store2.total == 2
            result = store2.since(0)
            assert result[0].value == 10
            assert result[1].value == 20

    def test_creates_parent_directories(self, tmp_path: Path):
        db_path = tmp_path / "nested" / "dir" / "test.db"
        with make_fact_store(db_path) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
        assert db_path.exists()


class TestContextManager:
    def test_close_idempotent(self, tmp_db: Path):
        store = make_fact_store(tmp_db)
        store.close()
        store.close()  # no error

    def test_with_statement(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            assert store.total == 1


class TestConsume:
    async def test_consume_protocol(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            await store.consume(TimestampedEvent(value=5, ts=100.0))
            assert store.total == 1


# --- Tick Persistence ---

from vertex import Tick


NOW_DT = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
EARLIER_DT = datetime(2025, 6, 1, 11, 0, 0, tzinfo=timezone.utc)


class TestTickPersistence:
    def test_append_tick_and_retrieve(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            tick = Tick(name="metric", ts=NOW_DT, payload={"count": 5}, origin="v1")
            store.append_tick(tick)

            ticks = store.ticks_since(0)
            assert len(ticks) == 1
            assert ticks[0].name == "metric"
            assert ticks[0].ts == NOW_DT
            assert ticks[0].payload == {"count": 5}
            assert ticks[0].origin == "v1"

    def test_ticks_between(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            t1 = Tick(name="a", ts=datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc), payload=1, origin="v")
            t2 = Tick(name="b", ts=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc), payload=2, origin="v")
            t3 = Tick(name="c", ts=datetime(2025, 6, 1, 14, 0, 0, tzinfo=timezone.utc), payload=3, origin="v")
            store.append_tick(t1)
            store.append_tick(t2)
            store.append_tick(t3)

            result = store.ticks_between(
                datetime(2025, 6, 1, 11, 0, 0, tzinfo=timezone.utc),
                datetime(2025, 6, 1, 13, 0, 0, tzinfo=timezone.utc),
            )
            assert len(result) == 1
            assert result[0].name == "b"

    def test_tick_with_since(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            tick = Tick(name="loop", ts=NOW_DT, payload=42, origin="v1", since=EARLIER_DT)
            store.append_tick(tick)

            ticks = store.ticks_since(0)
            assert ticks[0].since == EARLIER_DT

    def test_tick_survives_reopen(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            tick = Tick(name="durable", ts=NOW_DT, payload={"x": 1}, origin="v1", since=EARLIER_DT)
            store.append_tick(tick)

        with make_fact_store(tmp_db) as store2:
            ticks = store2.ticks_since(0)
            assert len(ticks) == 1
            assert ticks[0].name == "durable"
            assert ticks[0].since == EARLIER_DT

    def test_tick_total(self, tmp_db: Path):
        with make_fact_store(tmp_db) as store:
            assert store.tick_total == 0
            store.append_tick(Tick(name="a", ts=NOW_DT, payload=1, origin="v"))
            assert store.tick_total == 1
            store.append_tick(Tick(name="b", ts=NOW_DT, payload=2, origin="v"))
            assert store.tick_total == 2
