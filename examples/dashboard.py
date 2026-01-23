#!/usr/bin/env python3
"""
Dashboard - Step 4: Interactive two-pane dashboard

Features:
- Two panes: Logs (filtered) and Metrics (reaktiv-computed)
- Focus switching with 1/2 keys
- Filter mode with / key (logs pane only)
- Shared EventStore, different views

Run with: uv run examples/dashboard.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rich",
#     "reaktiv",
#     "typing_extensions",
# ]
# ///

from __future__ import annotations

import asyncio
import fnmatch
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from pathlib import Path
from reaktiv import Signal, Computed, Effect, batch
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Framework imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from framework import EventStore, BaseApp


# =============================================================================
# EVENTS (same as interactive_events.py)
# =============================================================================

@dataclass(frozen=True)
class Event:
    source: str
    event_type: str
    payload: dict
    level: str
    ts: float = field(default_factory=time.time)


# =============================================================================
# FILTER QUERY
# =============================================================================

@dataclass
class FilterQuery:
    """
    Filter query supporting:
    - level=error           (exact match)
    - level=warn,error      (OR: matches warn OR error)
    - source=orders         (exact match)
    - event_type=*failed    (glob pattern)
    """
    conditions: list[tuple[str, str, list[str]]] = field(default_factory=list)  # (field, op, values)
    raw: str = ""

    @classmethod
    def parse(cls, query: str) -> "FilterQuery":
        if not query.strip():
            return cls(raw=query)
        conditions = []
        pattern = r'(\w+)\s*=\s*(\S+)'
        for match in re.finditer(pattern, query):
            field, value = match.groups()
            # Support comma-separated OR values
            values = [v.strip() for v in value.split(",")]
            conditions.append((field, "=", values))
        return cls(conditions=conditions, raw=query)

    def matches(self, event: Event) -> bool:
        if not self.conditions:
            return True
        for field, op, values in self.conditions:
            event_value = getattr(event, field, None)
            if event_value is None:
                return False
            # Check if event_value matches ANY of the values (OR logic)
            matched = False
            for value in values:
                if "*" in value:
                    if fnmatch.fnmatch(str(event_value), value):
                        matched = True
                        break
                elif str(event_value) == value:
                    matched = True
                    break
            if not matched:
                return False
        return True

    def description(self) -> str:
        return self.raw if self.conditions else "all"


# =============================================================================
# DASHBOARD MODE (extends framework Mode with SOURCES)
# =============================================================================

class DashboardMode(Enum):
    VIEW = auto()
    FILTER = auto()
    SOURCES = auto()


# =============================================================================
# SOURCE MANAGER
# =============================================================================

AVAILABLE_SOURCES = ["orders", "payments", "inventory", "notifications", "analytics"]

EVENT_TYPES_BY_SOURCE = {
    "orders": [("order.created", "info"), ("order.completed", "info"), ("order.failed", "error")],
    "payments": [("payment.processed", "info"), ("payment.declined", "warn"), ("payment.failed", "error")],
    "inventory": [("inventory.updated", "info"), ("inventory.low", "warn"), ("inventory.out", "error")],
    "notifications": [("notification.sent", "info"), ("notification.failed", "error")],
    "analytics": [("analytics.batch", "info"), ("analytics.error", "error")],
}


class SourceManager:
    """Manages active event sources that can be toggled at runtime."""

    def __init__(self, store: EventStore):
        self._store = store
        self._active_tasks: dict[str, asyncio.Task] = {}
        self.active = Signal[set[str]](set())  # Active sources as Signal

    def is_active(self, source: str) -> bool:
        return source in self.active()

    async def toggle(self, source: str) -> bool:
        """Toggle source on/off. Returns new state."""
        if source in self._active_tasks:
            self._active_tasks[source].cancel()
            try:
                await self._active_tasks[source]
            except asyncio.CancelledError:
                pass
            del self._active_tasks[source]
            self.active.update(lambda s: s - {source})
            return False
        else:
            task = asyncio.create_task(self._run_source(source))
            self._active_tasks[source] = task
            self.active.update(lambda s: s | {source})
            return True

    async def _run_source(self, source: str):
        """Generate events for a source."""
        types = EVENT_TYPES_BY_SOURCE.get(source, [("event", "info")])

        while True:
            await asyncio.sleep(random.uniform(0.3, 0.8))

            event_type, level = random.choice(types)
            # Bias towards info
            if level != "info" and random.random() > 0.3:
                event_type, level = next((t, l) for t, l in types if l == "info")

            self._store.add(Event(
                source=source,
                event_type=event_type,
                payload={"id": f"{source[:3]}-{random.randint(1000, 9999)}"},
                level=level,
            ))

    async def stop_all(self):
        for task in self._active_tasks.values():
            task.cancel()
        for task in self._active_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._active_tasks.clear()
        self.active.set(set())


# =============================================================================
# DASHBOARD
# =============================================================================

LEVEL_STYLES = {"error": "red bold", "warn": "yellow", "info": "white"}
SOURCE_COLORS = {
    "orders": "cyan",
    "payments": "green",
    "inventory": "yellow",
    "notifications": "magenta",
    "analytics": "blue",
}


class Dashboard(BaseApp):
    def __init__(self, store: EventStore, sources: SourceManager, console: Console):
        super().__init__(console)
        self.store = store
        self.sources = sources

        # Override mode signal to support DashboardMode.SOURCES
        self._mode = Signal(DashboardMode.VIEW)
        self._focused_pane = Signal("logs")  # "logs" or "metrics"

        # Domain-specific signals
        self._log_filter = Signal(FilterQuery())
        self._filter_history: Signal[list[str]] = Signal([])  # Recent filter strings
        self._tee_path: Signal[Path | None] = Signal(None)  # Tee output file
        self._tee_count = Signal(0)  # Count of tee'd events
        self._tee_events: Signal[list[Event]] = Signal([])  # Recent tee'd events for display
        self._last_tee_version = 0  # Track which events we've already tee'd

        # Computed metrics - total (depend on store.version)
        self.total_count = Computed(lambda: store.version() and len(store.events) or 0)
        self.error_count = Computed(
            lambda: store.version() and sum(1 for e in store.events if e.level == "error") or 0
        )
        self.warn_count = Computed(
            lambda: store.version() and sum(1 for e in store.events if e.level == "warn") or 0
        )
        self.by_source = Computed(lambda: self._compute_by_source())

        # Computed metrics - filtered (depend on store.version AND _log_filter)
        self.filtered_count = Computed(lambda: self._compute_filtered_count())
        self.filtered_errors = Computed(lambda: self._compute_filtered_errors())
        self.filtered_warns = Computed(lambda: self._compute_filtered_warns())
        self.filtered_by_source = Computed(lambda: self._compute_filtered_by_source())

        # Effect: tee filtered events to file when tee is active
        self._tee_effect = Effect(lambda: self._do_tee())

    def _render_dependencies(self) -> None:
        """Read Signals that should trigger re-render. No Computeds here."""
        self.store.version()
        self._log_filter()
        self._filter_history()
        self._tee_path()
        self._tee_count()
        self._tee_events()
        self.sources.active()

    def _compute_by_source(self) -> dict[str, int]:
        """Compute event counts by source. Depends on store.version."""
        self.store.version()  # Establish dependency
        result: dict[str, int] = {}
        for e in self.store.events:
            result[e.source] = result.get(e.source, 0) + 1
        return result

    def _get_filtered_events(self) -> list[Event]:
        """Get events matching current filter. Establishes dependencies."""
        self.store.version()
        log_filter = self._log_filter()
        return [e for e in self.store.events if log_filter.matches(e)]

    def _compute_filtered_count(self) -> int:
        return len(self._get_filtered_events())

    def _compute_filtered_errors(self) -> int:
        return sum(1 for e in self._get_filtered_events() if e.level == "error")

    def _compute_filtered_warns(self) -> int:
        return sum(1 for e in self._get_filtered_events() if e.level == "warn")

    def _compute_filtered_by_source(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for e in self._get_filtered_events():
            result[e.source] = result.get(e.source, 0) + 1
        return result

    def _do_tee(self) -> None:
        """Effect body: write new filtered events to tee file."""
        version = self.store.version()
        tee_path = self._tee_path()
        log_filter = self._log_filter()

        if not tee_path:
            return

        # Only process new events since last tee
        if version <= self._last_tee_version:
            return

        # Get new events
        new_events = self.store.events[self._last_tee_version:]
        self._last_tee_version = version

        # Filter and write
        matching = [e for e in new_events if log_filter.matches(e)]
        if matching:
            with open(tee_path, "a") as f:
                for event in matching:
                    f.write(json.dumps(asdict(event)) + "\n")
            self._tee_count.update(lambda c: c + len(matching))
            # Keep last 50 for display (will be trimmed by _available_rows)
            self._tee_events.update(lambda evts: (evts + matching)[-50:])

    # =========================================================================
    # KEY HANDLING
    # =========================================================================

    def handle_key(self, key: str) -> bool:
        """Handle keystroke. Returns False if should quit."""
        if self._mode() == DashboardMode.VIEW:
            return self._handle_view_key(key)
        elif self._mode() == DashboardMode.FILTER:
            return self._handle_filter_key(key)
        elif self._mode() == DashboardMode.SOURCES:
            return self._handle_sources_key(key)
        return True

    def _handle_view_key(self, key: str) -> bool:
        if key == "q":
            self._running.set(False)
            return False
        elif key == "1":
            self._focused_pane.set("logs")
        elif key == "2":
            self._focused_pane.set("metrics")
        elif key == "/" and self._focused_pane() == "logs":
            with batch():
                self._mode.set(DashboardMode.FILTER)
                self._input_buffer.set("")
        elif key == "c" and self._focused_pane() == "logs":
            self._log_filter.set(FilterQuery())
        elif key == "e" and self._focused_pane() == "logs":
            self._log_filter.set(FilterQuery.parse("level=error"))
        elif key == "w" and self._focused_pane() == "logs":
            self._log_filter.set(FilterQuery.parse("level=warn"))
        elif key == "a" and self._focused_pane() == "logs":
            self._log_filter.set(FilterQuery())
        elif key == "h" and self._focused_pane() == "logs":
            # Apply most recent filter from history
            history = self._filter_history()
            if history:
                self._log_filter.set(FilterQuery.parse(history[0]))
        elif key == "t" and self._focused_pane() == "logs":
            # Toggle tee
            if self._tee_path():
                with batch():
                    self._tee_path.set(None)
                    self._tee_count.set(0)
                    self._tee_events.set([])
            else:
                tee_file = Path(f"/tmp/tee_{int(time.time())}.jsonl")
                with batch():
                    self._tee_path.set(tee_file)
                    self._tee_count.set(0)
                    self._tee_events.set([])
                self._last_tee_version = self.store.version()  # Start from now
        elif key == "s":
            self._mode.set(DashboardMode.SOURCES)
        return True

    def _handle_sources_key(self, key: str) -> bool:
        """Handle keys in sources mode."""
        if key == "\x1b" or key == "s":
            self._mode.set(DashboardMode.VIEW)
        elif key in "12345":
            idx = int(key) - 1
            if idx < len(AVAILABLE_SOURCES):
                source = AVAILABLE_SOURCES[idx]
                # Schedule toggle (async)
                asyncio.create_task(self.sources.toggle(source))
        return True

    def _handle_filter_key(self, key: str) -> bool:
        if key == "\r" or key == "\n":
            raw = self._input_buffer()
            if raw.strip():
                # Save to history (dedupe, keep last 5)
                self._filter_history.update(lambda h:
                    ([raw] + [x for x in h if x != raw])[:5]
                )
            with batch():
                self._log_filter.set(FilterQuery.parse(raw))
                self._mode.set(DashboardMode.VIEW)
                self._input_buffer.set("")
        elif key == "\x1b":  # Escape
            with batch():
                self._mode.set(DashboardMode.VIEW)
                self._input_buffer.set("")
        elif key == "\x7f":  # Backspace
            self._input_buffer.update(lambda s: s[:-1])
        elif key == "\x1b[A" or key == "":  # Up arrow (partial - see note)
            # Cycle through history
            history = self._filter_history()
            if history:
                current = self._input_buffer()
                try:
                    idx = history.index(current)
                    next_idx = (idx + 1) % len(history)
                except ValueError:
                    next_idx = 0
                self._input_buffer.set(history[next_idx])
        elif key.isprintable():
            self._input_buffer.update(lambda s: s + key)
        return True

    # =========================================================================
    # RENDER
    # =========================================================================

    def render(self) -> Layout:
        layout = Layout()

        # Main content: two panes side by side
        layout.split_column(
            Layout(name="main", ratio=1),
            Layout(self._render_status(), name="status", size=1),
            Layout(self._render_help(), name="help", size=1),
        )

        if self._mode() == DashboardMode.SOURCES:
            # Show sources panel instead of normal panes
            layout["main"].split_row(
                Layout(self._render_sources_pane(), name="sources"),
                Layout(self._render_metrics_pane(), name="metrics"),
            )
        elif self._tee_path():
            # Three panes: logs, tee output, metrics
            layout["main"].split_row(
                Layout(self._render_logs_pane(), name="logs", ratio=3),
                Layout(self._render_tee_pane(), name="tee", ratio=2),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=30),
            )
        else:
            # Two panes: logs gets more space
            layout["main"].split_row(
                Layout(self._render_logs_pane(), name="logs", ratio=2),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=30),
            )

        return layout

    def _render_tee_pane(self) -> Panel:
        """Tee output pane - shows recent tee'd events."""
        tee_events = self._tee_events()
        tee_path = self._tee_path()

        table = Table(
            show_header=False,
            expand=True,
            box=None,
            padding=(0, 1),
        )
        table.add_column("Time", no_wrap=True, style="dim")
        table.add_column("Event", ratio=1)

        max_rows = self._available_rows()
        for event in tee_events[-max_rows:]:
            time_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            level_style = LEVEL_STYLES.get(event.level, "white")
            table.add_row(
                time_str,
                Text(event.event_type, style=level_style),
            )

        if not tee_events:
            table.add_row("", Text("Waiting for matches...", style="dim"))

        tee_count = self._tee_count()
        return Panel(
            table,
            title=f"[bold]Tee[/bold] [dim]({tee_count} → /tmp/)[/dim]",
            border_style="yellow",
        )

    def _render_sources_pane(self) -> Panel:
        """Sources selection panel."""
        table = Table(
            show_header=False,
            expand=True,
            box=None,
            padding=(0, 1),
        )
        table.add_column("Key", no_wrap=True)
        table.add_column("Source", no_wrap=True)
        table.add_column("Status", no_wrap=True)

        for i, source in enumerate(AVAILABLE_SOURCES):
            key = str(i + 1)
            active = self.sources.is_active(source)
            status = "[green]● active[/green]" if active else "[dim]○ off[/dim]"
            color = SOURCE_COLORS.get(source, "white")
            table.add_row(
                f"[bold]{key}[/bold]",
                Text(source, style=color),
                Text.from_markup(status),
            )

        active_list = ", ".join(sorted(self.sources.active())) or "none"
        return Panel(table, title=f"[bold]Sources[/bold] [dim]({active_list})[/dim]", border_style="green")

    def _render_logs_pane(self) -> Panel:
        """Left pane: log viewer with filtering."""
        table = Table(
            show_header=True,
            header_style="bold",
            expand=True,
            box=None,
            padding=(0, 1),
        )
        # Flexible columns: time is fixed-ish, others expand
        table.add_column("Time", no_wrap=True, style="dim")
        table.add_column("Source", no_wrap=True)
        table.add_column("Event", ratio=1)  # Takes remaining space
        table.add_column("Lvl", no_wrap=True)

        # Filter and show events (dynamic row count)
        log_filter = self._log_filter()
        filtered = [e for e in self.store.events if log_filter.matches(e)]
        max_rows = self._available_rows()
        for event in filtered[-max_rows:]:
            time_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            source_style = SOURCE_COLORS.get(event.source, "white")
            level_style = LEVEL_STYLES.get(event.level, "white")

            table.add_row(
                time_str,
                Text(event.source, style=source_style),
                Text(event.event_type, style=level_style),
                Text(event.level, style=level_style),
            )

        border_style = "green" if self._focused_pane() == "logs" else "dim"
        filter_desc = log_filter.description()
        title = f"[bold]Logs[/bold] [dim]({filter_desc})[/dim]"
        return Panel(table, title=title, border_style=border_style)

    def _render_metrics_pane(self) -> Panel:
        """Right pane: reaktiv-computed metrics (total + filtered when filter active)."""
        log_filter = self._log_filter()
        has_filter = bool(log_filter.conditions)

        # Total metrics
        total = self.total_count()
        errors = self.error_count()
        warnings = self.warn_count()
        by_source = self.by_source()

        lines = ["[bold underline]All Events[/bold underline]"]
        lines.append(f"  Total: {total}  [red]err:{errors}[/red]  [yellow]warn:{warnings}[/yellow]")

        if has_filter:
            # Filtered metrics
            f_total = self.filtered_count()
            f_errors = self.filtered_errors()
            f_warnings = self.filtered_warns()
            f_by_source = self.filtered_by_source()

            lines.append("")
            lines.append(f"[bold underline]Filtered ({log_filter.raw})[/bold underline]")
            lines.append(f"  Total: {f_total}  [red]err:{f_errors}[/red]  [yellow]warn:{f_warnings}[/yellow]")
            lines.append("")
            lines.append("  [dim]By Source:[/dim]")
            for source, count in sorted(f_by_source.items(), key=lambda x: -x[1]):
                color = SOURCE_COLORS.get(source, "white")
                lines.append(f"    [{color}]{source}[/{color}]: {count}")
        else:
            lines.append("")
            lines.append("[dim]By Source:[/dim]")
            for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
                color = SOURCE_COLORS.get(source, "white")
                lines.append(f"  [{color}]{source}[/{color}]: {count}")

        border_style = "green" if self._focused_pane() == "metrics" else "dim"
        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold]Metrics[/bold]",
            border_style=border_style,
        )

    def _render_status(self) -> Text:
        if self._mode() == DashboardMode.FILTER:
            history = self._filter_history()
            hist_str = f"  [dim]history: {', '.join(history[:3])}[/dim]" if history else ""
            return Text.from_markup(f"[bold]Filter:[/bold] /{self._input_buffer()}█{hist_str}")

        history = self._filter_history()
        hist_part = f"  [dim]h={history[0]}[/dim]" if history else ""

        tee_path = self._tee_path()
        tee_part = f"  [green]tee:{self._tee_count()} → {tee_path.name}[/green]" if tee_path else ""

        return Text.from_markup(
            f"[bold]Focus:[/bold] {self._focused_pane()}  |  "
            f"[bold]Events:[/bold] {self.store.total}{hist_part}{tee_part}"
        )

    def _render_help(self) -> Text:
        if self._mode() == DashboardMode.FILTER:
            # Show available fields and example syntax
            return Text.from_markup(
                "[dim]Enter[/dim]=apply  [dim]Esc[/dim]=cancel  |  "
                "Fields: [cyan]level[/cyan]=(error,warn,info)  [cyan]source[/cyan]=(orders,payments,...)  [cyan]event_type[/cyan]=*pattern"
            )

        if self._mode() == DashboardMode.SOURCES:
            return Text.from_markup(
                "[dim]1-5[/dim]=toggle source  [dim]s/Esc[/dim]=done"
            )

        if self._focused_pane() == "logs":
            history = self._filter_history()
            h_key = "  [dim]h[/dim]=last" if history else ""
            tee_key = "[dim]t[/dim]=tee-off" if self._tee_path() else "[dim]t[/dim]=tee"
            return Text.from_markup(
                "[dim]1[/dim]=logs  [dim]2[/dim]=metrics  |  "
                f"[dim]/[/dim]=filter  [dim]e[/dim]=errors  [dim]c[/dim]=clear  [dim]s[/dim]=sources{h_key}  {tee_key}  |  "
                "[dim]q[/dim]=quit"
            )
        else:
            return Text.from_markup(
                "[dim]1[/dim]=logs  [dim]2[/dim]=metrics  |  "
                "[dim]s[/dim]=sources  [dim]q[/dim]=quit"
            )


# =============================================================================
# MAIN
# =============================================================================

async def run_dashboard(duration: float | None = None):
    console = Console()

    console.print("\n[bold]Interactive Dashboard[/bold]")
    console.print("Two panes: Logs (filtered) + Metrics (reaktiv-computed)")
    console.print("Press [bold]s[/bold] to manage sources")
    if duration:
        console.print(f"[dim]Running for {duration}s...[/dim]")
    console.print()
    await asyncio.sleep(0.5)

    store: EventStore[Event] = EventStore()
    sources = SourceManager(store)
    app = Dashboard(store, sources, console)

    # Start with some sources active
    await sources.toggle("orders")
    await sources.toggle("payments")

    try:
        await app.run(duration=duration)
    finally:
        await sources.stop_all()

    console.print(f"\n[bold]Done![/bold] {store.total} events")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", "-d", type=float, default=None, help="Run for N seconds (default: until quit)")
    args = parser.parse_args()

    try:
        asyncio.run(run_dashboard(duration=args.duration))
    except KeyboardInterrupt:
        print("\nInterrupted")


if __name__ == "__main__":
    main()
