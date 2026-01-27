"""Integration tests: full paths through the system.

These tests verify that primitives compose correctly. They exercise
the public API and test behavior, not implementation details.
"""

from pathlib import Path

import pytest

from ticks import EventStore, FileWriter, Forward, Projection, Stream, Tailer, Tick, Vertex

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
        event_store.append(Event(1))
        event_store.append(Event(2))
        event_store.append(Event(3))

        proj = SumProjection(initial=0)
        proj.advance(event_store)

        assert proj.state == 6
        assert proj.cursor == 3

    async def test_projection_advance_is_incremental(
        self, event_store: EventStore[Event]
    ):
        proj = SumProjection(initial=0)

        event_store.append(Event(1))
        proj.advance(event_store)
        assert proj.state == 1

        event_store.append(Event(2))
        event_store.append(Event(3))
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
            store.append(Event(1))
            store.append(Event(2))

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


# --- Folds used by boundary tests ---


def sum_fold(state: int, payload: dict) -> int:
    return state + payload["value"]


def count_fold(state: int, payload: dict) -> int:
    return state + 1


class TestBoundaryToStreamTick:
    """Boundary trigger → Tick emitted on Stream[Tick] → Projection receives."""

    async def test_boundary_produces_tick_on_stream(self):
        v = Vertex("meter")
        v.register("metric", 0, sum_fold, boundary="flush", reset=True)

        v.receive("metric", {"value": 10})
        v.receive("metric", {"value": 5})
        assert v.state("metric") == 15

        tick = v.receive("flush", {})
        assert isinstance(tick, Tick)
        assert tick.name == "metric"
        assert tick.payload == 15
        assert tick.origin == "meter"

        tick_stream: Stream[Tick] = Stream()
        tick_proj = Projection(
            initial=[],
            fold=lambda state, t: [*state, t],
        )
        tick_stream.tap(tick_proj)

        await tick_stream.emit(tick)

        assert len(tick_proj.state) == 1
        assert tick_proj.state[0] is tick
        assert tick_proj.state[0].payload == 15

    async def test_boundary_resets_engine_state(self):
        v = Vertex("meter")
        v.register("metric", 0, sum_fold, boundary="flush", reset=True)

        v.receive("metric", {"value": 10})
        tick = v.receive("flush", {})
        assert tick is not None
        assert tick.payload == 10

        assert v.state("metric") == 0

        v.receive("metric", {"value": 3})
        assert v.state("metric") == 3

    async def test_boundary_no_reset_carries_state(self):
        v = Vertex("meter")
        v.register("metric", 0, sum_fold, boundary="flush", reset=False)

        v.receive("metric", {"value": 10})
        tick = v.receive("flush", {})
        assert tick is not None
        assert tick.payload == 10

        assert v.state("metric") == 10

        v.receive("metric", {"value": 5})
        assert v.state("metric") == 15

    async def test_non_boundary_receive_returns_none(self):
        v = Vertex("meter")
        v.register("metric", 0, sum_fold, boundary="flush", reset=True)

        result = v.receive("metric", {"value": 10})
        assert result is None


class TestNestedLoops:
    """Tick nesting: upstream Vertex → Tick → downstream Vertex."""

    def test_two_level_nesting(self):
        upstream = Vertex("upstream")
        upstream.register("metric", 0, sum_fold, boundary="flush", reset=True)

        def tick_sum_fold(state: int, payload: dict) -> int:
            return state + payload["value"]

        downstream = Vertex("downstream")
        downstream.register("tick-metric", 0, tick_sum_fold)

        upstream.receive("metric", {"value": 10})
        upstream.receive("metric", {"value": 5})
        tick1 = upstream.receive("flush", {})

        upstream.receive("metric", {"value": 20})
        tick2 = upstream.receive("flush", {})

        assert tick1 is not None
        assert tick2 is not None
        assert tick1.payload == 15
        assert tick2.payload == 20

        downstream.receive("tick-metric", {"value": tick1.payload})
        downstream.receive("tick-metric", {"value": tick2.payload})

        assert downstream.state("tick-metric") == 35

    def test_nested_loop_downstream_boundary(self):
        upstream = Vertex("upstream")
        upstream.register("event", 0, count_fold, boundary="close", reset=True)

        def accumulate_count(state: int, payload: dict) -> int:
            return state + payload["count"]

        downstream = Vertex("downstream")
        downstream.register(
            "tick-count", 0, accumulate_count,
            boundary="rollup", reset=True,
        )

        upstream.receive("event", {})
        upstream.receive("event", {})
        upstream.receive("event", {})
        tick1 = upstream.receive("close", {})

        upstream.receive("event", {})
        upstream.receive("event", {})
        tick2 = upstream.receive("close", {})

        assert tick1.payload == 3
        assert tick2.payload == 2

        downstream.receive("tick-count", {"count": tick1.payload})
        downstream.receive("tick-count", {"count": tick2.payload})
        assert downstream.state("tick-count") == 5

        rollup_tick = downstream.receive("rollup", {})
        assert rollup_tick is not None
        assert rollup_tick.name == "tick-count"
        assert rollup_tick.payload == 5
        assert rollup_tick.origin == "downstream"

        assert downstream.state("tick-count") == 0


class TestShapeBoundaryToVertex:
    """Shape boundary descriptor → Vertex wiring at the composition point.

    The test IS the integration layer: it imports Shape + Boundary from
    shapes and Vertex from ticks. No cross-lib imports in the atoms.
    """

    def test_shape_boundary_wires_to_vertex(self):
        from shapes import Boundary, Facet, Fold, Shape

        shape = Shape(
            name="container-health",
            about="Tracks container health check counts",
            input_facets=(Facet("status", "str"),),
            state_facets=(Facet("checks", "int"),),
            folds=(Fold("count", "checks"),),
            boundary=Boundary(kind="container-health.close", reset=True),
        )

        assert shape.boundary is not None
        boundary_kind = shape.boundary.kind
        boundary_reset = shape.boundary.reset

        v = Vertex("health-vertex")
        v.register(
            "container-health", 0, count_fold,
            boundary=boundary_kind,
            reset=boundary_reset,
        )

        v.receive("container-health", {"status": "healthy"})
        v.receive("container-health", {"status": "healthy"})
        v.receive("container-health", {"status": "degraded"})
        assert v.state("container-health") == 3

        tick = v.receive("container-health.close", {})
        assert isinstance(tick, Tick)
        assert tick.name == "container-health"
        assert tick.payload == 3
        assert tick.origin == "health-vertex"

        assert v.state("container-health") == 0

    def test_shape_boundary_no_reset(self):
        from shapes import Boundary, Facet, Fold, Shape

        shape = Shape(
            name="deploy-count",
            about="Running deploy count, no reset",
            input_facets=(Facet("env", "str"),),
            state_facets=(Facet("deploys", "int"),),
            folds=(Fold("count", "deploys"),),
            boundary=Boundary(kind="deploy.snapshot", reset=False),
        )

        v = Vertex("deploy-vertex")
        v.register(
            "deploy", 0, count_fold,
            boundary=shape.boundary.kind,
            reset=shape.boundary.reset,
        )

        v.receive("deploy", {"env": "prod"})
        v.receive("deploy", {"env": "staging"})

        tick = v.receive("deploy.snapshot", {})
        assert tick.payload == 2

        assert v.state("deploy") == 2
        v.receive("deploy", {"env": "prod"})
        assert v.state("deploy") == 3

    def test_shape_without_boundary(self):
        from shapes import Facet, Fold, Shape

        shape = Shape(
            name="simple-counter",
            about="No boundary — continuous fold",
            input_facets=(Facet("x", "int"),),
            state_facets=(Facet("total", "int"),),
            folds=(Fold("count", "total"),),
        )

        assert shape.boundary is None

        v = Vertex("counter-vertex")
        v.register("counter", 0, count_fold)

        v.receive("counter", {"x": 1})
        v.receive("counter", {"x": 2})
        assert v.state("counter") == 2

        from datetime import datetime, timezone

        tick = v.tick("counter-loop", datetime(2025, 6, 1, tzinfo=timezone.utc))
        assert tick.payload == {"counter": 2}
