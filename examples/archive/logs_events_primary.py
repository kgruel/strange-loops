#!/usr/bin/env python3
"""
Logs Viewer: Events-Primary Architecture

All state changes flow through events. Subscribers derive their own views.

Architecture:
    Input → EventBus → Subscribers
                    → UISubscriber (renders)
                    → FileSubscriber (records)
                    → AlertSubscriber (notifies on errors)
                    → StatsSubscriber (aggregates)

Benefits:
    - Single source of truth (event stream)
    - Replay: record events = record everything
    - Multiple independent views from same data
    - Decoupled: add subscribers without changing core

Run with: uv run examples/logs_events_primary.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rich",
#     "typing_extensions",
# ]
# ///

from __future__ import annotations

import asyncio
import json
import random
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Protocol

from rich.console import Console, Group
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live


# =============================================================================
# EVENTS (the primary output - all state changes are events)
# =============================================================================

def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class StreamStarted:
    """Log stream started."""
    source: str
    max_lines: int | None = None
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {"type": "StreamStarted", **asdict(self)}


@dataclass(frozen=True)
class StreamEnded:
    """Log stream ended."""
    reason: str  # completed, error, interrupted
    total_lines: int
    duration_s: float
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {"type": "StreamEnded", **asdict(self)}


@dataclass(frozen=True)
class LogLine:
    """A log line was received."""
    index: int
    source: str | None
    message: str
    level: str | None
    raw: str
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {"type": "LogLine", **asdict(self)}


@dataclass(frozen=True)
class SourceDiscovered:
    """A new log source was seen (for color assignment)."""
    source: str
    color: str
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {"type": "SourceDiscovered", **asdict(self)}


@dataclass(frozen=True)
class ErrorDetected:
    """An error-level log was detected (for alerting)."""
    index: int
    source: str | None
    message: str
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {"type": "ErrorDetected", **asdict(self)}


# =============================================================================
# EVENT BUS (the spine)
# =============================================================================

# Union type for all events
Event = StreamStarted | StreamEnded | LogLine | SourceDiscovered | ErrorDetected


class Subscriber(Protocol):
    """Protocol for event subscribers."""
    def on_event(self, event: Event) -> None: ...


class EventBus:
    """
    Central event bus. The single source of truth.

    All state changes emit events here.
    Subscribers derive their own state from events.
    """

    def __init__(self):
        self._subscribers: list[Subscriber] = []
        self._history: deque[Event] = deque()  # Could limit with maxlen
        self._started_at: float | None = None

    def subscribe(self, subscriber: Subscriber) -> None:
        """Add a subscriber."""
        self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        """Remove a subscriber."""
        self._subscribers.remove(subscriber)

    def emit(self, event: Event) -> None:
        """Emit an event to all subscribers."""
        if self._started_at is None:
            self._started_at = time.time()
        self._history.append(event)
        for sub in self._subscribers:
            sub.on_event(event)

    @property
    def history(self) -> list[Event]:
        """Full event history (for replay/debugging)."""
        return list(self._history)

    @property
    def elapsed(self) -> float:
        """Time since first event."""
        if self._started_at is None:
            return 0.0
        return time.time() - self._started_at


# =============================================================================
# SUBSCRIBERS (derive state from events)
# =============================================================================

class UISubscriber:
    """
    Derives UI state from events. Renders on demand.

    State:
        - Recent lines (bounded deque)
        - Source colors
        - Stats (counts, rates)
    """

    LEVEL_STYLES = {
        "error": "red bold",
        "warn": "yellow",
        "info": None,
        "debug": "dim",
    }

    def __init__(self, max_visible: int = 20):
        self._max_visible = max_visible
        self._lines: deque[LogLine] = deque(maxlen=max_visible)
        self._source_colors: dict[str, str] = {}
        self._total_lines = 0
        self._error_count = 0
        self._status = "idle"
        self._stream_source: str | None = None

    def on_event(self, event: Event) -> None:
        """Apply event to derive new state."""
        match event:
            case StreamStarted(source=source):
                self._status = "streaming"
                self._stream_source = source
            case StreamEnded(reason=reason):
                self._status = reason
            case LogLine() as line:
                self._lines.append(line)
                self._total_lines += 1
                if line.level == "error":
                    self._error_count += 1
            case SourceDiscovered(source=source, color=color):
                self._source_colors[source] = color

    def render(self, elapsed: float) -> Layout:
        """Render current state to Rich Layout."""
        # Header
        rate = self._total_lines / elapsed if elapsed > 0 else 0
        header_parts = [
            f"[bold]{self._stream_source or 'Logs'}[/bold]",
            f"[dim]{len(self._lines)}/{self._total_lines} lines[/dim]",
            f"[dim]{rate:.1f}/s[/dim]",
        ]
        if self._error_count:
            header_parts.append(f"[red]{self._error_count} errors[/red]")

        header = Panel(" │ ".join(header_parts), expand=False, border_style="dim")

        # Lines
        rendered = [self._render_line(line) for line in self._lines]
        body = Group(*rendered) if rendered else Text("[dim]Waiting for logs...[/dim]")

        layout = Layout()
        layout.split_column(
            Layout(header, name="header", size=3),
            Layout(body, name="logs"),
        )
        return layout

    def _render_line(self, line: LogLine) -> Text:
        text = Text()
        if line.source:
            color = self._source_colors.get(line.source, "white")
            text.append(f"{line.source:12}", style=color)
            text.append(" │ ", style="dim")
        style = self.LEVEL_STYLES.get(line.level) if line.level else None
        text.append(line.message, style=style)
        return text


class FileSubscriber:
    """Records all events to JSONL file."""

    def __init__(self, path: Path):
        self._path = path
        self._file = open(path, "w")

    def on_event(self, event: Event) -> None:
        self._file.write(json.dumps(event.to_dict()) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class FilteredFileSubscriber:
    """Records only events matching a predicate."""

    def __init__(self, path: Path, predicate: Callable[[Event], bool]):
        self._inner = FileSubscriber(path)
        self._predicate = predicate

    def on_event(self, event: Event) -> None:
        if self._predicate(event):
            self._inner.on_event(event)

    def close(self) -> None:
        self._inner.close()


class AlertSubscriber:
    """Tracks errors and could trigger alerts."""

    def __init__(self, threshold: int = 5):
        self._threshold = threshold
        self._recent_errors: deque[ErrorDetected] = deque(maxlen=10)
        self._alert_triggered = False

    def on_event(self, event: Event) -> None:
        if isinstance(event, ErrorDetected):
            self._recent_errors.append(event)
            if len(self._recent_errors) >= self._threshold and not self._alert_triggered:
                self._alert_triggered = True
                # Could emit alert event, send notification, etc.

    @property
    def recent_errors(self) -> list[ErrorDetected]:
        return list(self._recent_errors)


class StatsSubscriber:
    """Aggregates statistics from events."""

    def __init__(self):
        self._total_lines = 0
        self._by_level: dict[str, int] = {}
        self._by_source: dict[str, int] = {}
        self._started_at: float | None = None
        self._ended_at: float | None = None

    def on_event(self, event: Event) -> None:
        match event:
            case StreamStarted():
                self._started_at = event.ts
            case StreamEnded():
                self._ended_at = event.ts
            case LogLine(level=level, source=source):
                self._total_lines += 1
                level_key = level or "none"
                self._by_level[level_key] = self._by_level.get(level_key, 0) + 1
                if source:
                    self._by_source[source] = self._by_source.get(source, 0) + 1

    def summary(self) -> dict:
        duration = (self._ended_at or time.time()) - (self._started_at or time.time())
        return {
            "total_lines": self._total_lines,
            "by_level": self._by_level,
            "by_source": self._by_source,
            "duration_s": duration,
            "rate": self._total_lines / duration if duration > 0 else 0,
        }


# =============================================================================
# LOG SOURCE (emits events from input)
# =============================================================================

SOURCE_COLORS = ["cyan", "green", "yellow", "blue", "magenta", "red"]
MOCK_SOURCES = ["traefik", "postgres", "redis", "api", "worker"]
MOCK_MESSAGES = [
    ("[INFO] Request handled", "info"),
    ("[DEBUG] Cache hit", "debug"),
    ("[WARN] Pool low", "warn"),
    ("[ERROR] Connection failed", "error"),
    ("Health check passed", None),
    ("Starting up...", None),
]


class LogSource:
    """
    Converts raw log input into events.

    This is the only place that emits events.
    All downstream processing is via subscribers.
    """

    def __init__(self, bus: EventBus, name: str = "mock"):
        self._bus = bus
        self._name = name
        self._seen_sources: set[str] = set()
        self._line_index = 0

    def _assign_color(self, source: str) -> None:
        """Emit SourceDiscovered if new source."""
        if source not in self._seen_sources:
            color = SOURCE_COLORS[len(self._seen_sources) % len(SOURCE_COLORS)]
            self._seen_sources.add(source)
            self._bus.emit(SourceDiscovered(source=source, color=color))

    def emit_line(self, source: str | None, message: str, level: str | None, raw: str) -> None:
        """Emit a log line event."""
        if source:
            self._assign_color(source)

        self._bus.emit(LogLine(
            index=self._line_index,
            source=source,
            message=message,
            level=level,
            raw=raw,
        ))
        self._line_index += 1

        # Also emit ErrorDetected for alerting
        if level == "error":
            self._bus.emit(ErrorDetected(
                index=self._line_index - 1,
                source=source,
                message=message,
            ))

    async def stream_mock(self, num_lines: int, delay: float = 0.05) -> None:
        """Generate mock log lines."""
        self._bus.emit(StreamStarted(source=self._name, max_lines=num_lines))
        start = time.time()

        for _ in range(num_lines):
            await asyncio.sleep(delay * random.uniform(0.5, 1.5))

            source = random.choice(MOCK_SOURCES)
            message, level = random.choice(MOCK_MESSAGES)
            raw = f"{source} | {message}"

            self.emit_line(source, message, level, raw)

        self._bus.emit(StreamEnded(
            reason="completed",
            total_lines=self._line_index,
            duration_s=time.time() - start,
        ))


# =============================================================================
# MAIN: WIRE IT ALL TOGETHER
# =============================================================================

async def main():
    console = Console(stderr=True)

    print("\n" + "=" * 60)
    print("EVENTS-PRIMARY ARCHITECTURE DEMO")
    print("=" * 60)
    print("""
This demo shows:
  1. All state changes are events
  2. Multiple subscribers derive independent views
  3. Recording is just another subscriber
    """)

    # Create the bus (the spine)
    bus = EventBus()

    # Create subscribers (each derives its own state)
    ui = UISubscriber(max_visible=15)
    stats = StatsSubscriber()
    alerts = AlertSubscriber(threshold=3)

    # Optional: file recording
    record_path = Path("/tmp/events_primary_demo.jsonl")
    file_sub = FileSubscriber(record_path)

    # Optional: filtered recording (errors only)
    errors_path = Path("/tmp/events_primary_errors.jsonl")
    errors_sub = FilteredFileSubscriber(
        errors_path,
        lambda e: isinstance(e, (ErrorDetected, StreamStarted, StreamEnded))
    )

    # Subscribe all
    bus.subscribe(ui)
    bus.subscribe(stats)
    bus.subscribe(alerts)
    bus.subscribe(file_sub)
    bus.subscribe(errors_sub)

    # Create log source (the only thing that emits)
    source = LogSource(bus, name="demo-stack")

    # Run with live UI
    with Live(console=console, refresh_per_second=20, transient=True) as live:
        async def render_loop():
            while True:
                live.update(ui.render(bus.elapsed))
                await asyncio.sleep(0.05)

        render_task = asyncio.create_task(render_loop())

        try:
            await source.stream_mock(num_lines=50, delay=0.08)
            await asyncio.sleep(0.5)  # Let final renders complete
        finally:
            render_task.cancel()
            try:
                await render_task
            except asyncio.CancelledError:
                pass

    # Cleanup file subscribers
    file_sub.close()
    errors_sub.close()

    # Show results
    console.print()
    console.print("[bold green]Stream completed[/bold green]")

    # Stats summary
    console.print("\n[bold]Stats (from StatsSubscriber):[/bold]")
    s = stats.summary()
    console.print(f"  Total lines: {s['total_lines']}")
    console.print(f"  Duration: {s['duration_s']:.2f}s ({s['rate']:.1f} lines/s)")
    console.print(f"  By level: {s['by_level']}")

    # Alerts
    if alerts.recent_errors:
        console.print(f"\n[bold yellow]Recent errors ({len(alerts.recent_errors)}):[/bold yellow]")
        for err in alerts.recent_errors[-3:]:
            console.print(f"  [{err.source}] {err.message}")

    # Event history
    console.print(f"\n[bold]Event history:[/bold] {len(bus.history)} events")
    by_type: dict[str, int] = {}
    for e in bus.history:
        name = e.__class__.__name__
        by_type[name] = by_type.get(name, 0) + 1
    for name, count in sorted(by_type.items()):
        console.print(f"  {name}: {count}")

    # Files
    console.print(f"\n[dim]Recorded to: {record_path}[/dim]")
    console.print(f"[dim]Errors to: {errors_path}[/dim]")

    # Show what replay looks like
    console.print("\n[bold]Replay capability:[/bold]")
    console.print(f"  Events can reconstruct full UI state.")
    console.print(f"  First 3 events:")
    for e in bus.history[:3]:
        console.print(f"    {e.to_dict()}")


if __name__ == "__main__":
    asyncio.run(main())
