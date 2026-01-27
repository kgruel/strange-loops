"""Behavior tests: edge cases and error paths.

These tests cover specific behaviors not exercised by integration tests.
Focus on public API behavior, not implementation details.
"""

from pathlib import Path

import pytest

from ticks import EventStore, FileWriter, Projection, Stream, Tailer

from tests.helpers import (
    Event,
    SumProjection,
    deserialize_event,
    serialize_event,
)


class TestStreamDetach:
    """Stream.detach() behavior."""

    async def test_detach_removes_tap(self, stream: Stream[Event]):
        proj = SumProjection(initial=0)
        tap = stream.tap(proj)

        assert stream.tap_count == 1
        stream.detach(tap)
        assert stream.tap_count == 0

    async def test_detach_during_emit(self, stream: Stream[Event]):
        """Consumer can detach during emit without breaking iteration."""
        proj1 = SumProjection(initial=0)
        proj2 = SumProjection(initial=0)

        tap1 = stream.tap(proj1)
        stream.tap(proj2)

        # First consumer detaches itself after first emit
        await stream.emit(Event(1))
        stream.detach(tap1)
        await stream.emit(Event(2))

        assert proj1.state == 1  # only got first event
        assert proj2.state == 3  # got both

    async def test_detach_already_detached_is_noop(self, stream: Stream[Event]):
        proj = SumProjection(initial=0)
        tap = stream.tap(proj)

        stream.detach(tap)
        stream.detach(tap)  # no error on second detach

        assert stream.tap_count == 0


class TestEventStoreEdgeCases:
    """EventStore edge cases and error handling."""

    def test_path_requires_serialize_and_deserialize(self, tmp_jsonl: Path):
        with pytest.raises(ValueError, match="path requires both"):
            EventStore[Event](path=tmp_jsonl, serialize=serialize_event)

        with pytest.raises(ValueError, match="path requires both"):
            EventStore[Event](path=tmp_jsonl, deserialize=deserialize_event)

    def test_close_when_no_file(self):
        store = EventStore[Event]()
        store.close()  # should not raise

    def test_context_manager_without_file(self):
        with EventStore[Event]() as store:
            store.append(Event(1))
        assert store.events == [Event(1)]

    def test_total_tracks_logical_count(self):
        store = EventStore[Event]()
        store.append(Event(1))
        store.append(Event(2))

        assert store.total == 2

    def test_since_returns_events_from_cursor(self):
        store = EventStore[Event]()
        store.append(Event(1))
        store.append(Event(2))
        store.append(Event(3))

        assert store.since(0) == [Event(1), Event(2), Event(3)]
        assert store.since(1) == [Event(2), Event(3)]
        assert store.since(3) == []

    def test_evict_below_removes_old_events(self):
        store = EventStore[Event]()
        store.append(Event(1))
        store.append(Event(2))
        store.append(Event(3))

        store.evict_below(2)

        # since() still works with cursors >= 2
        assert store.since(2) == [Event(3)]
        assert store.total == 3  # logical count unchanged

    def test_evict_below_raises_on_old_cursor(self):
        store = EventStore[Event]()
        store.append(Event(1))
        store.append(Event(2))

        store.evict_below(1)

        with pytest.raises(IndexError, match="below eviction watermark"):
            store.since(0)

    def test_evict_below_noop_when_already_evicted(self):
        store = EventStore[Event]()
        store.append(Event(1))
        store.append(Event(2))

        store.evict_below(1)
        store.evict_below(0)  # no-op, already past 0

        assert store.since(1) == [Event(2)]

    def test_evict_beyond_total_clamps(self):
        store = EventStore[Event]()
        store.append(Event(1))
        store.append(Event(2))

        store.evict_below(10)  # beyond current total

        assert store.events == []
        # offset becomes the eviction point, total reflects that
        assert store.total == 10

    def test_load_file_with_blank_lines(self, tmp_jsonl: Path):
        # Write file with blank lines
        tmp_jsonl.write_text('{"value": 1}\n\n{"value": 2}\n')

        store = EventStore[Event](
            path=tmp_jsonl,
            serialize=serialize_event,
            deserialize=deserialize_event,
        )
        store.close()

        assert len(store.events) == 2


class TestProjectionBehavior:
    """Projection behavior edge cases."""

    def test_name_returns_class_name(self):
        proj = SumProjection(initial=0)
        assert proj.name == "SumProjection"

    async def test_version_unchanged_when_state_identity_same(self):
        """Version only bumps when state changes."""

        class IdentityProjection(Projection[list, Event]):
            def apply(self, state: list, event: Event) -> list:
                state.append(event.value)  # mutate in place
                return state  # return same object

        proj = IdentityProjection(initial=[])
        await proj.consume(Event(1))

        # State mutated but identity same, version unchanged
        assert proj.state == [1]
        assert proj.version == 0

    def test_advance_noop_when_no_new_events(self):
        store = EventStore[Event]()
        proj = SumProjection(initial=0)

        proj.advance(store)

        assert proj.state == 0
        assert proj.version == 0

    def test_advance_version_unchanged_when_state_identity_same(self):
        """advance() only bumps version when state changes."""

        class IdentityProjection(Projection[list, Event]):
            def apply(self, state: list, event: Event) -> list:
                state.append(event.value)
                return state

        store = EventStore[Event]()
        store.append(Event(1))

        proj = IdentityProjection(initial=[])
        proj.advance(store)

        assert proj.state == [1]
        assert proj.version == 0  # same identity


class TestProjectionReset:
    """Projection.reset() behavior."""

    def test_reset_changes_state(self):
        proj = SumProjection(initial=0)
        proj.fold_one(Event(10))
        assert proj.state == 10

        proj.reset(0)
        assert proj.state == 0

    def test_reset_bumps_version(self):
        proj = SumProjection(initial=0)
        assert proj.version == 0

        proj.reset(42)
        assert proj.version == 1

    def test_reset_preserves_cursor(self):
        proj = SumProjection(initial=0)
        proj.fold_one(Event(1))
        proj.fold_one(Event(2))
        assert proj.cursor == 2

        proj.reset(0)
        assert proj.cursor == 2


class TestFileWriterBehavior:
    """FileWriter edge cases."""

    def test_close_when_already_closed(self, tmp_jsonl: Path):
        writer = FileWriter(tmp_jsonl, serialize_event)
        writer.close()
        writer.close()  # no error on second close

    async def test_context_manager(self, tmp_jsonl: Path):
        with FileWriter(tmp_jsonl, serialize_event) as writer:
            await writer.consume(Event(1))

        # File is closed after context
        assert tmp_jsonl.read_text() == '{"value": 1}\n'


class TestTailerBehavior:
    """Tailer behavior and edge cases."""

    def test_offset_getter_and_setter(self, tmp_jsonl: Path):
        tailer = Tailer(tmp_jsonl, deserialize_event)

        assert tailer.offset == 0
        tailer.offset = 100
        assert tailer.offset == 100

    def test_poll_nonexistent_file(self, tmp_jsonl: Path):
        tailer = Tailer(tmp_jsonl, deserialize_event)

        events = tailer.poll()

        assert events == []

    def test_poll_empty_file(self, tmp_jsonl: Path):
        tmp_jsonl.touch()
        tailer = Tailer(tmp_jsonl, deserialize_event)

        events = tailer.poll()

        assert events == []

    def test_poll_incomplete_line(self, tmp_jsonl: Path):
        # Write incomplete JSON (no trailing newline)
        tmp_jsonl.write_text('{"value": 1}')
        tailer = Tailer(tmp_jsonl, deserialize_event)

        events = tailer.poll()

        assert events == []  # incomplete line not processed
        assert tailer.offset == 0  # offset not advanced

    def test_poll_complete_then_incomplete(self, tmp_jsonl: Path):
        # One complete line, one incomplete
        tmp_jsonl.write_text('{"value": 1}\n{"value": 2}')
        tailer = Tailer(tmp_jsonl, deserialize_event)

        events = tailer.poll()

        assert len(events) == 1
        assert events[0].value == 1

    def test_poll_with_blank_lines(self, tmp_jsonl: Path):
        tmp_jsonl.write_text('{"value": 1}\n\n{"value": 2}\n')
        tailer = Tailer(tmp_jsonl, deserialize_event)

        events = tailer.poll()

        assert len(events) == 2

    def test_reset_returns_to_beginning(self, tmp_jsonl: Path):
        tmp_jsonl.write_text('{"value": 1}\n')
        tailer = Tailer(tmp_jsonl, deserialize_event)

        tailer.poll()
        assert tailer.offset > 0

        tailer.reset()
        assert tailer.offset == 0

        # Can re-read from beginning
        events = tailer.poll()
        assert len(events) == 1
