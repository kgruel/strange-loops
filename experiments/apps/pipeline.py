"""Full wired pipeline: all 5 prism libraries end-to-end.

Connects peers (identity), facts (events), shapes (schema),
ticks (streams/projection), and cells (terminal UI) into a
live service-pulse dashboard.

Run: uv run --package experiments python experiments/apps/pipeline.py
Press q to quit.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Any

from peers import Peer, Scope
from facts import Event
from shapes import Facet, Fold, Shape
from ticks import Stream, Projection
from cells import (
    RenderApp, Block, Style, Region,
    Column, TableState, table,
    Line, Span,
    join_horizontal, join_vertical, pad, border,
)


# ---------------------------------------------------------------------------
# 1. Shape declaration — service pulse monitor schema
# ---------------------------------------------------------------------------

PULSE_SHAPE = Shape(
    name="service_pulse",
    about="Monitor service heartbeat status, latency, and request counts",
    input_facets=(
        Facet(name="service", kind="str"),
        Facet(name="status", kind="str"),
        Facet(name="latency_ms", kind="float"),
        Facet(name="requests", kind="int"),
        Facet(name="peer", kind="str"),
    ),
    state_facets=(
        Facet(name="last_seen", kind="str"),
        Facet(name="event_count", kind="int"),
        Facet(name="services", kind="dict"),
        Facet(name="history", kind="list"),
        Facet(name="total_requests", kind="int"),
    ),
    folds=(
        Fold(op="latest", target="last_seen"),
        Fold(op="count", target="event_count"),
        Fold(op="upsert", target="services", props={"key": "service"}),
        Fold(op="collect", target="history", props={"max": 50}),
        Fold(op="sum", target="total_requests", props={"field": "requests"}),
    ),
)


# ---------------------------------------------------------------------------
# 2. ShapeProjection bridge — Projection[dict, Event] backed by Shape folds
# ---------------------------------------------------------------------------

def _make_latest(target: str):
    """state[target] = event timestamp."""
    def fold(state: dict, payload: dict) -> None:
        state[target] = payload.get("_ts", time.time())
    return fold


def _make_count(target: str):
    """Increment state[target]."""
    def fold(state: dict, payload: dict) -> None:
        state[target] = state.get(target, 0) + 1
    return fold


def _make_upsert(target: str, key_field: str):
    """Insert/update in dict keyed by key_field."""
    def fold(state: dict, payload: dict) -> None:
        key_value = payload.get(key_field)
        if key_value is not None:
            state[target][key_value] = payload
    return fold


def _make_collect(target: str, max_size: int):
    """Append payload to state[target] list, bounded by max_size."""
    def fold(state: dict, payload: dict) -> None:
        items = state[target]
        items.append(payload)
        if max_size and len(items) > max_size:
            state[target] = items[-max_size:]
    return fold


def _make_sum(target: str, value_field: str):
    """Add payload[value_field] to state[target]."""
    def fold(state: dict, payload: dict) -> None:
        value = payload.get(value_field, 0)
        state[target] = state.get(target, 0) + value
    return fold


def _build_fold_fn(fold: Fold, shape: Shape):
    """Build a callable (state, payload) -> None from a Fold."""
    target = fold.target
    match fold.op:
        case "latest":
            return _make_latest(target)
        case "count":
            return _make_count(target)
        case "upsert":
            key_field = str(fold.props.get("key", ""))
            if not key_field:
                raise ValueError(f"upsert fold requires key= prop (target: {target})")
            return _make_upsert(target, key_field)
        case "collect":
            max_size = int(fold.props.get("max", 0))
            return _make_collect(target, max_size)
        case "sum":
            value_field = str(fold.props.get("field", target))
            return _make_sum(target, value_field)
        case _:
            raise ValueError(f"Unknown fold op: {fold.op}")


class ShapeProjection(Projection[dict[str, Any], Event]):
    """Projection driven by a Shape's fold rules.

    Extracts dict(event.data) + _ts from event.ts as the payload,
    then applies fold closures built from Shape.folds.
    """

    def __init__(self, shape: Shape):
        super().__init__(shape.initial_state())
        self.shape = shape
        self._fold_fns = [_build_fold_fn(f, shape) for f in shape.folds]

    def apply(self, state: dict[str, Any], event: Event) -> dict[str, Any]:
        payload = dict(event.data)
        payload["_ts"] = event.ts
        new_state = dict(state)
        # Deep-copy mutable containers so Projection identity check works
        for key, val in new_state.items():
            if isinstance(val, dict):
                new_state[key] = dict(val)
            elif isinstance(val, list):
                new_state[key] = list(val)
        for fn in self._fold_fns:
            fn(new_state, payload)
        return new_state


# ---------------------------------------------------------------------------
# 3. Heartbeat source — async generator yielding facts.Event
# ---------------------------------------------------------------------------

SERVICES = [
    Peer(name="api-gateway", scope=Scope(see=frozenset({"http", "metrics"}))),
    Peer(name="auth-service", scope=Scope(see=frozenset({"auth", "tokens"}))),
    Peer(name="data-store", scope=Scope(see=frozenset({"sql", "cache"}))),
    Peer(name="cache", scope=Scope(see=frozenset({"redis", "memory"}))),
    Peer(name="worker", scope=Scope(see=frozenset({"jobs", "queue"}))),
]

STATUS_WEIGHTS = ["healthy"] * 80 + ["degraded"] * 15 + ["down"] * 5


async def heartbeat_source() -> None:
    """Yield heartbeat events forever. Intended to be pumped into a Stream."""
    # This is a coroutine that emits to a stream; callers pass the stream.
    raise NotImplementedError("Use pump_heartbeats() instead")


async def pump_heartbeats(stream: Stream[Event], *, interval: float = 0.5) -> None:
    """Continuously emit heartbeat events into a stream."""
    while True:
        peer = random.choice(SERVICES)
        status = random.choice(STATUS_WEIGHTS)
        latency = random.uniform(1, 50) if status == "healthy" else random.uniform(100, 2000)
        requests = random.randint(0, 100)

        event = Event.log_signal(
            "heartbeat",
            service=peer.name,
            status=status,
            latency_ms=round(latency, 1),
            requests=requests,
            peer=peer.name,
        )
        await stream.emit(event)
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# 4. Dashboard render — build a Block from projection state
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "healthy": Style(fg="green"),
    "degraded": Style(fg="yellow"),
    "down": Style(fg="red", bold=True),
}


def render_dashboard(state: dict[str, Any], width: int, height: int) -> Block:
    """Render the dashboard as a composed Block."""
    services = state.get("services", {})
    event_count = state.get("event_count", 0)
    total_requests = state.get("total_requests", 0)
    history = state.get("history", [])

    # --- Header: counters ---
    healthy_count = sum(1 for s in services.values() if s.get("status") == "healthy")
    degraded_count = sum(1 for s in services.values() if s.get("status") == "degraded")
    down_count = sum(1 for s in services.values() if s.get("status") == "down")

    header = join_horizontal(
        Block.text(f" Pipeline Dashboard ", Style(bold=True)),
        Block.text(f" events:{event_count} ", Style(dim=True)),
        Block.text(f" reqs:{total_requests} ", Style(dim=True)),
        Block.text(f" OK:{healthy_count} ", Style(fg="green")),
        Block.text(f" WARN:{degraded_count} ", Style(fg="yellow")),
        Block.text(f" DOWN:{down_count} ", Style(fg="red")),
    )

    # --- Service table ---
    columns = [
        Column(header=Line.plain("Service"), width=16),
        Column(header=Line.plain("Status"), width=10),
        Column(header=Line.plain("Latency"), width=10),
        Column(header=Line.plain("Requests"), width=10),
    ]

    rows: list[list[Line]] = []
    for svc_name in sorted(services.keys()):
        svc = services[svc_name]
        status = svc.get("status", "unknown")
        latency = svc.get("latency_ms", 0)
        reqs = svc.get("requests", 0)
        style = STATUS_COLORS.get(status, Style())

        rows.append([
            Line.plain(svc_name),
            Line(spans=(Span(status, style),)),
            Line.plain(f"{latency:.1f}ms"),
            Line.plain(str(reqs)),
        ])

    visible = min(len(SERVICES) + 2, max(5, height - 10))
    tstate = TableState(row_count=len(rows))
    svc_table = table(tstate, columns, rows, visible)
    table_block = border(svc_table, title="Services")

    # --- Recent events ---
    max_recent = min(10, max(3, height - 14))
    recent = history[-max_recent:] if history else []
    event_rows: list[Block] = []
    for entry in recent:
        svc_name = entry.get("service", "?")
        status = entry.get("status", "?")
        latency = entry.get("latency_ms", 0)
        ts_val = entry.get("_ts", 0)
        ts_str = datetime.fromtimestamp(ts_val, tz=timezone.utc).strftime("%H:%M:%S")
        style = STATUS_COLORS.get(status, Style())
        row = join_horizontal(
            Block.text(f"  {ts_str} ", Style(dim=True)),
            Block.text(f"[{status:>8}] ", style),
            Block.text(f"{svc_name} ", Style()),
            Block.text(f"{latency:.0f}ms", Style(dim=True)),
        )
        event_rows.append(row)

    events_content = (
        join_vertical(*event_rows) if event_rows
        else Block.text("  Waiting for events...", Style(dim=True))
    )
    events_block = border(events_content, title="Recent Events")

    # --- Compose ---
    composed = join_vertical(
        header,
        pad(table_block, top=1),
        pad(events_block, top=1),
    )
    return composed


# ---------------------------------------------------------------------------
# 5. PipelineApp — RenderApp that wires Stream -> ShapeProjection
# ---------------------------------------------------------------------------

class PipelineApp(RenderApp):
    """Live dashboard wiring all 5 prism libraries."""

    def __init__(self):
        super().__init__(fps_cap=15)
        self._stream: Stream[Event] = Stream()
        self._projection = ShapeProjection(PULSE_SHAPE)
        self._region = Region(0, 0, 80, 24)
        self._last_version = -1
        self._pump_task: asyncio.Task | None = None

        # Wire projection as consumer on the stream
        self._stream.tap(self._projection)

    def layout(self, width: int, height: int) -> None:
        self._region = Region(0, 0, width, height)

    async def run(self) -> None:
        """Start pump task, then run the main loop."""
        self._pump_task = asyncio.create_task(
            pump_heartbeats(self._stream, interval=0.5)
        )
        try:
            await super().run()
        finally:
            if self._pump_task:
                self._pump_task.cancel()
                try:
                    await self._pump_task
                except asyncio.CancelledError:
                    pass

    def update(self) -> None:
        if self._projection.version != self._last_version:
            self._last_version = self._projection.version
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        dashboard = render_dashboard(
            self._projection.state,
            self._region.width,
            self._region.height,
        )
        view = self._region.view(self._buf)
        dashboard.paint(view, x=0, y=0)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()


# ---------------------------------------------------------------------------
# 6. Entry point
# ---------------------------------------------------------------------------

async def main():
    app = PipelineApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
