"""Nested Flow Visualization: animated vertex hierarchy loaded from DSL.

Demonstrates DSL-driven vertex composition:
- root.vertex defines the hierarchy with discover: and sources:
- Python loads the DSL structure via compile_vertex_recursive
- Sources are compiled from .loop files and run via Runner
- ASCII visualization shows live data flow

This is the reference pattern for DSL-based experiments.

Run:
    uv run python experiments/nested_flow/viz.py
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from glob import glob as globfn
from pathlib import Path

from atoms import Fact, Source, Runner
from lang import parse_loop_file, parse_vertex_file, validate
from vertex import compile_loop, compile_vertex_recursive, materialize_vertex
from vertex import Tick, Vertex
from cells import Block, Style, join_vertical, join_horizontal, border, pad
from cells.tui import Surface
from cells.widgets import progress_bar, ProgressState


# -- Configuration -----------------------------------------------------------

MAX_EVENTS = 30           # Events to show in stream
SECONDS_PER_MINUTE = 10   # Accelerated for demo (normally 60)


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


# -- DSL Loading -------------------------------------------------------------

def load_vertex_and_sources(vertex_path: Path) -> tuple[Vertex, list[Source]]:
    """Load a vertex and its sources from DSL files.

    Returns:
        (vertex, sources) - Materialized vertex and compiled sources
    """
    # Parse and compile vertex
    ast = parse_vertex_file(vertex_path)
    validate(ast)
    compiled = compile_vertex_recursive(ast)
    vertex = materialize_vertex(compiled)

    # Compile sources from sources: patterns
    sources: list[Source] = []
    if ast.sources:
        for source_pattern in ast.sources:
            pattern = str(vertex_path.parent / source_pattern)
            for loop_path in globfn(pattern, recursive=True):
                loop_ast = parse_loop_file(Path(loop_path))
                validate(loop_ast)
                sources.append(compile_loop(loop_ast))

    return vertex, sources


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

    Loads the vertex tree from DSL files in nested_flow/:
    - root.vertex defines structure and sources
    - infra/*.vertex define child vertices
    - sources/*.loop and timers/*.loop define data sources
    """

    def __init__(self):
        super().__init__(fps_cap=30, on_emit=self._handle_emit, on_start=self._on_start, on_stop=self._on_stop)
        self._w = 80
        self._h = 40

        # Load from DSL
        vertex_path = Path(__file__).parent / "root.vertex"
        self._vertex, self._sources = load_vertex_and_sources(vertex_path)

        # Runner orchestrates sources
        self._runner = Runner(self._vertex)
        for source in self._sources:
            self._runner.add(source)

        self._runner_task: asyncio.Task | None = None

        # State tracking (state now lives in vertex, we just track UI)
        self._flashes: dict[str, int] = {}
        self._events: deque[EventEntry] = deque(maxlen=MAX_EVENTS)

        # UI state
        self._paused = False

        # Intercept facts for visualization
        self._original_receive = self._vertex.receive
        self._vertex.receive = self._intercept_receive  # type: ignore

    def _intercept_receive(self, fact: Fact, grant=None, *, _from_child=None) -> Tick | None:
        """Intercept fact reception for visualization."""
        kind = fact.kind

        # Flash and log based on kind
        if kind == "second":
            self._flash("second")
            # Get count from vertex state
            state = self._vertex.state("second") if "second" in self._vertex.kinds else {}
            count = state.get("count", 0) if isinstance(state, dict) else 0
            self._add_event("second", "timer", f"count={count + 1}", CYAN)
        elif kind == "disk":
            self._flash("disk")
            pct = fact.payload.get("pct", "?")
            self._add_event("disk", "source", f"usage={pct}%", YELLOW)
        elif kind == "proc":
            self._flash("proc")
            count = fact.payload.get("count", "?")
            self._add_event("proc", "source", f"count={count}", YELLOW)
        elif kind.endswith(".complete"):
            base = kind.replace(".complete", "")
            self._flash(f"{base}-tick", 8)
            self._add_event(kind, base, "boundary fired", GREEN_BOLD)
        elif kind == "source.error":
            self._flash("error", 10)
            err = str(fact.payload.get("error", "unknown"))[:30]
            self._add_event(kind, "error", err, RED)
        elif "health" in kind:
            self._flash("infra", 6)
            self._add_event(kind, "infra", "aggregated", MAGENTA_BOLD)

        # Call original receive
        tick = self._original_receive(fact, grant, _from_child=_from_child)

        if tick is not None:
            self._flash("minute", 8)  # Minute boundary fired
            self._add_event(f"tick.{tick.name}", "root", "minute boundary", GREEN_BOLD)

        self.mark_dirty()
        return tick

    def _flash(self, node: str, frames: int = 5) -> None:
        """Start flash effect for a node."""
        self._flashes[node] = frames

    def _is_flashing(self, node: str) -> bool:
        """Check if a node is currently flashing."""
        return self._flashes.get(node, 0) > 0

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    async def _on_start(self) -> None:
        """Start the runner when TUI mounts."""
        self._runner_task = asyncio.create_task(self._run_runner())

    async def _on_stop(self) -> None:
        """Cleanup when TUI exits."""
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
        await self._runner.stop()

    async def _run_runner(self) -> None:
        """Run the Runner in background."""
        try:
            async for tick in self._runner.run():
                # Ticks already handled in intercept_receive
                pass
        except asyncio.CancelledError:
            pass

    def update(self) -> None:
        """Decay flash effects."""
        for node in list(self._flashes.keys()):
            if self._flashes[node] > 0:
                self._flashes[node] -= 1
                self.mark_dirty()

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
        title_text = "NESTED VERTEX FLOW (DSL)"
        if self._paused:
            title_text += " [PAUSED]"
        title = Block.text(title_text.center(content_width), WHITE_BOLD, width=content_width)

        # Info line
        info_text = f"Loaded: root.vertex | {len(self._sources)} sources"
        info = Block.text(info_text.center(content_width), DIM, width=content_width)

        # Flow diagram
        diagram = self._render_flow_diagram(content_width)

        # State panels
        state_panels = self._render_state_panels(content_width)

        # Event stream
        stream = self._render_event_stream(content_width, 12)

        # Help line
        help_text = "[q]uit  [r]eset"
        help_line = Block.text(help_text.center(content_width), DIM, width=content_width)

        content = join_vertical(
            title,
            info,
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
        lines.append(Block.text("DATA FLOW (from DSL)", WHITE_BOLD, width=width))
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

        # Infra row (from discover: ./infra/*.vertex)
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
        """Render current state from DSL-defined folds."""
        panel_width = (width - 8) // 3

        # Timer state from the 'second' loop (DSL: boundary every 10)
        second_state = self._vertex.state("second") if "second" in self._vertex.kinds else {}
        second_count = second_state.get("count", 0) if isinstance(second_state, dict) else 0
        minute_count = second_count // SECONDS_PER_MINUTE

        timer_lines = [
            Block.text(f"second: {second_count}", CYAN, width=panel_width - 4),
            Block.text(f"minute: {minute_count}", GREEN, width=panel_width - 4),
            Block.empty(panel_width - 4, 1),
            Block.text("progress:", DIM, width=panel_width - 4),
        ]
        progress = (second_count % SECONDS_PER_MINUTE) / SECONDS_PER_MINUTE
        pbar = progress_bar(ProgressState(value=progress), panel_width - 6, filled_style=GREEN, empty_style=DIM)
        timer_lines.append(pbar)
        timer_content = join_vertical(*timer_lines)
        timer_panel = border(timer_content, title="TIMERS", style=CYAN if self._is_flashing("second") else DIM, title_style=CYAN_BOLD)

        # Infra state (disk/proc vertices from DSL discover)
        disk_state = None
        proc_state = None
        for child in self._vertex.children:
            if child.name == "disk":
                disk_state = child.state("usage") if "usage" in child.kinds else {}
            elif child.name == "proc":
                proc_state = child.state("count") if "count" in child.kinds else {}

        source_lines = [
            Block.text("disk:", YELLOW_BOLD, width=panel_width - 4),
        ]
        if disk_state and isinstance(disk_state, dict):
            mounts = disk_state.get("mounts", {})
            if mounts:
                for mount, data in list(mounts.items())[:2]:
                    pct = data.get("pct", "?") if isinstance(data, dict) else "?"
                    source_lines.append(Block.text(f"  {mount}: {pct}%", DIM, width=panel_width - 4))
            else:
                source_lines.append(Block.text("  (waiting)", DIM, width=panel_width - 4))
        else:
            source_lines.append(Block.text("  (waiting)", DIM, width=panel_width - 4))

        source_lines.append(Block.text("proc:", YELLOW_BOLD, width=panel_width - 4))
        if proc_state and isinstance(proc_state, dict):
            total = proc_state.get("total", "?")
            source_lines.append(Block.text(f"  count: {total}", DIM, width=panel_width - 4))
        else:
            source_lines.append(Block.text("  (waiting)", DIM, width=panel_width - 4))

        source_content = join_vertical(*source_lines)
        source_panel = border(source_content, title="INFRA", style=YELLOW if self._is_flashing("disk") or self._is_flashing("proc") else DIM, title_style=YELLOW_BOLD)

        # Health state (root health loop from DSL)
        health_state = self._vertex.state("health") if "health" in self._vertex.kinds else {}
        health_lines = []
        if health_state and isinstance(health_state, dict):
            events = health_state.get("events", [])
            health_lines.append(Block.text(f"events: {len(events)}", MAGENTA, width=panel_width - 4))
            updated = health_state.get("updated")
            if updated:
                health_lines.append(Block.text(f"updated: {updated}", DIM, width=panel_width - 4))
            else:
                health_lines.append(Block.text("updated: -", DIM, width=panel_width - 4))
        else:
            health_lines.append(Block.text("(no data)", DIM, width=panel_width - 4))
        health_content = join_vertical(*health_lines)
        health_panel = border(health_content, title="HEALTH", style=MAGENTA if self._is_flashing("infra") else DIM, title_style=MAGENTA_BOLD)

        return join_horizontal(timer_panel, Block.empty(2, 1), source_panel, Block.empty(2, 1), health_panel)

    def _render_event_stream(self, width: int, height: int) -> Block:
        """Render scrolling event stream."""
        lines = []

        events = list(self._events)[-height:]
        for event in reversed(events):
            ts_str = datetime.fromtimestamp(event.ts).strftime("%H:%M:%S")
            line = f"{ts_str}  {event.source:8s} {event.kind:15s} {event.summary}"
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
        elif key == "r":
            self._reset()

    def _reset(self) -> None:
        """Reset all state by reloading from DSL."""
        self._events.clear()
        self._flashes.clear()

        # Reload from DSL (fresh vertex with reset state)
        vertex_path = Path(__file__).parent / "root.vertex"
        self._vertex, self._sources = load_vertex_and_sources(vertex_path)
        self._vertex.receive = self._intercept_receive  # type: ignore

        # Recreate runner
        self._runner = Runner(self._vertex)
        for source in self._sources:
            self._runner.add(source)

        self._add_event("reset", "viz", "reloaded from DSL", WHITE_BOLD)
        self.mark_dirty()


# -- Main --------------------------------------------------------------------

async def main():
    app = NestedFlowApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
