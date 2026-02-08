"""Source → Vertex Live Wiring: real commands flowing through the pipeline.

Demonstrates the full data flow:
  Source.stream() → Runner → Vertex.receive() → fold → Tick

Uses real shell commands:
  - df: disk usage facts
  - ps: process count facts
  - timer: heartbeat facts (pure timer source)

The Runner orchestrates sources and routes facts through the vertex.
Boundaries fire ticks when sources complete.

Run:
    uv run python experiments/source_vertex/viz.py
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from atoms import Fact
from atoms.source import Source
from atoms.runner import Runner
from atoms.parse import Split, Pick, Rename, Transform, Coerce, Skip
from engine import Vertex, Tick, Loop
from engine.projection import Projection
from cells import Block, Style, join_vertical, join_horizontal, border, pad
from cells.tui import Surface
from cells.widgets import progress_bar, ProgressState


# -- Configuration -----------------------------------------------------------

HEARTBEAT_INTERVAL = 1.0   # Timer tick rate (seconds)
SOURCE_INTERVAL = 5.0      # Disk/proc polling interval
MAX_EVENTS = 25            # Events to show in stream
HEARTBEATS_PER_CYCLE = 5   # Heartbeats before cycle boundary


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
RED_BOLD = Style(fg="red", bold=True)
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

def heartbeat_fold(state: dict, payload: dict) -> dict:
    """Count heartbeats and track timing."""
    return {
        "count": state.get("count", 0) + 1,
        "last_ts": payload.get("tick", time.time()),
    }


def disk_fold(state: dict, payload: dict) -> dict:
    """Accumulate disk usage samples."""
    samples = state.get("samples", [])
    new_sample = {
        "pct": payload.get("pct", 0),
        "mount": payload.get("mount", "/"),
        "ts": time.time(),
    }
    return {
        "samples": (samples + [new_sample])[-10:],  # Keep last 10
        "last_pct": new_sample["pct"],
        "count": state.get("count", 0) + 1,
    }


def proc_fold(state: dict, payload: dict) -> dict:
    """Accumulate process count samples."""
    samples = state.get("samples", [])
    new_sample = {
        "count": payload.get("count", 0),
        "ts": time.time(),
    }
    return {
        "samples": (samples + [new_sample])[-10:],
        "last_count": new_sample["count"],
        "reports": state.get("reports", 0) + 1,
    }


def health_fold(state: dict, payload: dict) -> dict:
    """Aggregate health from disk and proc ticks."""
    return {
        "ticks": state.get("ticks", 0) + 1,
        "last_disk_pct": payload.get("last_pct", state.get("last_disk_pct")),
        "last_proc_count": payload.get("last_count", state.get("last_proc_count")),
        "last_ts": time.time(),
    }


# -- Source Definitions ------------------------------------------------------

def create_heartbeat_source() -> Source:
    """Pure timer source - no command, emits tick facts."""
    return Source(
        command=None,  # Pure timer
        kind="heartbeat",
        observer="timer",
        every=HEARTBEAT_INTERVAL,
    )


def create_disk_source() -> Source:
    """Disk usage source using df command."""
    return Source(
        command="df -P /",
        kind="disk",
        observer="disk-monitor",
        every=SOURCE_INTERVAL,
        format="lines",
        parse=[
            Skip(startswith="Filesystem"),  # Skip header
            Split(),  # Whitespace split
            Pick(4, 5),  # capacity%, mount
            Rename({0: "pct", 1: "mount"}),
            Transform("pct", strip="%"),
            Coerce({"pct": int}),
        ],
    )


def create_proc_source() -> Source:
    """Process count source using ps."""
    return Source(
        command="ps aux | wc -l",
        kind="proc",
        observer="proc-monitor",
        every=SOURCE_INTERVAL,
        format="lines",
        parse=[
            Split(),
            Pick(0),
            Rename({0: "count"}),
            Coerce({"count": int}),
        ],
    )


# -- Main Visualization ------------------------------------------------------

class SourceVertexApp(Surface):
    """Live visualization of Source → Vertex wiring."""

    def __init__(self):
        super().__init__(fps_cap=30, on_emit=self._handle_emit, on_start=self._on_start, on_stop=self._on_stop)
        self._w = 80
        self._h = 40

        # Build vertex hierarchy
        self._build_vertex()

        # Create sources
        self._sources = [
            create_heartbeat_source(),
            create_disk_source(),
            create_proc_source(),
        ]

        # Runner orchestrates sources → vertex
        self._runner = Runner(self._vertex)
        for source in self._sources:
            self._runner.add(source)

        # State tracking
        self._flashes: dict[str, int] = {}
        self._events: deque[EventEntry] = deque(maxlen=MAX_EVENTS)
        self._tick_count = 0
        self._fact_count = 0
        self._last_tick: Tick | None = None
        self._paused = False
        self._runner_task: asyncio.Task | None = None

        # Intercept facts for visualization
        self._original_receive = self._vertex.receive
        self._vertex.receive = self._intercept_receive  # type: ignore

    def _build_vertex(self) -> None:
        """Build the vertex with fold engines."""
        self._vertex = Vertex("root")

        # Heartbeat loop - manual boundary control
        heartbeat_loop = Loop(
            name="heartbeat",
            projection=Projection({"count": 0, "last_ts": 0}, fold=heartbeat_fold),
            boundary_kind="heartbeat.cycle",  # External trigger
            reset=True,
        )
        self._vertex.register_loop(heartbeat_loop)

        # Disk fold - triggered by completion
        self._vertex.register(
            "disk",
            {"samples": [], "last_pct": 0, "count": 0},
            disk_fold,
            boundary="disk.complete",
            reset=False,  # Accumulate across cycles
        )

        # Proc fold - triggered by completion
        self._vertex.register(
            "proc",
            {"samples": [], "last_count": 0, "reports": 0},
            proc_fold,
            boundary="proc.complete",
            reset=False,
        )

        # Health aggregator - fired by tick arrivals
        self._vertex.register(
            "health",
            {"ticks": 0, "last_disk_pct": None, "last_proc_count": None, "last_ts": 0},
            health_fold,
            boundary="health.tick",
            reset=False,
        )

    def _intercept_receive(self, fact: Fact, grant=None, *, _from_child=None) -> Tick | None:
        """Intercept fact reception for visualization."""
        self._fact_count += 1
        kind = fact.kind

        # Flash and log based on kind
        if kind == "heartbeat":
            self._flash("heartbeat")
            self._add_event("heartbeat", "timer", f"tick #{self._fact_count}", CYAN)
            # Check for cycle boundary
            state = self._vertex.state("heartbeat")
            if state["count"] > 0 and state["count"] % HEARTBEATS_PER_CYCLE == 0:
                # Emit cycle boundary fact
                cycle_fact = Fact.of("heartbeat.cycle", "timer", cycle=state["count"] // HEARTBEATS_PER_CYCLE)
                self._original_receive(cycle_fact, grant)
        elif kind == "disk":
            self._flash("disk")
            pct = fact.payload.get("pct", "?")
            self._add_event("disk", "df", f"usage={pct}%", YELLOW)
        elif kind == "proc":
            self._flash("proc")
            count = fact.payload.get("count", "?")
            self._add_event("proc", "ps", f"processes={count}", YELLOW)
        elif kind.endswith(".complete"):
            base = kind.replace(".complete", "")
            self._flash(f"{base}-tick", 8)
            self._add_event(kind, base, "boundary fired", GREEN_BOLD)
        elif kind.endswith(".error") or kind == "source.error":
            self._flash("error", 10)
            err = fact.payload.get("error", "unknown")[:30]
            self._add_event(kind, "error", err, RED_BOLD)

        # Call original receive
        tick = self._original_receive(fact, grant, _from_child=_from_child)

        if tick is not None:
            self._tick_count += 1
            self._last_tick = tick
            self._flash("tick", 10)
            self._add_event(f"tick.{tick.name}", "vertex", f"payload={len(str(tick.payload))}b", MAGENTA_BOLD)

        self.mark_dirty()
        return tick

    def _flash(self, node: str, frames: int = 5) -> None:
        """Start flash effect for a node."""
        self._flashes[node] = frames

    def _is_flashing(self, node: str) -> bool:
        """Check if a node is currently flashing."""
        return self._flashes.get(node, 0) > 0

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

    async def _run_runner(self) -> None:
        """Run the Runner in background."""
        try:
            async for tick in self._runner.run():
                # Ticks already handled in intercept_receive
                pass
        except asyncio.CancelledError:
            pass

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

    def update(self) -> None:
        """Decay flash effects."""
        for node in list(self._flashes.keys()):
            if self._flashes[node] > 0:
                self._flashes[node] -= 1
                self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        content_width = min(self._w - 4, 100)

        # Title
        title_text = "SOURCE → VERTEX LIVE WIRING"
        if self._paused:
            title_text += " [PAUSED]"
        title = Block.text(title_text.center(content_width), WHITE_BOLD, width=content_width)

        # Pipeline diagram
        pipeline = self._render_pipeline(content_width)

        # State panels
        states = self._render_states(content_width)

        # Stats bar
        stats = self._render_stats(content_width)

        # Event stream
        stream = self._render_event_stream(content_width, 10)

        # Help line
        help_text = "[q]uit  [r]eset"
        help_line = Block.text(help_text.center(content_width), DIM, width=content_width)

        content = join_vertical(
            title,
            Block.empty(content_width, 1),
            pipeline,
            Block.empty(content_width, 1),
            states,
            Block.empty(content_width, 1),
            stats,
            Block.empty(content_width, 1),
            stream,
            Block.empty(content_width, 1),
            help_line,
        )

        padded = pad(content, left=2, top=1)

        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _render_pipeline(self, width: int) -> Block:
        """Render the data flow pipeline."""
        lines = []

        # Header
        lines.append(Block.text("DATA FLOW PIPELINE", WHITE_BOLD, width=width))
        lines.append(Block.empty(width, 1))

        # Source → Fact → Vertex → Tick
        def pulse(label: str, active: bool, style: Style, w: int = 12) -> Block:
            char = "●" if active else "○"
            s = style if active else DIM
            return Block.text(f"{char} {label}", s, width=w)

        def arrow(active: bool) -> Block:
            s = CYAN_BOLD if active else DIM
            return Block.text(" → ", s)

        # Row 1: Sources
        src_label = Block.text("Sources:   ", DIM)
        heartbeat_p = pulse("heartbeat", self._is_flashing("heartbeat"), CYAN)
        disk_p = pulse("disk", self._is_flashing("disk"), YELLOW)
        proc_p = pulse("proc", self._is_flashing("proc"), YELLOW)
        src_row = join_horizontal(src_label, heartbeat_p, Block.text("  ", DIM), disk_p, Block.text("  ", DIM), proc_p)
        lines.append(src_row)

        # Arrows down
        lines.append(Block.text("              ↓           ↓           ↓", DIM, width=width))

        # Row 2: Parse
        parse_label = Block.text("Parse:     ", DIM)
        hb_parse = Block.text("(passthru)", DIM, width=12)
        disk_parse = Block.text("df→{pct}", DIM if not self._is_flashing("disk") else YELLOW, width=12)
        proc_parse = Block.text("wc→{count}", DIM if not self._is_flashing("proc") else YELLOW, width=12)
        parse_row = join_horizontal(parse_label, hb_parse, Block.text("  ", DIM), disk_parse, Block.text("  ", DIM), proc_parse)
        lines.append(parse_row)

        # Arrows down to vertex
        lines.append(Block.text("              ↓           ↓           ↓", DIM, width=width))
        lines.append(Block.text("              └─────────→ ● ←─────────┘", CYAN if self._is_flashing("heartbeat") or self._is_flashing("disk") or self._is_flashing("proc") else DIM, width=width))

        # Vertex
        vertex_active = self._is_flashing("heartbeat") or self._is_flashing("disk") or self._is_flashing("proc")
        vertex_line = Block.text("                       VERTEX", CYAN_BOLD if vertex_active else DIM, width=width)
        lines.append(vertex_line)

        # Arrow down to tick
        lines.append(Block.text("                         ↓", DIM, width=width))

        # Tick output
        tick_active = self._is_flashing("tick") or self._is_flashing("disk-tick") or self._is_flashing("proc-tick")
        tick_line = Block.text("                       TICK", MAGENTA_BOLD if tick_active else DIM, width=width)
        lines.append(tick_line)

        content = join_vertical(*lines)
        return border(content, title="PIPELINE", style=DIM, title_style=WHITE_BOLD)

    def _render_states(self, width: int) -> Block:
        """Render current fold states."""
        panel_width = (width - 8) // 3

        # Heartbeat state
        hb_state = self._vertex.state("heartbeat") if "heartbeat" in self._vertex.kinds else {}
        hb_count = hb_state.get("count", 0)
        cycle_progress = (hb_count % HEARTBEATS_PER_CYCLE) / HEARTBEATS_PER_CYCLE
        hb_lines = [
            Block.text(f"count: {hb_count}", CYAN, width=panel_width - 4),
            Block.text(f"cycle: {hb_count // HEARTBEATS_PER_CYCLE}", DIM, width=panel_width - 4),
            Block.text("progress:", DIM, width=panel_width - 4),
            progress_bar(ProgressState(value=cycle_progress), panel_width - 6, filled_style=CYAN, empty_style=DIM),
        ]
        hb_content = join_vertical(*hb_lines)
        hb_panel = border(hb_content, title="HEARTBEAT", style=CYAN if self._is_flashing("heartbeat") else DIM, title_style=CYAN_BOLD)

        # Disk state
        disk_state = self._vertex.state("disk") if "disk" in self._vertex.kinds else {}
        disk_lines = [
            Block.text(f"samples: {disk_state.get('count', 0)}", YELLOW, width=panel_width - 4),
            Block.text(f"last: {disk_state.get('last_pct', '?')}%", DIM, width=panel_width - 4),
        ]
        # Mini sparkline of samples
        samples = disk_state.get("samples", [])
        if samples:
            spark = "".join("▁▂▃▄▅▆▇█"[min(int(s.get("pct", 0) / 12.5), 7)] for s in samples[-8:])
            disk_lines.append(Block.text(f"trend: {spark}", DIM, width=panel_width - 4))
        disk_content = join_vertical(*disk_lines)
        disk_panel = border(disk_content, title="DISK", style=YELLOW if self._is_flashing("disk") else DIM, title_style=YELLOW_BOLD)

        # Proc state
        proc_state = self._vertex.state("proc") if "proc" in self._vertex.kinds else {}
        proc_lines = [
            Block.text(f"reports: {proc_state.get('reports', 0)}", YELLOW, width=panel_width - 4),
            Block.text(f"last: {proc_state.get('last_count', '?')}", DIM, width=panel_width - 4),
        ]
        # Mini sparkline
        proc_samples = proc_state.get("samples", [])
        if proc_samples:
            max_c = max((s.get("count", 1) for s in proc_samples), default=1)
            min_c = min((s.get("count", 0) for s in proc_samples), default=0)
            rng = max(max_c - min_c, 1)
            spark = "".join("▁▂▃▄▅▆▇█"[min(int((s.get("count", 0) - min_c) / rng * 7), 7)] for s in proc_samples[-8:])
            proc_lines.append(Block.text(f"trend: {spark}", DIM, width=panel_width - 4))
        proc_content = join_vertical(*proc_lines)
        proc_panel = border(proc_content, title="PROC", style=YELLOW if self._is_flashing("proc") else DIM, title_style=YELLOW_BOLD)

        return join_horizontal(hb_panel, Block.empty(2, 1), disk_panel, Block.empty(2, 1), proc_panel)

    def _render_stats(self, width: int) -> Block:
        """Render aggregate statistics."""
        stats_text = f"Facts: {self._fact_count}  │  Ticks: {self._tick_count}  │  Sources: {len(self._sources)}"
        return Block.text(stats_text.center(width), DIM, width=width)

    def _render_event_stream(self, width: int, height: int) -> Block:
        """Render scrolling event stream."""
        lines = []

        events = list(self._events)[-height:]
        for event in reversed(events):
            ts_str = datetime.fromtimestamp(event.ts).strftime("%H:%M:%S")
            line = f"{ts_str}  {event.source:10s} {event.kind:18s} {event.summary}"
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
        """Reset all state."""
        self._fact_count = 0
        self._tick_count = 0
        self._events.clear()
        self._flashes.clear()
        self._last_tick = None

        # Rebuild vertex
        self._build_vertex()
        self._vertex.receive = self._intercept_receive  # type: ignore

        # Recreate runner
        self._runner = Runner(self._vertex)
        for source in self._sources:
            self._runner.add(source)

        self._add_event("reset", "viz", "all state cleared", WHITE_BOLD)
        self.mark_dirty()


# -- Main --------------------------------------------------------------------

async def main():
    app = SourceVertexApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
