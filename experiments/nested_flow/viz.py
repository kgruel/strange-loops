"""Nested Flow Visualization: animated vertex hierarchy.

Demonstrates nested vertex composition with live data flow:
- Timer → Source → Aggregator → Root
- Animated tick propagation through the hierarchy
- ASCII visualization of the loop structure

Refactored to use extracted vertex builder:
- `build_nested_flow_vertex()` constructs the hierarchy
- Returns a VertexTree with named references for state access
- Single root vertex with three sibling children

Run:
    uv run python experiments/nested_flow/viz.py
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from data import Fact
from vertex import Peer, Vertex, Loop
from vertex.projection import Projection
from cells import Block, Style, join_vertical, join_horizontal, border, pad
from cells.tui import Surface
from cells.widgets import progress_bar, ProgressState


# -- Configuration -----------------------------------------------------------

SECOND_INTERVAL = 1.0     # Base timer tick rate
SECONDS_PER_MINUTE = 10   # Accelerated for demo (normally 60)
MAX_EVENTS = 30           # Events to show in stream


# -- Styles ------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
CYAN = Style(fg="cyan")
CYAN_BOLD = Style(fg="cyan", bold=True)
GREEN = Style(fg="green")
GREEN_BOLD = Style(fg="green", bold=True)
YELLOW = Style(fg="yellow")
YELLOW_BOLD = Style(fg="yellow", bold=True)
RED = Style(fg="red")
MAGENTA = Style(fg="magenta")
MAGENTA_BOLD = Style(fg="magenta", bold=True)
WHITE_BOLD = Style(bold=True)


# -- Event Stream Entry ------------------------------------------------------

@dataclass(frozen=True)
class EventEntry:
    """An event in the stream display."""
    ts: float
    kind: str
    source: str
    summary: str
    style: Style = DIM


# -- Fold Functions ----------------------------------------------------------

def count_fold(state: int, payload: dict) -> int:
    """Count events."""
    return state + 1


def collect_fold(state: list, payload: dict) -> list:
    """Collect last 10 payloads."""
    return [*state[-9:], payload]


def health_fold(state: dict, payload: dict) -> dict:
    """Aggregate health metrics from disk and proc."""
    return {
        "reports": state.get("reports", 0) + 1,
        "last_disk": payload.get("disk_pct", state.get("last_disk", 0)),
        "last_proc": payload.get("proc_count", state.get("last_proc", 0)),
        "last_ts": time.time(),
    }


# -- Initial States ----------------------------------------------------------

HEALTH_INITIAL = {"reports": 0, "last_disk": 0, "last_proc": 0, "last_ts": 0.0}


# -- Vertex Tree -------------------------------------------------------------

class VertexTree(NamedTuple):
    """References to vertices in the hierarchy for state access."""
    root: Vertex
    timers: Vertex
    sources: Vertex
    infra: Vertex


def build_nested_flow_vertex() -> VertexTree:
    """Build the nested vertex hierarchy.

    Structure:
        root (system loop)
        ├── timers (second, minute loops)
        ├── sources (disk, proc folds)
        └── infra (health loop)

    Facts flow through root to children. Children fold independently.
    This demonstrates sibling composition (fan-out) vs the cadence_viz
    which demonstrates nested composition (cascade).
    """
    # Timers vertex: second and minute counters
    timers = Vertex("timers")
    timers.register_loop(Loop(
        name="second",
        projection=Projection(0, fold=count_fold),
        boundary_kind=None,
    ))
    timers.register_loop(Loop(
        name="minute",
        projection=Projection(0, fold=count_fold),
        boundary_kind="minute.tick",
    ))

    # Sources vertex: disk and proc collectors
    sources = Vertex("sources")
    sources.register("disk", [], collect_fold)
    sources.register("proc", [], collect_fold)

    # Infra vertex: health aggregator
    infra = Vertex("infra")
    infra.register_loop(Loop(
        name="health",
        projection=Projection(HEALTH_INITIAL.copy(), fold=health_fold),
        boundary_kind="infra.tick",
    ))

    # Root vertex: top-level system state
    root = Vertex("root")
    root.register_loop(Loop(
        name="system",
        projection=Projection([], fold=collect_fold),
        boundary_kind="system.tick",
    ))

    # Wire nesting: root contains all children as siblings
    root.add_child(timers)
    root.add_child(sources)
    root.add_child(infra)

    return VertexTree(root=root, timers=timers, sources=sources, infra=infra)


# -- Pulse Rendering ---------------------------------------------------------

def render_pulse(active: bool, label: str, style: Style, width: int) -> Block:
    """Render a pulsing indicator."""
    char = "●" if active else "○"
    indicator_style = style if active else DIM
    text = f"{char} {label}"
    return Block.text(text, indicator_style, width=width)


def render_arrow(active: bool, direction: str = "→") -> Block:
    """Render an arrow that lights up when data flows."""
    style = CYAN_BOLD if active else DIM
    return Block.text(f" {direction} ", style)


def render_flow_line(nodes: list[tuple[str, bool, Style]], width: int) -> Block:
    """Render a horizontal flow of nodes connected by arrows."""
    parts = []
    for i, (label, active, style) in enumerate(nodes):
        if i > 0:
            parts.append(render_arrow(active))
        parts.append(render_pulse(active, label, style, len(label) + 2))
    return join_horizontal(*parts)


# -- Main Visualization ------------------------------------------------------

class NestedFlowApp(Surface):
    """Animated visualization of nested vertex hierarchy.

    Uses a single vertex tree built by `build_nested_flow_vertex()`.
    Demonstrates sibling composition: root fans out to children.
    """

    def __init__(self):
        super().__init__(fps_cap=30, on_emit=self._handle_emit)
        self._w = 80
        self._h = 40

        self.peer = Peer("nested-flow-viz")

        # Build vertex hierarchy
        self._tree = build_nested_flow_vertex()

        # Timer state
        self._last_second = time.time()
        self._second_count = 0
        self._minute_count = 0

        # Flash effects (node -> frames remaining)
        self._flashes: dict[str, int] = {}

        # Event stream
        self._events: deque[EventEntry] = deque(maxlen=MAX_EVENTS)

        # UI state
        self._paused = False

    def _flash(self, node: str, frames: int = 5) -> None:
        """Start flash effect for a node."""
        self._flashes[node] = frames

    def _is_flashing(self, node: str) -> bool:
        """Check if a node is currently flashing."""
        return self._flashes.get(node, 0) > 0

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def update(self) -> None:
        """Drive timers and decay flash effects."""
        for node in list(self._flashes.keys()):
            if self._flashes[node] > 0:
                self._flashes[node] -= 1
                self.mark_dirty()

        if self._paused:
            return

        now = time.time()
        if now - self._last_second >= SECOND_INTERVAL:
            self._emit_second(now)
            self._last_second = now
            self.mark_dirty()

    def _emit_second(self, ts: float) -> None:
        """Emit a second tick, cascading through the hierarchy."""
        self._second_count += 1

        # Route through root - cascades to children that accept "second"
        second_fact = Fact.of("second", "timer", ts=ts, count=self._second_count)
        self._tree.root.receive(second_fact)

        self._flash("second")
        self._add_event("second", "timer", f"count={self._second_count}", CYAN)

        # Check for minute boundary
        if self._second_count % SECONDS_PER_MINUTE == 0:
            self._emit_minute(ts)

    def _emit_minute(self, ts: float) -> None:
        """Emit a minute tick, triggering sources."""
        self._minute_count += 1

        minute_fact = Fact.of("minute", "timer", ts=ts, count=self._minute_count)
        self._tree.root.receive(minute_fact)

        self._flash("minute", 8)
        self._add_event("minute", "timer", f"count={self._minute_count}", GREEN_BOLD)

        # Trigger sources with simulated data
        self._trigger_sources(ts)

    def _trigger_sources(self, ts: float) -> None:
        """Simulate source execution on minute trigger."""
        # Simulate disk usage
        disk_pct = random.randint(30, 85)
        disk_fact = Fact.of("disk", "infra", ts=ts, pct=disk_pct, mount="/")
        self._tree.root.receive(disk_fact)
        self._flash("disk")
        self._add_event("disk", "sources", f"usage={disk_pct}%", YELLOW)

        # Simulate process count
        proc_count = random.randint(100, 300)
        proc_fact = Fact.of("proc", "infra", ts=ts, count=proc_count)
        self._tree.root.receive(proc_fact)
        self._flash("proc")
        self._add_event("proc", "sources", f"count={proc_count}", YELLOW)

        # After sources complete, emit health summary
        self._emit_health(ts, disk_pct, proc_count)

    def _emit_health(self, ts: float, disk_pct: int, proc_count: int) -> None:
        """Emit health fact from infra vertex."""
        health_fact = Fact.of(
            "health", "infra",
            ts=ts,
            disk_pct=disk_pct,
            proc_count=proc_count,
        )
        self._tree.root.receive(health_fact)

        self._flash("infra", 6)
        self._add_event("health", "infra", f"disk={disk_pct}% proc={proc_count}", MAGENTA_BOLD)

        # Cascade to root system report
        self._emit_system(ts)

    def _emit_system(self, ts: float) -> None:
        """Emit system report from root."""
        system_fact = Fact.of(
            "system", "root",
            ts=ts,
            health=self._tree.infra.state("health"),
        )
        self._tree.root.receive(system_fact)

        self._flash("root", 8)
        self._add_event("system", "root", "report emitted", WHITE_BOLD)

    def _add_event(self, kind: str, source: str, summary: str, style: Style) -> None:
        """Add an event to the stream."""
        self._events.append(EventEntry(
            ts=time.time(),
            kind=kind,
            source=source,
            summary=summary,
            style=style,
        ))

    def _handle_emit(self, kind: str, data: dict) -> None:
        """Handle UI emissions."""
        pass

    def render(self) -> None:
        if self._buf is None:
            return

        content_width = min(self._w - 4, 100)

        # Title
        title_text = "NESTED VERTEX FLOW"
        if self._paused:
            title_text += " [PAUSED]"
        title = Block.text(title_text.center(content_width), WHITE_BOLD, width=content_width)

        # Flow diagram
        diagram = self._render_flow_diagram(content_width)

        # State panels
        state_panels = self._render_state_panels(content_width)

        # Event stream
        stream = self._render_event_stream(content_width, 12)

        # Help line
        help_text = "[q]uit  [p]ause  [r]eset"
        help_line = Block.text(help_text.center(content_width), DIM, width=content_width)

        content = join_vertical(
            title,
            Block.empty(content_width, 1),
            diagram,
            Block.empty(content_width, 1),
            state_panels,
            Block.empty(content_width, 1),
            stream,
            Block.empty(content_width, 1),
            help_line,
        )

        padded = pad(content, left=2, top=1)

        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _render_flow_diagram(self, width: int) -> Block:
        """Render the vertex hierarchy as ASCII flow diagram."""
        lines = []

        # Title
        lines.append(Block.text("DATA FLOW", WHITE_BOLD, width=width))
        lines.append(Block.empty(width, 1))

        # Timer row: second → minute
        timer_label = Block.text("timers/  ", DIM)
        timer_flow = render_flow_line([
            ("second", self._is_flashing("second"), CYAN),
            ("minute", self._is_flashing("minute"), GREEN),
        ], width - 10)
        lines.append(join_horizontal(timer_label, timer_flow))

        # Vertical connector
        lines.append(Block.text("             │", DIM, width=width))

        # Source row: disk, proc (triggered by minute)
        source_label = Block.text("sources/ ", DIM)
        disk_pulse = render_pulse(self._is_flashing("disk"), "disk", YELLOW, 6)
        proc_pulse = render_pulse(self._is_flashing("proc"), "proc", YELLOW, 6)
        down_arrow = Block.text(" ↓ ", GREEN if self._is_flashing("minute") else DIM)
        source_flow = join_horizontal(down_arrow, disk_pulse, Block.text("  ", DIM), proc_pulse)
        lines.append(join_horizontal(source_label, source_flow))

        # Vertical connectors from disk/proc
        lines.append(Block.text("              ↘   ↙", DIM, width=width))

        # Infra row
        infra_label = Block.text("infra/   ", DIM)
        infra_pulse = render_pulse(self._is_flashing("infra"), "health", MAGENTA, 8)
        lines.append(join_horizontal(infra_label, Block.text("   ", DIM), infra_pulse))

        # Final connector
        lines.append(Block.text("               │", DIM, width=width))

        # Root
        root_label = Block.text("root/    ", DIM)
        root_pulse = render_pulse(self._is_flashing("root"), "system", WHITE_BOLD, 8)
        lines.append(join_horizontal(root_label, Block.text("   ", DIM), root_pulse))

        content = join_vertical(*lines)
        return border(content, title="HIERARCHY", style=DIM, title_style=WHITE_BOLD)

    def _render_state_panels(self, width: int) -> Block:
        """Render current state of each vertex."""
        panel_width = (width - 8) // 3
        tree = self._tree

        # Timers panel
        second_state = tree.timers.state("second") if "second" in tree.timers.kinds else 0
        minute_state = tree.timers.state("minute") if "minute" in tree.timers.kinds else 0
        timer_lines = [
            Block.text(f"second: {second_state}", CYAN, width=panel_width - 4),
            Block.text(f"minute: {minute_state}", GREEN, width=panel_width - 4),
            Block.empty(panel_width - 4, 1),
            Block.text("progress:", DIM, width=panel_width - 4),
        ]
        progress = (self._second_count % SECONDS_PER_MINUTE) / SECONDS_PER_MINUTE
        pbar = progress_bar(ProgressState(value=progress), panel_width - 6, filled_style=GREEN, empty_style=DIM)
        timer_lines.append(pbar)
        timer_content = join_vertical(*timer_lines)
        timer_panel = border(timer_content, title="TIMERS", style=CYAN if self._is_flashing("second") else DIM, title_style=CYAN_BOLD)

        # Sources panel
        disk_state = tree.sources.state("disk") if "disk" in tree.sources.kinds else []
        proc_state = tree.sources.state("proc") if "proc" in tree.sources.kinds else []
        source_lines = [
            Block.text(f"disk samples: {len(disk_state)}", YELLOW, width=panel_width - 4),
            Block.text(f"proc samples: {len(proc_state)}", YELLOW, width=panel_width - 4),
        ]
        if disk_state:
            last_disk = disk_state[-1] if isinstance(disk_state[-1], dict) else {}
            source_lines.append(Block.text(f"last: {last_disk.get('pct', '?')}%", DIM, width=panel_width - 4))
        source_content = join_vertical(*source_lines)
        source_panel = border(source_content, title="SOURCES", style=YELLOW if self._is_flashing("disk") or self._is_flashing("proc") else DIM, title_style=YELLOW_BOLD)

        # Infra panel
        health_state = tree.infra.state("health") if "health" in tree.infra.kinds else {}
        infra_lines = [
            Block.text(f"reports: {health_state.get('reports', 0)}", MAGENTA, width=panel_width - 4),
            Block.text(f"disk: {health_state.get('last_disk', '?')}%", DIM, width=panel_width - 4),
            Block.text(f"proc: {health_state.get('last_proc', '?')}", DIM, width=panel_width - 4),
        ]
        infra_content = join_vertical(*infra_lines)
        infra_panel = border(infra_content, title="INFRA", style=MAGENTA if self._is_flashing("infra") else DIM, title_style=MAGENTA_BOLD)

        return join_horizontal(timer_panel, Block.empty(2, 1), source_panel, Block.empty(2, 1), infra_panel)

    def _render_event_stream(self, width: int, height: int) -> Block:
        """Render scrolling event stream."""
        lines = []

        events = list(self._events)[-height:]
        for event in reversed(events):
            ts_str = datetime.fromtimestamp(event.ts).strftime("%H:%M:%S")
            line = f"{ts_str}  {event.source:8s} {event.kind:8s} {event.summary}"
            if len(line) > width - 4:
                line = line[:width - 5] + "…"
            lines.append(Block.text(line, event.style, width=width - 4))

        while len(lines) < height:
            lines.append(Block.empty(width - 4, 1))

        content = join_vertical(*lines)
        return border(content, title="EVENT STREAM", style=DIM, title_style=WHITE_BOLD)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()
        elif key == "p":
            self._paused = not self._paused
            self.mark_dirty()
        elif key == "r":
            self._reset()

    def _reset(self) -> None:
        """Reset all state."""
        self._second_count = 0
        self._minute_count = 0
        self._last_second = time.time()
        self._events.clear()
        self._flashes.clear()

        # Rebuild vertex tree
        self._tree = build_nested_flow_vertex()

        self._add_event("reset", "viz", "all state cleared", WHITE_BOLD)
        self.mark_dirty()


# -- Main --------------------------------------------------------------------

async def main():
    app = NestedFlowApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
