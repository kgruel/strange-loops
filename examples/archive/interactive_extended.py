#!/usr/bin/env python3
"""
Extended Interactive CLI - pushing the boundaries

Features:
1. Filter query input (type "type=*declined" to filter)
2. Dynamic source management (add/remove queues at runtime)
3. Mode switching (view mode vs input mode)

This explores: how far can Rich Live + keystrokes go before needing full TUI?

Run with: uv run examples/interactive_extended.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rich",
# ]
# ///

from __future__ import annotations

import asyncio
import fnmatch
import random
import re
import sys
import termios
import tty
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.layout import Layout


# =============================================================================
# EVENTS
# =============================================================================

@dataclass(frozen=True)
class Event:
    source: str  # which queue/stream
    event_type: str
    payload: dict
    level: str
    ts: float = field(default_factory=time.time)


# =============================================================================
# FILTER QUERY LANGUAGE
# =============================================================================

@dataclass
class FilterQuery:
    """
    Parsed filter query supporting:
    - level=error
    - type=*declined (glob)
    - source=payments
    - payload.amount>100 (nested field comparison)
    - Multiple conditions: level=error type=*failed
    """
    conditions: list[tuple[str, str, str]] = field(default_factory=list)  # (field, op, value)
    raw: str = ""

    @classmethod
    def parse(cls, query: str) -> "FilterQuery":
        """Parse a query string into conditions."""
        if not query.strip():
            return cls(raw=query)

        conditions = []
        # Match: field=value, field>value, field<value, field~pattern
        pattern = r'(\w+(?:\.\w+)*)\s*(=|>|<|~)\s*(\S+)'

        for match in re.finditer(pattern, query):
            field, op, value = match.groups()
            conditions.append((field, op, value))

        return cls(conditions=conditions, raw=query)

    def matches(self, event: Event) -> bool:
        """Check if event matches all conditions."""
        if not self.conditions:
            return True

        for field, op, value in self.conditions:
            event_value = self._get_field(event, field)
            if event_value is None:
                return False

            if not self._compare(event_value, op, value):
                return False

        return True

    def _get_field(self, event: Event, field: str) -> Any:
        """Get a field value, supporting nested paths like payload.amount."""
        parts = field.split(".")

        if parts[0] == "payload":
            obj = event.payload
            parts = parts[1:]
        elif hasattr(event, parts[0]):
            if len(parts) == 1:
                return getattr(event, parts[0])
            obj = getattr(event, parts[0])
            parts = parts[1:]
        else:
            return None

        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
        return obj

    def _compare(self, event_value: Any, op: str, query_value: str) -> bool:
        """Compare event value against query value."""
        if op == "=":
            # Support glob patterns
            if "*" in query_value:
                return fnmatch.fnmatch(str(event_value), query_value)
            return str(event_value) == query_value
        elif op == "~":
            # Regex match
            try:
                return bool(re.search(query_value, str(event_value)))
            except re.error:
                return False
        elif op == ">":
            try:
                return float(event_value) > float(query_value)
            except (ValueError, TypeError):
                return False
        elif op == "<":
            try:
                return float(event_value) < float(query_value)
            except (ValueError, TypeError):
                return False
        return False

    def description(self) -> str:
        if not self.conditions:
            return "all events"
        return self.raw


# =============================================================================
# EVENT STORE
# =============================================================================

class EventStore:
    def __init__(self):
        self._events: list[Event] = []
        self._subscribers: list[Callable[[Event], None]] = []

    def add(self, event: Event) -> None:
        self._events.append(event)
        for sub in self._subscribers:
            sub(event)

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subscribers.append(callback)

    def query(self, filter: FilterQuery, limit: int = 50) -> list[Event]:
        matching = [e for e in self._events if filter.matches(e)]
        return matching[-limit:]

    @property
    def total(self) -> int:
        return len(self._events)


# =============================================================================
# SOURCE MANAGER (dynamic queue management)
# =============================================================================

class SourceManager:
    """Manages active event sources that can be added/removed at runtime."""

    def __init__(self, store: EventStore):
        self._store = store
        self._active_sources: dict[str, asyncio.Task] = {}
        self._available_sources = ["orders", "payments", "inventory", "notifications", "analytics"]

    @property
    def available(self) -> list[str]:
        return self._available_sources

    @property
    def active(self) -> list[str]:
        return list(self._active_sources.keys())

    def is_active(self, source: str) -> bool:
        return source in self._active_sources

    async def toggle(self, source: str) -> bool:
        """Toggle a source on/off. Returns new state (True=active)."""
        if source in self._active_sources:
            # Stop it
            self._active_sources[source].cancel()
            try:
                await self._active_sources[source]
            except asyncio.CancelledError:
                pass
            del self._active_sources[source]
            return False
        else:
            # Start it
            task = asyncio.create_task(self._run_source(source))
            self._active_sources[source] = task
            return True

    async def _run_source(self, source: str):
        """Simulate events from a source."""
        event_types = {
            "orders": [("order.created", "info"), ("order.completed", "info"), ("order.failed", "error")],
            "payments": [("payment.processed", "info"), ("payment.declined", "warn"), ("payment.failed", "error")],
            "inventory": [("inventory.updated", "info"), ("inventory.low", "warn"), ("inventory.out", "error")],
            "notifications": [("notification.sent", "info"), ("notification.failed", "error")],
            "analytics": [("analytics.batch", "info"), ("analytics.error", "error")],
        }

        types = event_types.get(source, [("event", "info")])

        while True:
            await asyncio.sleep(random.uniform(0.3, 1.0))

            event_type, level = random.choice(types)
            # Bias towards info
            if level != "info" and random.random() > 0.3:
                event_type, level = next((t, l) for t, l in types if l == "info")

            self._store.add(Event(
                source=source,
                event_type=event_type,
                payload={"id": f"{source[:3]}-{random.randint(1000,9999)}", "amount": random.randint(10, 500)},
                level=level,
            ))

    async def stop_all(self):
        for task in self._active_sources.values():
            task.cancel()
        for task in self._active_sources.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._active_sources.clear()


# =============================================================================
# UI MODES
# =============================================================================

class Mode(Enum):
    VIEW = auto()      # Normal viewing, single-key commands
    FILTER = auto()    # Typing a filter query
    SOURCES = auto()   # Selecting sources


# =============================================================================
# INTERACTIVE VIEW
# =============================================================================

LEVEL_STYLES = {"error": "red bold", "warn": "yellow", "info": "white"}
SOURCE_COLORS = {
    "orders": "cyan",
    "payments": "green",
    "inventory": "yellow",
    "notifications": "magenta",
    "analytics": "blue",
}


class InteractiveView:
    def __init__(self, store: EventStore, sources: SourceManager, max_visible: int = 15):
        self._store = store
        self._sources = sources
        self._max_visible = max_visible

        self._mode = Mode.VIEW
        self._filter = FilterQuery()
        self._input_buffer = ""
        self._running = True
        self._live: Live | None = None

        store.subscribe(self._on_event)

    def _on_event(self, event: Event) -> None:
        if self._live and self._mode == Mode.VIEW:
            self._live.update(self._render())

    async def handle_key(self, key: str) -> bool:
        """Handle keystroke. Returns False if should quit."""

        if self._mode == Mode.VIEW:
            return await self._handle_view_key(key)
        elif self._mode == Mode.FILTER:
            return self._handle_filter_key(key)
        elif self._mode == Mode.SOURCES:
            return await self._handle_sources_key(key)

        return True

    async def _handle_view_key(self, key: str) -> bool:
        if key == "q":
            self._running = False
            return False
        elif key == "/":
            # Enter filter mode
            self._mode = Mode.FILTER
            self._input_buffer = ""
        elif key == "s":
            # Enter sources mode
            self._mode = Mode.SOURCES
        elif key == "c":
            # Clear filter
            self._filter = FilterQuery()
        elif key == "e":
            # Quick filter: errors only
            self._filter = FilterQuery.parse("level=error")
        elif key == "w":
            # Quick filter: warnings+
            self._filter = FilterQuery.parse("level=warn level=error")
        elif key == "a":
            # All events
            self._filter = FilterQuery()

        self._refresh()
        return True

    def _handle_filter_key(self, key: str) -> bool:
        if key == "\r" or key == "\n":
            # Submit filter
            self._filter = FilterQuery.parse(self._input_buffer)
            self._mode = Mode.VIEW
            self._input_buffer = ""
        elif key == "\x1b":  # Escape
            # Cancel
            self._mode = Mode.VIEW
            self._input_buffer = ""
        elif key == "\x7f":  # Backspace
            self._input_buffer = self._input_buffer[:-1]
        elif key.isprintable():
            self._input_buffer += key

        self._refresh()
        return True

    async def _handle_sources_key(self, key: str) -> bool:
        if key == "\x1b" or key == "s":
            # Exit sources mode
            self._mode = Mode.VIEW
        elif key in "12345":
            idx = int(key) - 1
            if idx < len(self._sources.available):
                source = self._sources.available[idx]
                await self._sources.toggle(source)

        self._refresh()
        return True

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Layout:
        layout = Layout()

        if self._mode == Mode.SOURCES:
            layout.split_column(
                Layout(self._render_sources_panel(), name="main"),
                Layout(self._render_status(), name="status", size=1),
                Layout(Text("[dim]1-5[/dim]=toggle  [dim]s/Esc[/dim]=done"), name="help", size=1),
            )
        else:
            layout.split_column(
                Layout(self._render_events_panel(), name="main"),
                Layout(self._render_status(), name="status", size=1),
                Layout(self._render_help(), name="help", size=1),
            )

        return layout

    def _render_events_panel(self) -> Panel:
        events = self._store.query(self._filter, self._max_visible)

        table = Table(show_header=True, header_style="bold", expand=True)
        table.add_column("Time", width=8)
        table.add_column("Source", width=14)
        table.add_column("Type", width=20)
        table.add_column("Payload", ratio=1)

        for event in events:
            time_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            source_style = SOURCE_COLORS.get(event.source, "white")
            level_style = LEVEL_STYLES.get(event.level, "white")

            table.add_row(
                Text(time_str, style="dim"),
                Text(event.source, style=source_style),
                Text(event.event_type, style=level_style),
                Text(str(event.payload), style="dim", overflow="ellipsis"),
            )

        active = ", ".join(self._sources.active) or "none"
        title = f"[bold]Events[/bold] [dim](sources: {active})[/dim]"
        return Panel(table, title=title)

    def _render_sources_panel(self) -> Panel:
        table = Table(show_header=False, expand=True, box=None)
        table.add_column("Key", width=5)
        table.add_column("Source", width=20)
        table.add_column("Status", width=10)

        for i, source in enumerate(self._sources.available):
            key = str(i + 1)
            active = self._sources.is_active(source)
            status = "[green]● active[/green]" if active else "[dim]○ inactive[/dim]"
            color = SOURCE_COLORS.get(source, "white")
            table.add_row(f"[bold]{key}[/bold]", Text(source, style=color), Text.from_markup(status))

        return Panel(table, title="[bold]Select Sources[/bold]")

    def _render_status(self) -> Text:
        if self._mode == Mode.FILTER:
            return Text.from_markup(f"[bold]Filter:[/bold] /{self._input_buffer}█")

        visible = len(self._store.query(self._filter, self._max_visible))
        total = self._store.total
        filter_desc = self._filter.description()
        return Text.from_markup(f"[bold]Filter:[/bold] {filter_desc}  |  [bold]Showing:[/bold] {visible}/{total}")

    def _render_help(self) -> Text:
        if self._mode == Mode.FILTER:
            return Text.from_markup("[dim]Enter[/dim]=apply  [dim]Esc[/dim]=cancel  |  Examples: type=*failed  level=error  payload.amount>100")

        return Text.from_markup(
            "[dim]/[/dim]=filter  [dim]s[/dim]=sources  [dim]a[/dim]=all  [dim]e[/dim]=errors  [dim]c[/dim]=clear  [dim]q[/dim]=quit"
        )

    @property
    def running(self) -> bool:
        return self._running

    def set_live(self, live: Live) -> None:
        self._live = live
        self._refresh()


# =============================================================================
# KEYBOARD INPUT
# =============================================================================

class KeyboardInput:
    def __init__(self):
        self._old_settings = None
        self._available = True

    def __enter__(self):
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, OSError):
            self._available = False
        return self

    def __exit__(self, *args):
        if self._old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            except (termios.error, OSError):
                pass

    def get_key(self) -> str | None:
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
# MAIN
# =============================================================================

async def run_interactive(duration: float | None = None):
    console = Console()

    console.print("\n[bold]Extended Interactive Event Viewer[/bold]")
    console.print("Features: filter queries, dynamic sources\n")
    await asyncio.sleep(0.5)

    store = EventStore()
    sources = SourceManager(store)
    view = InteractiveView(store, sources, max_visible=12)

    # Start with some sources active
    await sources.toggle("orders")
    await sources.toggle("payments")

    start_time = time.time()

    try:
        with KeyboardInput() as keyboard:
            with Live(console=console, refresh_per_second=10) as live:
                view.set_live(live)

                while view.running:
                    if duration and (time.time() - start_time) > duration:
                        break

                    key = keyboard.get_key()
                    if key:
                        await view.handle_key(key)

                    await asyncio.sleep(0.05)

    finally:
        await sources.stop_all()

    console.print(f"\n[bold]Done![/bold] {store.total} events captured")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", "-d", type=float, help="Run for N seconds")
    args = parser.parse_args()

    try:
        asyncio.run(run_interactive(duration=args.duration))
    except KeyboardInterrupt:
        print("\nInterrupted")


if __name__ == "__main__":
    main()
