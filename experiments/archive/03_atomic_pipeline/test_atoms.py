"""Build the pipeline atomically, testing each stage.

Each test adds one layer, validating assumptions in pipeline order:
  Fact → Stream → Shape → Shape.apply → Projection → Tick
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from facts import Fact
from ticks import Stream, Projection, Tick
from shapes import Facet, Fold, Shape


# ---------------------------------------------------------------------------
# Stage 1: A Fact exists — an intentional observation
# ---------------------------------------------------------------------------


def test_fact_direct_construction():
    """Fact is a frozen envelope: kind + ts + payload."""
    now = datetime.now(timezone.utc)
    fact = Fact(kind="heartbeat", ts=now, payload={"service": "api", "latency": 42.0})
    assert fact.kind == "heartbeat"
    assert fact.ts == now
    assert fact.payload["service"] == "api"
    assert fact.payload["latency"] == 42.0


def test_fact_factory():
    """Fact.of() auto-timestamps and wraps kwargs as dict payload."""
    fact = Fact.of("heartbeat", service="api", latency=42.0)
    assert fact.kind == "heartbeat"
    assert fact.payload["service"] == "api"
    assert fact.ts.tzinfo is not None  # timezone-aware


def test_fact_is_kind():
    """Kind predicate for stream filtering."""
    fact = Fact.of("heartbeat", service="api")
    assert fact.is_kind("heartbeat")
    assert fact.is_kind("heartbeat", "deploy")
    assert not fact.is_kind("deploy")


# ---------------------------------------------------------------------------
# Stage 2: Facts flow through a Stream
# ---------------------------------------------------------------------------


async def test_stream_carries_facts():
    """Stream[Fact] fans out to consumers."""
    stream: Stream[Fact] = Stream()
    received: list[Fact] = []

    class Collector:
        async def consume(self, fact: Fact) -> None:
            received.append(fact)

    stream.tap(Collector())

    fact = Fact.of("heartbeat", service="api", latency=42.0)
    await stream.emit(fact)

    assert len(received) == 1
    assert received[0].kind == "heartbeat"
    assert received[0].payload["service"] == "api"


async def test_stream_fans_out_to_multiple_consumers():
    """Multiple taps on the same stream each receive every fact."""
    stream: Stream[Fact] = Stream()
    a: list[Fact] = []
    b: list[Fact] = []

    class Collector:
        def __init__(self, target: list):
            self._target = target
        async def consume(self, fact: Fact) -> None:
            self._target.append(fact)

    stream.tap(Collector(a))
    stream.tap(Collector(b))

    await stream.emit(Fact.of("heartbeat", service="api"))

    assert len(a) == 1
    assert len(b) == 1


# ---------------------------------------------------------------------------
# Stage 3: A Shape defines the data contract
# ---------------------------------------------------------------------------


PULSE_SHAPE = Shape(
    name="pulse",
    about="Count heartbeats and track latest service status",
    input_facets=(
        Facet(name="service", kind="str"),
        Facet(name="latency", kind="float"),
    ),
    state_facets=(
        Facet(name="count", kind="int"),
        Facet(name="total_latency", kind="float"),
        Facet(name="services", kind="dict"),
    ),
    folds=(
        Fold(op="count", target="count"),
        Fold(op="sum", target="total_latency", props={"field": "latency"}),
        Fold(op="upsert", target="services", props={"key": "service"}),
    ),
)


def test_shape_initial_state():
    """Shape.initial_state() creates zeroed state from state_facets."""
    state = PULSE_SHAPE.initial_state()
    assert state == {"count": 0, "total_latency": 0, "services": {}}


# ---------------------------------------------------------------------------
# Stage 4: Shape.apply folds a payload into state
# ---------------------------------------------------------------------------


def test_shape_apply_single():
    """One payload folded into initial state."""
    state = PULSE_SHAPE.initial_state()
    payload = {"service": "api", "latency": 42.0}

    new_state = PULSE_SHAPE.apply(state, payload)

    assert new_state["count"] == 1
    assert new_state["total_latency"] == 42.0
    assert "api" in new_state["services"]
    assert new_state["services"]["api"]["latency"] == 42.0


def test_shape_apply_accumulates():
    """Multiple payloads fold incrementally."""
    state = PULSE_SHAPE.initial_state()

    state = PULSE_SHAPE.apply(state, {"service": "api", "latency": 10.0})
    state = PULSE_SHAPE.apply(state, {"service": "db", "latency": 25.0})
    state = PULSE_SHAPE.apply(state, {"service": "api", "latency": 15.0})

    assert state["count"] == 3
    assert state["total_latency"] == 50.0
    assert len(state["services"]) == 2
    # upsert: api was updated with latest payload
    assert state["services"]["api"]["latency"] == 15.0


def test_shape_apply_immutability():
    """apply() never mutates the input state."""
    state = PULSE_SHAPE.initial_state()
    original = dict(state)

    PULSE_SHAPE.apply(state, {"service": "api", "latency": 42.0})

    assert state == original


# ---------------------------------------------------------------------------
# Stage 5: Projection wires Stream → Shape.apply
# ---------------------------------------------------------------------------


def _make_fold(shape: Shape):
    """Bridge: extract Fact payload and delegate to shape.apply.

    Projection receives Facts. Shape.apply receives dicts.
    This is the extraction point — the only place that knows about both.
    """
    def fold(state: dict, fact: Fact) -> dict:
        return shape.apply(state, dict(fact.payload))
    return fold


async def test_projection_folds_streamed_facts():
    """Stream → Projection(fold=shape.apply) produces live state."""
    stream: Stream[Fact] = Stream()
    proj: Projection[dict, Fact] = Projection(
        PULSE_SHAPE.initial_state(),
        fold=_make_fold(PULSE_SHAPE),
    )
    stream.tap(proj)

    await stream.emit(Fact.of("heartbeat", service="api", latency=10.0))
    await stream.emit(Fact.of("heartbeat", service="db", latency=25.0))

    assert proj.state["count"] == 2
    assert proj.state["total_latency"] == 35.0
    assert proj.version == 2


async def test_projection_state_updates_incrementally():
    """Each fact advances state — O(1) per fact, not O(all)."""
    stream: Stream[Fact] = Stream()
    proj: Projection[dict, Fact] = Projection(
        PULSE_SHAPE.initial_state(),
        fold=_make_fold(PULSE_SHAPE),
    )
    stream.tap(proj)

    await stream.emit(Fact.of("heartbeat", service="api", latency=10.0))
    assert proj.state["count"] == 1
    assert proj.version == 1

    await stream.emit(Fact.of("heartbeat", service="api", latency=20.0))
    assert proj.state["count"] == 2
    assert proj.version == 2


# ---------------------------------------------------------------------------
# Stage 6: Tick snapshots the projected state at a boundary
# ---------------------------------------------------------------------------


async def test_tick_captures_projected_state():
    """At a boundary, the projected state becomes a Tick."""
    stream: Stream[Fact] = Stream()
    proj: Projection[dict, Fact] = Projection(
        PULSE_SHAPE.initial_state(),
        fold=_make_fold(PULSE_SHAPE),
    )
    stream.tap(proj)

    await stream.emit(Fact.of("heartbeat", service="api", latency=10.0))
    await stream.emit(Fact.of("heartbeat", service="db", latency=25.0))

    # Snapshot at boundary
    tick = Tick(ts=datetime.now(timezone.utc), payload=dict(proj.state))

    assert tick.payload["count"] == 2
    assert tick.payload["total_latency"] == 35.0
    assert tick.ts.tzinfo is not None


def test_tick_is_frozen_snapshot():
    """Tick is frozen — the snapshot doesn't change when state advances."""
    state = PULSE_SHAPE.initial_state()
    state = PULSE_SHAPE.apply(state, {"service": "api", "latency": 10.0})

    tick = Tick(ts=datetime.now(timezone.utc), payload=dict(state))

    # State advances further
    state = PULSE_SHAPE.apply(state, {"service": "db", "latency": 25.0})

    # Tick is still the old snapshot
    assert tick.payload["count"] == 1
    assert state["count"] == 2


async def test_tick_flows_downstream():
    """Ticks can flow through their own Stream for further processing."""
    fact_stream: Stream[Fact] = Stream()
    tick_stream: Stream[Tick] = Stream()
    proj: Projection[dict, Fact] = Projection(
        PULSE_SHAPE.initial_state(),
        fold=_make_fold(PULSE_SHAPE),
    )
    fact_stream.tap(proj)

    ticks_received: list[Tick] = []

    class TickCollector:
        async def consume(self, tick: Tick) -> None:
            ticks_received.append(tick)

    tick_stream.tap(TickCollector())

    # Simulate: emit facts, then snapshot into tick stream
    await fact_stream.emit(Fact.of("heartbeat", service="api", latency=10.0))
    await fact_stream.emit(Fact.of("heartbeat", service="db", latency=25.0))

    tick = Tick(ts=datetime.now(timezone.utc), payload=dict(proj.state))
    await tick_stream.emit(tick)

    assert len(ticks_received) == 1
    assert ticks_received[0].payload["count"] == 2
