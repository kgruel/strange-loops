"""Integration tests: full paths through the system.

These tests verify that primitives compose correctly. They exercise
the public API and test behavior, not implementation details.
"""

from pathlib import Path

import pytest

from ticks import EventStore, FileWriter, Forward, Projection, Stream, Tailer

from tests.helpers import (
    CountProjection,
    Event,
    NamedEvent,
    NamedSumProjection,
    SumProjection,
    deserialize_event,
    deserialize_named,
    serialize_event,
    serialize_named,
)


class TestStreamToProjection:
    """Stream emits -> Projection folds -> state updates."""

    async def test_emit_updates_projection_state(
        self, stream: Stream[Event], sum_projection: SumProjection
    ):
        stream.tap(sum_projection)

        await stream.emit(Event(10))
        await stream.emit(Event(5))
        await stream.emit(Event(3))

        assert sum_projection.state == 18

    async def test_emit_increments_projection_version(
        self, stream: Stream[Event], sum_projection: SumProjection
    ):
        stream.tap(sum_projection)
        assert sum_projection.version == 0

        await stream.emit(Event(1))
        assert sum_projection.version == 1

        await stream.emit(Event(2))
        assert sum_projection.version == 2

    async def test_projection_cursor_tracks_events(
        self, stream: Stream[Event], sum_projection: SumProjection
    ):
        stream.tap(sum_projection)

        await stream.emit(Event(1))
        await stream.emit(Event(2))

        assert sum_projection.cursor == 2


class TestStreamToEventStore:
    """Stream emits -> EventStore appends -> events available."""

    async def test_emit_adds_to_store(
        self, stream: Stream[Event], event_store: EventStore[Event]
    ):
        stream.tap(event_store)

        await stream.emit(Event(1))
        await stream.emit(Event(2))

        assert len(event_store.events) == 2
        assert event_store.events[0].value == 1
        assert event_store.events[1].value == 2

    async def test_emit_increments_store_version(
        self, stream: Stream[Event], event_store: EventStore[Event]
    ):
        stream.tap(event_store)
        assert event_store.version == 0

        await stream.emit(Event(1))
        assert event_store.version == 1


class TestStreamFanOut:
    """Stream emits -> multiple consumers receive."""

    async def test_emit_reaches_all_taps(self, stream: Stream[Event]):
        proj1 = SumProjection(initial=0)
        proj2 = SumProjection(initial=100)
        store = EventStore[Event]()

        stream.tap(proj1)
        stream.tap(proj2)
        stream.tap(store)

        await stream.emit(Event(10))

        assert proj1.state == 10
        assert proj2.state == 110
        assert len(store.events) == 1


class TestStreamFiltering:
    """Stream with filter -> only matching events reach consumer."""

    async def test_filter_blocks_non_matching(
        self, stream: Stream[Event], sum_projection: SumProjection
    ):
        stream.tap(sum_projection, filter=lambda e: e.value > 5)

        await stream.emit(Event(3))  # blocked
        await stream.emit(Event(10))  # passes
        await stream.emit(Event(2))  # blocked

        assert sum_projection.state == 10

    async def test_filter_does_not_affect_other_taps(self, stream: Stream[Event]):
        filtered = SumProjection(initial=0)
        unfiltered = SumProjection(initial=0)

        stream.tap(filtered, filter=lambda e: e.value > 5)
        stream.tap(unfiltered)

        await stream.emit(Event(3))
        await stream.emit(Event(10))

        assert filtered.state == 10
        assert unfiltered.state == 13


class TestStreamTransform:
    """Stream with transform -> events modified before delivery."""

    async def test_transform_modifies_event(
        self, stream: Stream[Event], sum_projection: SumProjection
    ):
        stream.tap(sum_projection, transform=lambda e: Event(e.value * 2))

        await stream.emit(Event(5))

        assert sum_projection.state == 10


class TestEventStoreToProjection:
    """EventStore advances -> Projection catches up."""

    async def test_projection_advance_catches_up(self, event_store: EventStore[Event]):
        event_store.add(Event(1))
        event_store.add(Event(2))
        event_store.add(Event(3))

        proj = SumProjection(initial=0)
        proj.advance(event_store)

        assert proj.state == 6
        assert proj.cursor == 3

    async def test_projection_advance_is_incremental(
        self, event_store: EventStore[Event]
    ):
        proj = SumProjection(initial=0)

        event_store.add(Event(1))
        proj.advance(event_store)
        assert proj.state == 1

        event_store.add(Event(2))
        event_store.add(Event(3))
        proj.advance(event_store)
        assert proj.state == 6


class TestFileWriterToTailer:
    """FileWriter writes -> Tailer reads back."""

    async def test_write_then_read(self, tmp_jsonl: Path):
        writer = FileWriter(tmp_jsonl, serialize_event)
        try:
            await writer.consume(Event(1))
            await writer.consume(Event(2))
        finally:
            writer.close()

        tailer = Tailer(tmp_jsonl, deserialize_event)
        events = tailer.poll()

        assert len(events) == 2
        assert events[0].value == 1
        assert events[1].value == 2

    async def test_tailer_tracks_offset(self, tmp_jsonl: Path):
        writer = FileWriter(tmp_jsonl, serialize_event)
        try:
            await writer.consume(Event(1))
        finally:
            writer.close()

        tailer = Tailer(tmp_jsonl, deserialize_event)
        events1 = tailer.poll()
        assert len(events1) == 1

        # Write more after first poll
        writer2 = FileWriter(tmp_jsonl, serialize_event)
        try:
            await writer2.consume(Event(2))
        finally:
            writer2.close()

        events2 = tailer.poll()
        assert len(events2) == 1
        assert events2[0].value == 2


class TestStreamToFileWriterToTailer:
    """Full pipeline: Stream -> FileWriter -> Tailer."""

    async def test_full_pipeline(self, tmp_jsonl: Path):
        stream: Stream[Event] = Stream()
        writer = FileWriter(tmp_jsonl, serialize_event)

        try:
            stream.tap(writer)

            await stream.emit(Event(10))
            await stream.emit(Event(20))
        finally:
            writer.close()

        tailer = Tailer(tmp_jsonl, deserialize_event)
        events = tailer.poll()

        assert len(events) == 2
        assert events[0].value == 10
        assert events[1].value == 20


class TestForwardBridge:
    """Forward bridges typed streams."""

    async def test_forward_transforms_between_streams(self):
        source: Stream[Event] = Stream()
        target: Stream[NamedEvent] = Stream()

        forward = Forward(target, lambda e: NamedEvent(name="x", amount=e.value))
        source.tap(forward)

        proj = NamedSumProjection(initial={})
        target.tap(proj)

        await source.emit(Event(5))
        await source.emit(Event(3))

        assert proj.state == {"x": 8}


class TestEventStorePersistence:
    """EventStore with file persistence."""

    def test_persist_and_reload(self, tmp_jsonl: Path):
        with EventStore[Event](
            path=tmp_jsonl,
            serialize=serialize_event,
            deserialize=deserialize_event,
        ) as store:
            store.add(Event(1))
            store.add(Event(2))

        # Reload from file
        with EventStore[Event](
            path=tmp_jsonl,
            serialize=serialize_event,
            deserialize=deserialize_event,
        ) as store2:
            assert len(store2.events) == 2
            assert store2.events[0].value == 1
            assert store2.events[1].value == 2
            assert store2.version == 2
