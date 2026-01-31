"""Tests for Store protocol and FileStore implementation."""

from pathlib import Path

from vertex import EventStore, FileStore, Store

from tests.helpers import Event, deserialize_event, serialize_event


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
