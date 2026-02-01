"""Nested Flow Visualization: animated vertex hierarchy.

Demonstrates nested vertex composition with live data flow:
- Timer → Source → Aggregator → Root
- Animated tick propagation through the hierarchy
- ASCII visualization of the loop structure

Run:
    uv run python experiments/nested_flow/viz.py
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from data import Fact
from vertex import Peer, Vertex, Tick, Loop
from vertex.projection import Projection
from cells import Block, Style, Cell, join_vertical, join_horizontal, border, pad, ROUNDED
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
    return state + 1


def collect_fold(state: list, payload: dict) -> list:
    return [*state[-9:], payload]  # Keep last 10


def health_fold(state: dict, payload: dict) -> dict:
    """Aggregate health metrics from disk and proc."""
    return {
        "reports": state.get("reports", 0) + 1,
        "last_disk": payload.get("disk_pct", state.get("last_disk", 0)),
        "last_proc": payload.get("proc_count", state.get("last_proc", 0)),
        "last_ts": time.time(),
    }


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
            # Arrow between nodes
            parts.append(render_arrow(active))
        parts.append(render_pulse(active, label, style, len(label) + 2))
    return join_horizontal(*parts)


# -- Main Visualization ------------------------------------------------------

class NestedFlowApp(Surface):
    """Animated visualization of nested vertex hierarchy."""

    def __init__(self):
        super().__init__(fps_cap=30, on_emit=self._handle_emit)
        self._w = 80
        self._h = 40

        self.peer = Peer("nested-flow-viz")

        # Build the vertex hierarchy
        self._build_vertices()

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

    def _build_vertices(self) -> None:
        """Build the nested vertex hierarchy.

        Structure:
          root
          ├── timers (second, minute)
          ├── sources (disk, proc)
          └── infra (folds disk + proc → health)
        """
        # Timers vertex: contains second and minute loops
        self.timers = Vertex("timers")

        # Second timer: counts ticks
        second_loop = Loop(
            name="second",
            projection=Projection(0, fold=count_fold),
            boundary_kind=None,  # No auto-boundary, we tick manually
        )
        self.timers.register_loop(second_loop)

        # Minute timer: triggered by second count
        minute_loop = Loop(
            name="minute",
            projection=Projection(0, fold=count_fold),
            boundary_kind="minute.tick",
        )
        self.timers.register_loop(minute_loop)

        # Sources vertex: disk and proc
        self.sources = Vertex("sources")
        self.sources.register("disk", [], collect_fold)
        self.sources.register("proc", [], collect_fold)

        # Infra vertex: folds disk and proc into health
        self.infra = Vertex("infra")
        infra_health_loop = Loop(
            name="health",
            projection=Projection(
                {"reports": 0, "last_disk": 0, "last_proc": 0, "last_ts": 0},
                fold=health_fold,
            ),
            boundary_kind="infra.tick",
        )
        self.infra.register_loop(infra_health_loop)

        # Root vertex: top-level aggregation
        self.root = Vertex("root")
        root_loop = Loop(
            name="system",
            projection=Projection([], fold=collect_fold),
            boundary_kind="system.tick",
        )
        self.root.register_loop(root_loop)

        # Wire up nesting: root contains timers, sources, infra
        self.root.add_child(self.timers)
        self.root.add_child(self.sources)
        self.root.add_child(self.infra)

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
        # Decay flashes
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

        # Create second fact
        second_fact = Fact.of("second", "timer", ts=ts, count=self._second_count)

        # Route through root (will cascade to children)
        self.root.receive(second_fact)

        # Flash the second node
        self._flash("second")
        self._add_event("second", "timer", f"count={self._second_count}", CYAN)

        # Check for minute boundary
        if self._second_count % SECONDS_PER_MINUTE == 0:
            self._emit_minute(ts)

    def _emit_minute(self, ts: float) -> None:
        """Emit a minute tick, triggering sources."""
        self._minute_count += 1

        # Create minute fact
        minute_fact = Fact.of("minute", "timer", ts=ts, count=self._minute_count)
        self.root.receive(minute_fact)

        self._flash("minute", 8)
        self._add_event("minute", "timer", f"count={self._minute_count}", GREEN_BOLD)

        # Trigger sources (simulated data)
        self._trigger_sources(ts)

    def _trigger_sources(self, ts: float) -> None:
        """Simulate source execution on minute trigger."""
        import random

        # Simulate disk usage
        disk_pct = random.randint(30, 85)
        disk_fact = Fact.of("disk", "infra", ts=ts, pct=disk_pct, mount="/")
        self.root.receive(disk_fact)
        self._flash("disk")
        self._add_event("disk", "sources", f"usage={disk_pct}%", YELLOW)

        # Simulate process count
        proc_count = random.randint(100, 300)
        proc_fact = Fact.of("proc", "infra", ts=ts, count=proc_count)
        self.root.receive(proc_fact)
        self._flash("proc")
        self._add_event("proc", "sources", f"count={proc_count}", YELLOW)

        # After sources complete, emit health
        self._emit_health(ts, disk_pct, proc_count)

    def _emit_health(self, ts: float, disk_pct: int, proc_count: int) -> None:
        """Emit health fact from infra vertex."""
        health_fact = Fact.of(
            "health", "infra",
            ts=ts,
            disk_pct=disk_pct,
            proc_count=proc_count,
        )
        self.root.receive(health_fact)

        self._flash("infra", 6)
        self._add_event("health", "infra", f"disk={disk_pct}% proc={proc_count}", MAGENTA_BOLD)

        # Cascade to root
        self._emit_system(ts)

    def _emit_system(self, ts: float) -> None:
        """Emit system report from root."""
        system_fact = Fact.of(
            "system", "root",
            ts=ts,
            health=self.infra.state("health"),
        )
        self.root.receive(system_fact)

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

        # Timers panel
        second_state = self.timers.state("second") if "second" in self.timers.kinds else 0
        minute_state = self.timers.state("minute") if "minute" in self.timers.kinds else 0
        timer_lines = [
            Block.text(f"second: {second_state}", CYAN, width=panel_width - 4),
            Block.text(f"minute: {minute_state}", GREEN, width=panel_width - 4),
            Block.empty(panel_width - 4, 1),
            # Progress bar showing seconds toward next minute
            Block.text("progress:", DIM, width=panel_width - 4),
        ]
        progress = (self._second_count % SECONDS_PER_MINUTE) / SECONDS_PER_MINUTE
        pbar = progress_bar(ProgressState(value=progress), panel_width - 6, filled_style=GREEN, empty_style=DIM)
        timer_lines.append(pbar)
        timer_content = join_vertical(*timer_lines)
        timer_panel = border(timer_content, title="TIMERS", style=CYAN if self._is_flashing("second") else DIM, title_style=CYAN_BOLD)

        # Sources panel
        disk_state = self.sources.state("disk") if "disk" in self.sources.kinds else []
        proc_state = self.sources.state("proc") if "proc" in self.sources.kinds else []
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
        health_state = self.infra.state("health") if "health" in self.infra.kinds else {}
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

        # Events (newest first)
        events = list(self._events)[-height:]
        for event in reversed(events):
            ts_str = datetime.fromtimestamp(event.ts).strftime("%H:%M:%S")
            line = f"{ts_str}  {event.source:8s} {event.kind:8s} {event.summary}"
            if len(line) > width - 4:
                line = line[:width - 5] + "…"
            lines.append(Block.text(line, event.style, width=width - 4))

        # Pad to height
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

        # Rebuild vertices
        self._build_vertices()

        self._add_event("reset", "viz", "all state cleared", WHITE_BOLD)
        self.mark_dirty()


# -- Main --------------------------------------------------------------------

async def main():
    app = NestedFlowApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
