"""Tests for Store protocol and FileStore implementation."""

from datetime import datetime, timezone
from pathlib import Path

from engine import EventStore, FileStore, Store

from tests.helpers import (
    Event,
    TimestampedEvent,
    deserialize_event,
    deserialize_timestamped,
    serialize_event,
    serialize_timestamped,
)


class TestStoreProtocol:
    """Store protocol conformance."""

    def test_event_store_is_store(self):
        store = EventStore[Event]()
        assert isinstance(store, Store)

    def test_file_store_is_store(self, tmp_jsonl: Path):
        store = FileStore(tmp_jsonl, serialize_event, deserialize_event)
        store.close()
        assert isinstance(store, Store)


class TestFileStore:
    """FileStore — JSONL-backed store."""

    def test_append_and_since(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store:
            store.append(Event(1))
            store.append(Event(2))

            assert store.since(0) == [Event(1), Event(2)]
            assert store.since(1) == [Event(2)]
            assert store.since(2) == []

    def test_persists_to_file(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store:
            store.append(Event(10))
            store.append(Event(20))

        # Reload from same file
        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store2:
            assert store2.events == [Event(10), Event(20)]
            assert store2.total == 2

    def test_loads_existing_on_init(self, tmp_jsonl: Path):
        tmp_jsonl.write_text('{"value": 1}\n{"value": 2}\n')

        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store:
            assert len(store.events) == 2
            assert store.events[0].value == 1

    def test_total_property(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store:
            assert store.total == 0
            store.append(Event(1))
            assert store.total == 1

    def test_close_idempotent(self, tmp_jsonl: Path):
        store = FileStore(tmp_jsonl, serialize_event, deserialize_event)
        store.close()
        store.close()  # no error on second close

    async def test_consume_protocol(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store:
            await store.consume(Event(5))
            assert store.events == [Event(5)]

    def test_blank_lines_in_file(self, tmp_jsonl: Path):
        tmp_jsonl.write_text('{"value": 1}\n\n{"value": 2}\n')

        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store:
            assert len(store.events) == 2

    def test_nonexistent_file_creates_on_append(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_event, deserialize_event) as store:
            store.append(Event(1))

        assert tmp_jsonl.exists()
        assert tmp_jsonl.read_text() == '{"value": 1}\n'


class TestEventStoreBetween:
    """EventStore.between() — time-range queries for fidelity traversal."""

    def test_between_returns_events_in_range(self):
        store: EventStore[TimestampedEvent] = EventStore()
        store.append(TimestampedEvent(value=1, ts=100.0))
        store.append(TimestampedEvent(value=2, ts=200.0))
        store.append(TimestampedEvent(value=3, ts=300.0))

        result = store.between(150.0, 250.0)
        assert len(result) == 1
        assert result[0].value == 2

    def test_between_inclusive_boundaries(self):
        store: EventStore[TimestampedEvent] = EventStore()
        store.append(TimestampedEvent(value=1, ts=100.0))
        store.append(TimestampedEvent(value=2, ts=200.0))
        store.append(TimestampedEvent(value=3, ts=300.0))

        # Exact boundary match should be included
        result = store.between(100.0, 300.0)
        assert len(result) == 3

    def test_between_excludes_outside_range(self):
        store: EventStore[TimestampedEvent] = EventStore()
        store.append(TimestampedEvent(value=1, ts=100.0))
        store.append(TimestampedEvent(value=2, ts=200.0))
        store.append(TimestampedEvent(value=3, ts=300.0))

        result = store.between(400.0, 500.0)
        assert result == []

    def test_between_with_datetime(self):
        store: EventStore[TimestampedEvent] = EventStore()
        t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2025, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        store.append(TimestampedEvent(value=1, ts=t1.timestamp()))
        store.append(TimestampedEvent(value=2, ts=t2.timestamp()))
        store.append(TimestampedEvent(value=3, ts=t3.timestamp()))

        # Query with datetime objects
        result = store.between(t1, t2)
        assert len(result) == 2
        assert result[0].value == 1
        assert result[1].value == 2

    def test_between_empty_store(self):
        store: EventStore[TimestampedEvent] = EventStore()
        result = store.between(0.0, 1000.0)
        assert result == []

    def test_between_mixed_datetime_and_float(self):
        store: EventStore[TimestampedEvent] = EventStore()
        t = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        store.append(TimestampedEvent(value=1, ts=t.timestamp()))

        # datetime start, float end
        result = store.between(t, t.timestamp() + 1)
        assert len(result) == 1


class TestFileStoreBetween:
    """FileStore.between() — time-range queries for fidelity traversal."""

    def test_between_returns_events_in_range(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_timestamped, deserialize_timestamped) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            store.append(TimestampedEvent(value=2, ts=200.0))
            store.append(TimestampedEvent(value=3, ts=300.0))

            result = store.between(150.0, 250.0)
            assert len(result) == 1
            assert result[0].value == 2

    def test_between_with_datetime(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_timestamped, deserialize_timestamped) as store:
            t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

            store.append(TimestampedEvent(value=1, ts=t1.timestamp()))
            store.append(TimestampedEvent(value=2, ts=t2.timestamp()))

            result = store.between(t1, t2)
            assert len(result) == 2

    def test_between_inclusive_boundaries(self, tmp_jsonl: Path):
        with FileStore(tmp_jsonl, serialize_timestamped, deserialize_timestamped) as store:
            store.append(TimestampedEvent(value=1, ts=100.0))
            store.append(TimestampedEvent(value=2, ts=200.0))

            result = store.between(100.0, 200.0)
            assert len(result) == 2
