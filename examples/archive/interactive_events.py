#!/usr/bin/env python3
"""
Interactive Event Viewer - the middle ground between CLI and TUI

Features:
- Events stream in (always recorded)
- Rich Live renders current view
- Keystrokes change the filter (e, w, a for errors/warnings/all)
- Full record happens regardless of view

This is the pattern for:
- Queue watchers
- Log tailers
- Status monitors
- Any "I want to see events as they happen" tool

Run with: uv run examples/interactive_events.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rich",
# ]
# ///

from __future__ import annotations

import asyncio
import json
import random
import sys
import termios
import tty
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable


from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.layout import Layout


# =============================================================================
# EVENT TYPES
# =============================================================================

@dataclass(frozen=True)
class QueueEvent:
    """An event from a message queue."""
    queue: str
    event_type: str
    payload: dict
    level: str  # info, warn, error
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# =============================================================================
# FILTERS
# =============================================================================

@dataclass
class ViewFilter:
    """Current view filter state."""
    level: str | None = None  # None = all, or "error", "warn"
    queue: str | None = None  # None = all queues

    def matches(self, event: QueueEvent) -> bool:
        if self.level and event.level != self.level:
            # "warn" filter shows warn + error
            if self.level == "warn" and event.level not in ("warn", "error"):
                return False
            elif self.level == "error" and event.level != "error":
                return False
        if self.queue and event.queue != self.queue:
            return False
        return True

    def description(self) -> str:
        parts = []
        if self.level:
            parts.append(f"level={self.level}+")
        if self.queue:
            parts.append(f"queue={self.queue}")
        return " ".join(parts) if parts else "all events"


# =============================================================================
# EVENT STORE (always records everything)
# =============================================================================

class EventStore:
    """
    Stores all events. Views filter over this.

    The store is the source of truth. Recording happens here.
    Views are just windows into the store.
    """

    def __init__(self, record_path: Path | None = None):
        self._events: list[QueueEvent] = []
        self._record_file = open(record_path, "w") if record_path else None
        self._subscribers: list[Callable[[QueueEvent], None]] = []

    def add(self, event: QueueEvent) -> None:
        """Add event - always recorded, subscribers notified."""
        self._events.append(event)

        # Record to file
        if self._record_file:
            self._record_file.write(json.dumps(event.to_dict()) + "\n")
            self._record_file.flush()

        # Notify subscribers
        for sub in self._subscribers:
            sub(event)

    def subscribe(self, callback: Callable[[QueueEvent], None]) -> None:
        self._subscribers.append(callback)

    def query(self, filter: ViewFilter, limit: int = 50) -> list[QueueEvent]:
        """Query events matching filter."""
        matching = [e for e in self._events if filter.matches(e)]
        return matching[-limit:]

    @property
    def total(self) -> int:
        return len(self._events)

    def close(self) -> None:
        if self._record_file:
            self._record_file.close()


# =============================================================================
# INTERACTIVE VIEW
# =============================================================================

QUEUE_COLORS = {
    "orders": "cyan",
    "payments": "green",
    "inventory": "yellow",
    "notifications": "magenta",
    "analytics": "blue",
}

LEVEL_STYLES = {
    "error": "red bold",
    "warn": "yellow",
    "info": "white",
}


class InteractiveView:
    """
    Rich Live view with keyboard-driven filtering.

    Keystrokes:
        a - show all
        e - show errors only
        w - show warnings + errors
        1-5 - filter to specific queue
        0 - show all queues
        q - quit
    """

    def __init__(self, store: EventStore, max_visible: int = 20):
        self._store = store
        self._max_visible = max_visible
        self._filter = ViewFilter()
        self._queues = list(QUEUE_COLORS.keys())
        self._running = True
        self._live: Live | None = None

        # Subscribe to new events for live updates
        store.subscribe(self._on_event)

    def _on_event(self, event: QueueEvent) -> None:
        """Called when new event arrives."""
        if self._live:
            self._live.update(self._render())

    def handle_key(self, key: str) -> bool:
        """Handle keystroke. Returns False if should quit."""
        if key == "q":
            self._running = False
            return False
        elif key == "a":
            self._filter.level = None
        elif key == "e":
            self._filter.level = "error"
        elif key == "w":
            self._filter.level = "warn"
        elif key == "0":
            self._filter.queue = None
        elif key in "12345":
            idx = int(key) - 1
            if idx < len(self._queues):
                self._filter.queue = self._queues[idx]

        if self._live:
            self._live.update(self._render())
        return True

    def _render(self) -> Layout:
        """Render current view."""
        # Query events matching current filter
        events = self._store.query(self._filter, self._max_visible)

        # Build table
        table = Table(show_header=True, header_style="bold", expand=True)
        table.add_column("Time", width=10)
        table.add_column("Queue", width=15)
        table.add_column("Type", width=20)
        table.add_column("Payload", ratio=1)

        for event in events:
            time_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            queue_style = QUEUE_COLORS.get(event.queue, "white")
            level_style = LEVEL_STYLES.get(event.level, "white")

            table.add_row(
                Text(time_str, style="dim"),
                Text(event.queue, style=queue_style),
                Text(event.event_type, style=level_style),
                Text(str(event.payload), style="dim", overflow="ellipsis"),
            )

        # Build help bar
        help_parts = [
            "[bold]Keys:[/bold]",
            "[dim]a[/dim]=all",
            "[dim]e[/dim]=errors",
            "[dim]w[/dim]=warn+",
            "[dim]1-5[/dim]=queue",
            "[dim]0[/dim]=all queues",
            "[dim]q[/dim]=quit",
        ]
        help_text = "  ".join(help_parts)

        # Build status bar
        filter_desc = self._filter.description()
        visible = len(events)
        total = self._store.total
        status = f"[bold]Filter:[/bold] {filter_desc}  |  [bold]Showing:[/bold] {visible}/{total} events"

        # Layout
        layout = Layout()
        layout.split_column(
            Layout(Panel(table, title="[bold]Event Stream[/bold]"), name="main"),
            Layout(Text(status), name="status", size=1),
            Layout(Text(help_text), name="help", size=1),
        )
        return layout

    @property
    def running(self) -> bool:
        return self._running

    def set_live(self, live: Live) -> None:
        self._live = live
        self._live.update(self._render())


# =============================================================================
# KEYBOARD INPUT (non-blocking)
# =============================================================================

class KeyboardInput:
    """Non-blocking keyboard input for interactive mode."""

    def __init__(self):
        self._old_settings = None
        self._available = True

    def __enter__(self):
        # Save terminal settings and switch to raw mode
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, OSError):
            # Not a real terminal (e.g., running in background)
            self._available = False
        return self

    def __exit__(self, *args):
        # Restore terminal settings
        if self._old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            except (termios.error, OSError):
                pass

    def get_key(self) -> str | None:
        """Get a key if available (non-blocking)."""
        if not self._available:
            return None
        import select
        try:
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
        except (OSError, ValueError):
            self._available = False
        return None


# =============================================================================
# MOCK EVENT SOURCE
# =============================================================================

QUEUES = ["orders", "payments", "inventory", "notifications", "analytics"]
EVENT_TYPES = [
    ("order.created", "info"),
    ("order.completed", "info"),
    ("order.failed", "error"),
    ("payment.processed", "info"),
    ("payment.declined", "warn"),
    ("payment.failed", "error"),
    ("inventory.low", "warn"),
    ("inventory.out", "error"),
    ("notification.sent", "info"),
    ("analytics.batch", "info"),
]


async def generate_events(store: EventStore, rate: float = 0.3):
    """Generate mock events at given rate."""
    while True:
        await asyncio.sleep(rate * random.uniform(0.5, 1.5))

        queue = random.choice(QUEUES)
        event_type, level = random.choice(EVENT_TYPES)

        # Make errors less common
        if level == "error" and random.random() > 0.3:
            event_type, level = random.choice([e for e in EVENT_TYPES if e[1] == "info"])
        elif level == "warn" and random.random() > 0.5:
            event_type, level = random.choice([e for e in EVENT_TYPES if e[1] == "info"])

        payload = {
            "id": f"{queue[:3]}-{random.randint(1000, 9999)}",
            "value": random.randint(10, 500),
        }

        store.add(QueueEvent(
            queue=queue,
            event_type=event_type,
            payload=payload,
            level=level,
        ))


# =============================================================================
# MAIN
# =============================================================================

async def run_interactive(duration: float | None = None):
    console = Console()

    console.print("\n[bold]Interactive Event Viewer[/bold]")
    console.print("Events stream in. Use keystrokes to filter the view.")
    console.print("Full record saved to /tmp/events.jsonl regardless of filter.")
    if duration:
        console.print(f"[dim]Running for {duration}s (non-interactive mode)[/dim]")
    console.print()
    await asyncio.sleep(0.5)

    # Setup
    record_path = Path("/tmp/events.jsonl")
    store = EventStore(record_path)
    view = InteractiveView(store, max_visible=15)

    # Start event generator
    generator_task = asyncio.create_task(generate_events(store, rate=0.2))

    start_time = time.time()

    try:
        with KeyboardInput() as keyboard:
            with Live(console=console, refresh_per_second=10) as live:
                view.set_live(live)

                while view.running:
                    # Check for duration limit
                    if duration and (time.time() - start_time) > duration:
                        break

                    # Check for keypress
                    key = keyboard.get_key()
                    if key:
                        view.handle_key(key)

                    await asyncio.sleep(0.05)

    finally:
        generator_task.cancel()
        try:
            await generator_task
        except asyncio.CancelledError:
            pass
        store.close()

    # Summary
    console.print(f"\n[bold]Done![/bold] {store.total} events recorded to {record_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Interactive Event Viewer")
    parser.add_argument("--duration", "-d", type=float, help="Run for N seconds then exit")
    args = parser.parse_args()

    try:
        asyncio.run(run_interactive(duration=args.duration))
    except KeyboardInterrupt:
        print("\nInterrupted")


if __name__ == "__main__":
    main()
