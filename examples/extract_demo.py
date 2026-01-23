#!/usr/bin/env python3
"""
Minimal demo using cli_framework components.

Demonstrates: EventStore + KeyboardInput + BaseApp + render loop.
Generates random counter events and displays them in a single pane.

Run with: uv run examples/extract_demo.py --duration 3
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
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Allow import from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reaktiv import Signal, Computed
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from framework import EventStore, BaseApp, Mode, FilterHistory


# =============================================================================
# DOMAIN: simple counter events
# =============================================================================

@dataclass(frozen=True)
class CounterEvent:
    source: str
    value: int
    ts: float = field(default_factory=time.time)


SOURCES = ["alpha", "beta", "gamma"]


# =============================================================================
# APP
# =============================================================================

class DemoApp(BaseApp):
    def __init__(self, store: EventStore[CounterEvent], console: Console):
        super().__init__(console)
        self.store = store
        self._focused_pane.set("events")
        self._filter_history = FilterHistory()

        # Computed metrics
        self.event_count = Computed(lambda: self.store.version() and self.store.total)
        self.sum_by_source = Computed(lambda: self._compute_sums())

    def _render_dependencies(self) -> None:
        self.store.version()

    def _compute_sums(self) -> dict[str, int]:
        self.store.version()
        result: dict[str, int] = {}
        for e in self.store.events:
            result[e.source] = result.get(e.source, 0) + e.value
        return result

    def handle_key(self, key: str) -> bool:
        if self._mode() == Mode.FILTER:
            if key == "\x1b":
                self._mode.set(Mode.VIEW)
                self._input_buffer.set("")
            elif key == "\r" or key == "\n":
                raw = self._input_buffer()
                self._filter_history.push(raw)
                self._mode.set(Mode.VIEW)
                self._input_buffer.set("")
            elif key == "\x7f":
                self._input_buffer.update(lambda s: s[:-1])
            elif key.isprintable():
                self._input_buffer.update(lambda s: s + key)
            return True

        if key == "q":
            self._running.set(False)
            return False
        elif key == "/":
            self._mode.set(Mode.FILTER)
            self._input_buffer.set("")
        return True

    def render(self):
        # Read dependencies for effect tracking
        self.store.version()
        self._mode()
        self._input_buffer()

        layout = Layout()
        layout.split_column(
            Layout(name="main", ratio=1),
            Layout(self._render_status(), name="status", size=1),
            Layout(self._render_help(), name="help", size=1),
        )
        layout["main"].split_row(
            Layout(self._render_events(), name="events", ratio=2),
            Layout(self._render_metrics(), name="metrics", minimum_size=25),
        )
        return layout

    def _render_events(self) -> Panel:
        table = Table(show_header=True, header_style="bold", expand=True, box=None, padding=(0, 1))
        table.add_column("Time", no_wrap=True, style="dim")
        table.add_column("Source", no_wrap=True)
        table.add_column("Value", justify="right")

        max_rows = self._available_rows()
        for event in self.store.events[-max_rows:]:
            time_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            table.add_row(time_str, event.source, str(event.value))

        return Panel(table, title="[bold]Events[/bold]", border_style="green")

    def _render_metrics(self) -> Panel:
        sums = self.sum_by_source()
        lines = [f"[bold]Total:[/bold] {self.event_count()}", ""]
        for source in SOURCES:
            total = sums.get(source, 0)
            lines.append(f"  {source}: {total}")
        return Panel(Text.from_markup("\n".join(lines)), title="[bold]Metrics[/bold]", border_style="dim")

    def _render_status(self) -> Text:
        if self._mode() == Mode.FILTER:
            return Text.from_markup(f"[bold]Filter:[/bold] /{self._input_buffer()}\u2588")
        return Text.from_markup(f"[bold]Events:[/bold] {self.store.total}")

    def _render_help(self) -> Text:
        if self._mode() == Mode.FILTER:
            return Text.from_markup("[dim]Enter[/dim]=apply  [dim]Esc[/dim]=cancel")
        return Text.from_markup("[dim]/[/dim]=filter  [dim]q[/dim]=quit")


# =============================================================================
# MAIN
# =============================================================================

async def run_demo(duration: float | None = None):
    console = Console()
    console.print("\n[bold]cli_framework demo[/bold]")
    console.print("EventStore + BaseApp + KeyboardInput + FilterHistory")
    if duration:
        console.print(f"[dim]Running for {duration}s...[/dim]")
    console.print()
    await asyncio.sleep(0.3)

    store: EventStore[CounterEvent] = EventStore()
    app = DemoApp(store, console)

    # Background event generator
    async def generate():
        while app.running:
            await asyncio.sleep(random.uniform(0.2, 0.5))
            store.add(CounterEvent(
                source=random.choice(SOURCES),
                value=random.randint(1, 100),
            ))

    gen_task = asyncio.create_task(generate())

    try:
        await app.run(duration=duration)
    finally:
        gen_task.cancel()
        try:
            await gen_task
        except asyncio.CancelledError:
            pass

    console.print(f"\n[bold]Done![/bold] {store.total} events")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", "-d", type=float, default=None)
    args = parser.parse_args()

    try:
        asyncio.run(run_demo(duration=args.duration))
    except KeyboardInterrupt:
        print("\nInterrupted")


if __name__ == "__main__":
    main()
