"""Cascade: live tick flow between loops.

Two vertices in one process, connected via Stream. When the review vertex
fires a boundary, the tick flows immediately to the summary vertex. No file,
no batch. Live.

Architecture:
    health facts ─┐
                  ├─→ Review Vertex ─→ Tick ─→ Stream ─→ Summary Vertex
    ack facts ────┘                              │
                                                 └─→ UI shows both levels

This proves: loops compose at runtime, not just through files.

Run:
    uv run python experiments/cascade.py
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass

from facts import Fact
from peers import Peer, delegate
from ticks import Tick, Vertex, Stream
from specs import Shape, Facet, Boundary
from cells import Block, Style, join_vertical, join_horizontal, border
from cells.tui import Surface

# System peer — unrestricted, for infrastructure facts (health timer).
SYSTEM = Peer("system")


# -- Review Shapes (level 1) -------------------------------------------------

health_shape = Shape(
    name="health",
    about="Container health status",
    input_facets=(Facet("container", "str"), Facet("status", "str")),
    state_facets=(Facet("statuses", "dict"),),
    boundary=Boundary("health.close", reset=True),
)

ack_shape = Shape(
    name="ack",
    about="Acknowledged containers this cycle",
    input_facets=(Facet("container", "str"), Facet("peer", "str")),
    state_facets=(Facet("acked", "dict"),),
    boundary=Boundary("review.complete", reset=True),
)

focus_shape = Shape(
    name="focus",
    about="Observer cursor",
    input_facets=(Facet("index", "int"),),
    state_facets=(Facet("index", "int"),),
)


# -- Summary Shapes (level 2) ------------------------------------------------

health_summary_shape = Shape(
    name="health.tick",
    about="Aggregate from health ticks",
    input_facets=(Facet("statuses", "dict"),),
    state_facets=(
        Facet("tick_count", "int"),
        Facet("total_containers", "int"),
    ),
)

review_summary_shape = Shape(
    name="review.tick",
    about="Aggregate from review ticks",
    input_facets=(Facet("acked", "dict"),),
    state_facets=(
        Facet("cycle_count", "int"),
        Facet("total_acks", "int"),
    ),
)


# -- Folds -------------------------------------------------------------------

def health_fold(state: dict, payload: dict) -> dict:
    statuses = dict(state.get("statuses", {}))
    statuses[payload["container"]] = payload["status"]
    return {"statuses": statuses}


def ack_fold(state: dict, payload: dict) -> dict:
    acked = dict(state.get("acked", {}))
    acked[payload["container"]] = payload["peer"]
    return {"acked": acked}


def focus_fold(state: dict, payload: dict) -> dict:
    return {"index": payload.get("index", 0)}


def health_summary_fold(state: dict, payload: dict) -> dict:
    statuses = payload.get("statuses", {})
    return {
        "tick_count": state.get("tick_count", 0) + 1,
        "total_containers": state.get("total_containers", 0) + len(statuses),
    }


def review_summary_fold(state: dict, payload: dict) -> dict:
    acked = payload.get("acked", {})
    return {
        "cycle_count": state.get("cycle_count", 0) + 1,
        "total_acks": state.get("total_acks", 0) + len(acked),
    }


# -- Topology ----------------------------------------------------------------

CONTAINERS = ["nginx", "api", "redis", "postgres", "worker"]
STATUSES = ["running", "running", "running", "unhealthy", "stopped"]

REVIEW_SHAPES = [
    (health_shape, health_fold),
    (ack_shape, ack_fold),
    (focus_shape, focus_fold),
]

SUMMARY_SHAPES = [
    (health_summary_shape, health_summary_fold),
    (review_summary_shape, review_summary_fold),
]


def build_review_vertex() -> Vertex:
    v = Vertex("review")
    for shape, fold in REVIEW_SHAPES:
        if shape.boundary is not None:
            v.register(
                shape.name, shape.initial_state(), fold,
                boundary=shape.boundary.kind, reset=shape.boundary.reset,
            )
        else:
            v.register(shape.name, shape.initial_state(), fold)
    return v


def build_summary_vertex() -> Vertex:
    v = Vertex("summary")
    for shape, fold in SUMMARY_SHAPES:
        v.register(shape.name, shape.initial_state(), fold)
    return v


# -- Summary Consumer --------------------------------------------------------

@dataclass
class SummaryConsumer:
    """Consumes Ticks from review, feeds to summary vertex."""
    vertex: Vertex
    log: deque

    async def consume(self, tick: Tick) -> None:
        """Route tick to summary vertex based on tick name."""
        if tick.name == "health":
            self.vertex.receive(Fact.of("health.tick", **tick.payload), SYSTEM)
            self.log.append(f"summary ← health tick")
        elif tick.name == "ack":
            self.vertex.receive(Fact.of("review.tick", **tick.payload), SYSTEM)
            self.log.append(f"summary ← review tick")


# -- App ---------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
ACTIVE = Style(fg="cyan", bold=True)

STATUS_STYLE = {
    "running": Style(fg="green"),
    "unhealthy": Style(fg="yellow"),
    "stopped": Style(fg="red"),
}


class CascadeApp(Surface):
    """Two vertices, live tick flow via Stream."""

    def __init__(self):
        super().__init__(fps_cap=60, on_emit=self._make_bridge(), on_start=self._start)
        self._w = 80
        self._h = 24
        self._task: asyncio.Task | None = None

        # Level 1: Review
        self.review = build_review_vertex()

        # Level 2: Summary
        self.summary = build_summary_vertex()

        # Stream connects them
        self.tick_stream: Stream[Tick] = Stream()
        self.log: deque[str] = deque(maxlen=10)
        self._consumer = SummaryConsumer(self.summary, self.log)
        self.tick_stream.tap(self._consumer)

        # Peer
        self.peer = Peer("operator")

        # Tick counters
        self.health_ticks = 0
        self.review_ticks = 0

    def _make_bridge(self):
        """Emit callback: route to review vertex, emit ticks to stream."""
        def on_emit(kind: str, data: dict) -> None:
            tick = self.review.receive(Fact.of(kind, **data, peer=self.peer.name), self.peer)

            if tick is not None:
                # Tick fired — emit to stream (async bridge)
                asyncio.create_task(self._emit_tick(tick))

                if tick.name == "health":
                    self.health_ticks += 1
                elif tick.name == "ack":
                    self.review_ticks += 1
                    self.log.append(f"review #{self.review_ticks} complete")

            self.mark_dirty()
        return on_emit

    async def _emit_tick(self, tick: Tick):
        """Async bridge: emit tick to stream."""
        await self.tick_stream.emit(tick)
        self.mark_dirty()

    async def _start(self):
        self._task = asyncio.create_task(self._source())

    async def _source(self):
        """Health facts + boundary sentinel."""
        try:
            while True:
                for c in CONTAINERS:
                    status = random.choice(STATUSES)
                    self.review.receive(Fact.of("health", container=c, status=status), SYSTEM)

                tick = self.review.receive(Fact.of("health.close"), SYSTEM)
                if tick:
                    self.health_ticks += 1
                    await self.tick_stream.emit(tick)

                self.mark_dirty()
                await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            pass

    def on_key(self, key: str) -> None:
        focus = self.review.state("focus")
        current = focus.get("index", 0)
        max_idx = len(CONTAINERS) - 1

        if key == "j":
            self.emit("focus", index=min(current + 1, max_idx))
        elif key == "k":
            self.emit("focus", index=max(current - 1, 0))
        elif key in ("enter", "return"):
            idx = min(current, max_idx)
            self.emit("ack", container=CONTAINERS[idx])
            # Check if all acked
            acked = self.review.state("ack").get("acked", {})
            if len(acked) >= len(CONTAINERS):
                tick = self.review.receive(Fact.of("review.complete"), self.peer)
                if tick:
                    self.review_ticks += 1
                    asyncio.create_task(self._emit_tick(tick))
                    self.log.append(f"review #{self.review_ticks} complete")
        elif key in ("q", "escape"):
            asyncio.ensure_future(self._shutdown())

    async def _shutdown(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.quit()

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def render(self) -> None:
        if self._buf is None:
            return

        w = self._w
        half = w // 2

        header = self._render_header(w)
        left = self._render_review(half)
        right = self._render_summary(w - half)
        body = join_horizontal(left, right)
        footer = self._render_footer(w)

        composed = join_vertical(header, body, footer)
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        composed.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _render_header(self, w: int) -> Block:
        return Block.text(
            f" cascade — review #{self.review_ticks + 1}  health #{self.health_ticks}",
            BOLD, width=w,
        )

    def _render_review(self, w: int) -> Block:
        inner = w - 4
        blocks: list[Block] = []

        # Container list
        focus = self.review.state("focus")
        current = focus.get("index", 0)
        health = self.review.state("health")
        statuses = health.get("statuses", {})
        acked = self.review.state("ack").get("acked", {})

        lines: list[Block] = []
        for i, name in enumerate(CONTAINERS):
            cursor = ">" if i == current else " "
            status = statuses.get(name, "unknown")
            style = STATUS_STYLE.get(status, DIM)
            ack_mark = " ✓" if name in acked else ""
            lines.append(Block.text(f" {cursor} {name:<10} {status:<10}{ack_mark}", style, width=inner))

        blocks.append(border(join_vertical(*lines), title=f"review ({len(acked)}/{len(CONTAINERS)})", style=DIM))

        # Log
        if self.log:
            log_lines = [Block.text(f" {e}", DIM, width=inner) for e in list(self.log)[-5:]]
            blocks.append(border(join_vertical(*log_lines), title="log", style=DIM))

        return join_vertical(*blocks)

    def _render_summary(self, w: int) -> Block:
        inner = w - 4
        blocks: list[Block] = []

        # Health summary
        hs = self.summary.state("health.tick")
        h_lines = [
            Block.text(f" ticks: {hs.get('tick_count', 0)}", Style(fg="green"), width=inner),
            Block.text(f" observations: {hs.get('total_containers', 0)}", DIM, width=inner),
        ]
        blocks.append(border(join_vertical(*h_lines), title="health (L2)", style=DIM))

        # Review summary
        rs = self.summary.state("review.tick")
        r_lines = [
            Block.text(f" cycles: {rs.get('cycle_count', 0)}", Style(fg="cyan"), width=inner),
            Block.text(f" total acks: {rs.get('total_acks', 0)}", DIM, width=inner),
        ]
        blocks.append(border(join_vertical(*r_lines), title="review (L2)", style=DIM))

        # Stream info
        blocks.append(Block.text(f" stream taps: {self.tick_stream.tap_count}", DIM, width=w))

        return join_vertical(*blocks)

    def _render_footer(self, w: int) -> Block:
        return Block.text(" j/k nav  enter ack  q quit", DIM, width=w)


async def main():
    app = CascadeApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
