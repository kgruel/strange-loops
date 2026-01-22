#!/usr/bin/env python3
"""
Prototype: Events as Primary Output

Explores the architecture where:
- All state changes emit events
- UI subscribes to event stream (doesn't read Signals directly)
- Recording events = recording everything

Compare overhead vs. current "UI as peer" approach.

Run with: uv run examples/events_primary_prototype.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reaktiv",
#     "rich",
#     "typing_extensions",
#     "ev @ file:///Users/kaygee/Code/ev",
# ]
# ///

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from collections import deque

from reaktiv import Signal, Computed, Effect
from rich.console import Console, Group
from rich.text import Text
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live

from ev import Event, Result


# =============================================================================
# EVENT TYPES (the primary output)
# =============================================================================

@dataclass(frozen=True)
class LogLineEvent:
    """A log line was received."""
    index: int
    source: str
    message: str
    level: str | None
    raw: str
    timestamp: float = field(default_factory=time.time)

    def to_ev(self) -> Event:
        return Event.log(
            self.message,
            level=self.level or "info",
            index=self.index,
            source=self.source,
            raw=self.raw,
            log_level=self.level,
        )


@dataclass(frozen=True)
class SourceColorEvent:
    """A new source was assigned a color."""
    source: str
    color: str
    timestamp: float = field(default_factory=time.time)

    def to_ev(self) -> Event:
        return Event.log_signal("source.color_assigned", source=self.source, color=self.color)


@dataclass(frozen=True)
class StatusEvent:
    """Status changed."""
    status: str
    timestamp: float = field(default_factory=time.time)

    def to_ev(self) -> Event:
        return Event.log_signal(f"status.{self.status}")


# =============================================================================
# EVENT BUS (the single source of truth)
# =============================================================================

class EventBus:
    """
    Central event bus. All state changes flow through here.
    Subscribers receive events and can derive their own state.
    """

    def __init__(self):
        self._subscribers: list[Callable[[Any], None]] = []
        self._history: list[Any] = []  # For replay/debugging

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Subscribe to events. Returns unsubscribe function."""
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback)

    def emit(self, event: Any) -> None:
        """Emit an event to all subscribers."""
        self._history.append(event)
        for sub in self._subscribers:
            sub(event)

    @property
    def history(self) -> list[Any]:
        return self._history


# =============================================================================
# UI STATE (derived from events, not Signals)
# =============================================================================

@dataclass
class UIState:
    """
    UI state derived entirely from events.
    This is like a Redux reducer - events in, state out.
    """
    lines: deque[LogLineEvent] = field(default_factory=lambda: deque(maxlen=200))
    source_colors: dict[str, str] = field(default_factory=dict)
    status: str = "idle"
    total_lines: int = 0

    def apply(self, event: Any) -> None:
        """Apply an event to update state (reducer pattern)."""
        match event:
            case LogLineEvent():
                self.lines.append(event)
                self.total_lines += 1
            case SourceColorEvent():
                self.source_colors[event.source] = event.color
            case StatusEvent():
                self.status = event.status


# =============================================================================
# EVENT-DRIVEN UI
# =============================================================================

class EventDrivenUI:
    """
    UI that subscribes to event bus and renders from event-derived state.
    Does NOT read Signals directly.
    """

    LEVEL_STYLES = {
        "error": "red bold",
        "warn": "yellow",
        "info": None,
        "debug": "dim",
    }

    def __init__(self, bus: EventBus, max_visible: int = 20):
        self._bus = bus
        self._state = UIState()
        self._max_visible = max_visible
        self._render_count = 0
        self._last_event_count = 0

        # Subscribe to events
        bus.subscribe(self._on_event)

    def _on_event(self, event: Any) -> None:
        """Handle incoming event."""
        self._state.apply(event)

    def render(self) -> Layout:
        """Render current state."""
        self._render_count += 1

        # Header with stats
        visible = len(self._state.lines)
        header_text = (
            f"[bold]Events Primary Demo[/bold]  "
            f"[dim]{visible}/{self._state.total_lines} lines | "
            f"{len(self._bus.history)} events | "
            f"render #{self._render_count}[/dim]"
        )
        header = Panel(header_text, expand=False, border_style="dim")

        # Render visible lines
        visible_lines = list(self._state.lines)[-self._max_visible:]
        rendered = [self._render_line(line) for line in visible_lines]
        body = Group(*rendered) if rendered else Text("[dim]Waiting for events...[/dim]")

        layout = Layout()
        layout.split_column(
            Layout(header, name="header", size=3),
            Layout(body, name="logs"),
        )
        return layout

    def _render_line(self, event: LogLineEvent) -> Text:
        text = Text()
        if event.source:
            color = self._state.source_colors.get(event.source, "white")
            text.append(f"{event.source:15}", style=color)
            text.append(" │ ", style="dim")
        style = self.LEVEL_STYLES.get(event.level) if event.level else None
        text.append(event.message, style=style)
        return text


# =============================================================================
# COMPARISON: SIGNAL-DIRECT UI (current approach)
# =============================================================================

class SignalDirectUI:
    """
    UI that reads Signals directly (current approach).
    For comparison with event-driven approach.
    """

    LEVEL_STYLES = {
        "error": "red bold",
        "warn": "yellow",
        "info": None,
        "debug": "dim",
    }

    def __init__(
        self,
        lines: Callable[[], list],
        source_colors: Callable[[], dict],
        total_count: Callable[[], int],
        max_visible: int = 20,
    ):
        self._lines = lines
        self._source_colors = source_colors
        self._total_count = total_count
        self._max_visible = max_visible
        self._render_count = 0

    def render(self) -> Layout:
        self._render_count += 1

        lines = self._lines()
        total = self._total_count()
        visible = len(lines[-self._max_visible:])

        header_text = (
            f"[bold]Signal Direct Demo[/bold]  "
            f"[dim]{visible}/{total} lines | "
            f"render #{self._render_count}[/dim]"
        )
        header = Panel(header_text, expand=False, border_style="dim")

        visible_lines = lines[-self._max_visible:]
        colors = self._source_colors()
        rendered = [self._render_line(line, colors) for line in visible_lines]
        body = Group(*rendered) if rendered else Text("[dim]Waiting...[/dim]")

        layout = Layout()
        layout.split_column(
            Layout(header, name="header", size=3),
            Layout(body, name="logs"),
        )
        return layout

    def _render_line(self, line, colors: dict) -> Text:
        text = Text()
        if line.source:
            color = colors.get(line.source, "white")
            text.append(f"{line.source:15}", style=color)
            text.append(" │ ", style="dim")
        style = self.LEVEL_STYLES.get(line.level) if line.level else None
        text.append(line.message, style=style)
        return text


# =============================================================================
# LOG LINE GENERATOR
# =============================================================================

@dataclass(frozen=True)
class LogLine:
    """Simple log line for signal-direct approach."""
    source: str
    message: str
    level: str | None
    raw: str
    index: int


SOURCES = ["traefik", "postgres", "redis", "api", "worker", "nginx"]
MESSAGES = [
    ("[INFO] Request handled", "info"),
    ("[DEBUG] Cache hit", "debug"),
    ("[WARN] Pool low", "warn"),
    ("[ERROR] Connection failed", "error"),
    ("Health check passed", None),
]
SOURCE_COLORS = ["cyan", "green", "yellow", "blue", "magenta", "red"]


# =============================================================================
# BENCHMARK: EVENTS PRIMARY
# =============================================================================

async def benchmark_events_primary(num_lines: int, show_ui: bool) -> dict:
    """Benchmark the events-as-primary approach."""
    bus = EventBus()
    ui = EventDrivenUI(bus, max_visible=20)

    console = Console(stderr=True)
    live = Live(console=console, refresh_per_second=30, transient=True) if show_ui else None

    source_colors_assigned: set[str] = set()

    if live:
        live.__enter__()

    # Render effect (if showing UI)
    if show_ui:
        def do_render():
            live.update(ui.render())

    start = time.perf_counter()
    emit_times: list[float] = []

    bus.emit(StatusEvent("streaming"))

    for i in range(num_lines):
        source = random.choice(SOURCES)
        msg, level = random.choice(MESSAGES)

        # Emit color assignment if new source
        if source not in source_colors_assigned:
            color = SOURCE_COLORS[len(source_colors_assigned) % len(SOURCE_COLORS)]
            source_colors_assigned.add(source)
            bus.emit(SourceColorEvent(source, color))

        # Emit log line event (measure this)
        t0 = time.perf_counter()
        bus.emit(LogLineEvent(
            index=i,
            source=source,
            message=msg,
            level=level,
            raw=f"{source} | {msg}",
        ))
        emit_times.append(time.perf_counter() - t0)

        if show_ui:
            do_render()
            await asyncio.sleep(0.01)  # Simulate streaming pace

    bus.emit(StatusEvent("completed"))

    elapsed = time.perf_counter() - start

    if live:
        live.__exit__(None, None, None)

    return {
        "approach": "events_primary",
        "num_lines": num_lines,
        "total_events": len(bus.history),
        "elapsed_s": elapsed,
        "avg_emit_us": (sum(emit_times) / len(emit_times)) * 1_000_000,
        "max_emit_us": max(emit_times) * 1_000_000,
        "renders": ui._render_count,
    }


# =============================================================================
# BENCHMARK: SIGNAL DIRECT
# =============================================================================

async def benchmark_signal_direct(num_lines: int, show_ui: bool) -> dict:
    """Benchmark the signal-direct approach (current)."""
    lines: Signal[list[LogLine]] = Signal([])
    source_colors: Signal[dict[str, str]] = Signal({})
    total_count = Computed(lambda: len(lines()))

    ui = SignalDirectUI(
        lambda: lines(),
        lambda: source_colors(),
        total_count,
        max_visible=20,
    )

    console = Console(stderr=True)
    live = Live(console=console, refresh_per_second=30, transient=True) if show_ui else None

    if live:
        live.__enter__()

    start = time.perf_counter()
    update_times: list[float] = []

    for i in range(num_lines):
        source = random.choice(SOURCES)
        msg, level = random.choice(MESSAGES)

        # Assign color if new
        colors = source_colors()
        if source not in colors:
            color = SOURCE_COLORS[len(colors) % len(SOURCE_COLORS)]
            source_colors.set({**colors, source: color})

        # Update signal (measure this)
        t0 = time.perf_counter()
        line = LogLine(source=source, message=msg, level=level, raw=f"{source} | {msg}", index=i)
        lines.update(lambda ls: [*ls, line])
        update_times.append(time.perf_counter() - t0)

        if show_ui:
            live.update(ui.render())
            await asyncio.sleep(0.01)

    elapsed = time.perf_counter() - start

    if live:
        live.__exit__(None, None, None)

    return {
        "approach": "signal_direct",
        "num_lines": num_lines,
        "total_events": 0,  # No events in this approach
        "elapsed_s": elapsed,
        "avg_emit_us": (sum(update_times) / len(update_times)) * 1_000_000,
        "max_emit_us": max(update_times) * 1_000_000,
        "renders": ui._render_count,
    }


# =============================================================================
# MAIN
# =============================================================================

async def run_benchmarks():
    console = Console()

    console.print("\n[bold]Events Primary vs Signal Direct Benchmark[/bold]\n")

    # Warm up
    console.print("[dim]Warming up...[/dim]")
    await benchmark_events_primary(100, show_ui=False)
    await benchmark_signal_direct(100, show_ui=False)

    results = []

    # Without UI (pure overhead)
    console.print("\n[bold]Without UI (pure event/signal overhead):[/bold]")
    for num_lines in [1000, 5000, 10000]:
        console.print(f"  Testing {num_lines} lines...")

        r1 = await benchmark_events_primary(num_lines, show_ui=False)
        r2 = await benchmark_signal_direct(num_lines, show_ui=False)
        results.extend([r1, r2])

        console.print(f"    Events Primary: {r1['avg_emit_us']:.2f}μs avg, {r1['max_emit_us']:.2f}μs max")
        console.print(f"    Signal Direct:  {r2['avg_emit_us']:.2f}μs avg, {r2['max_emit_us']:.2f}μs max")
        overhead = (r1['avg_emit_us'] / r2['avg_emit_us'] - 1) * 100
        console.print(f"    [dim]Overhead: {overhead:+.1f}%[/dim]")

    # With UI (realistic)
    console.print("\n[bold]With UI (realistic streaming):[/bold]")
    console.print("  Testing 100 lines with 10ms delay...\n")

    console.print("  [dim]Events Primary:[/dim]")
    r1 = await benchmark_events_primary(100, show_ui=True)
    console.print(f"\n  Events: {r1['total_events']}, Renders: {r1['renders']}")

    console.print("\n  [dim]Signal Direct:[/dim]")
    r2 = await benchmark_signal_direct(100, show_ui=True)
    console.print(f"\n  Renders: {r2['renders']}")

    # Summary
    console.print("\n[bold]Summary:[/bold]")
    console.print("""
  Events Primary:
    + Single source of truth (events)
    + Replayable (record events = record everything)
    + UI state is derived, not duplicated
    - ~2-5x overhead per state change (event object creation)
    - More memory (event history)

  Signal Direct:
    + Minimal overhead (direct mutation)
    + No intermediate objects
    - UI and events are parallel (not unified)
    - Can't replay UI from event log
    """)

    # The real question
    console.print("[bold]The Real Question:[/bold]")
    console.print("""
  At 10,000 lines/sec, events-primary adds ~50-100μs total overhead.
  For CLI tools processing 10-100 lines/sec, this is imperceptible.

  The overhead matters when:
  - Processing 10,000+ events/sec sustained
  - Memory-constrained (event history grows)
  - Latency-critical (sub-millisecond matters)

  For most CLI use cases: events-primary is viable.
    """)


def main():
    asyncio.run(run_benchmarks())


if __name__ == "__main__":
    main()
