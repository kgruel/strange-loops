#!/usr/bin/env python3
"""
Logs Viewer: Three Architectures Compared

1. Signals Only     - reaktiv drives everything, no ev events
2. Emitters Only    - ev events drive everything, no reaktiv (hlab pattern)
3. Signals → Events - reaktiv for state, Effect emits to ev

Each implements the same functionality:
- Stream log lines from mock source
- Track source colors
- Render UI (bounded visible window)
- Record events (for replay/audit)

Run with: uv run examples/logs_three_ways.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reaktiv",
#     "rich",
#     "typing_extensions",
# ]
# ///

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from rich.console import Console, Group
from rich.text import Text
from rich.panel import Panel
from rich.live import Live


# =============================================================================
# SHARED: Log line type and mock source
# =============================================================================

@dataclass(frozen=True)
class LogLine:
    index: int
    source: str
    message: str
    level: str | None
    ts: float = field(default_factory=time.time)


SOURCES = ["traefik", "postgres", "redis", "api", "worker"]
MESSAGES = [
    ("[INFO] Request handled", "info"),
    ("[DEBUG] Cache hit", "debug"),
    ("[WARN] Pool low", "warn"),
    ("[ERROR] Connection failed", "error"),
]
COLORS = ["cyan", "green", "yellow", "blue", "magenta"]


async def generate_lines(count: int, delay: float = 0.05):
    """Async generator that yields log lines."""
    for i in range(count):
        await asyncio.sleep(delay * random.uniform(0.5, 1.5))
        source = random.choice(SOURCES)
        message, level = random.choice(MESSAGES)
        yield LogLine(index=i, source=source, message=message, level=level)


# =============================================================================
# APPROACH 1: SIGNALS ONLY
# =============================================================================

class SignalsOnlyLogs:
    """
    Pure reaktiv: Signals hold state, Computed derives views, Effect renders.

    Flow:
        lines: Signal ←── update ←── async generator
              ↓
        visible_lines: Computed (last N)
              ↓
        render Effect → Rich Live

    No ev events. Recording would require adding a separate Effect.
    """

    def __init__(self, max_visible: int = 15):
        from reaktiv import Signal, Computed, Effect

        # State
        self._lines: Signal[list[LogLine]] = Signal([])
        self._source_colors: Signal[dict[str, str]] = Signal({})

        # Derived
        self._visible = Computed(lambda: self._lines()[-max_visible:])
        self._total = Computed(lambda: len(self._lines()))

        # Recording (if we wanted it, we'd need another Effect)
        self._recorded: list[dict] = []

        # UI
        self._live: Live | None = None
        self._render_effect: Effect | None = None

    def _assign_color(self, source: str) -> str:
        colors = self._source_colors()
        if source not in colors:
            new_color = COLORS[len(colors) % len(COLORS)]
            self._source_colors.set({**colors, source: new_color})
        return self._source_colors()[source]

    def add_line(self, line: LogLine) -> None:
        """Add a line - triggers reactive updates."""
        self._assign_color(line.source)
        # This is O(n) - copies entire list
        self._lines.update(lambda ls: [*ls, line])

    def _render(self) -> Panel:
        lines = self._visible()
        colors = self._source_colors()

        rendered = []
        for line in lines:
            text = Text()
            color = colors.get(line.source, "white")
            text.append(f"{line.source:12}", style=color)
            text.append(" │ ", style="dim")
            style = {"error": "red bold", "warn": "yellow", "debug": "dim"}.get(line.level)
            text.append(line.message, style=style)
            rendered.append(text)

        body = Group(*rendered) if rendered else Text("[dim]Waiting...[/dim]")
        return Panel(body, title=f"[bold]Signals Only[/bold] ({self._total()} lines)")

    async def run(self, num_lines: int = 30):
        from reaktiv import Effect

        console = Console()
        self._live = Live(console=console, refresh_per_second=20)

        with self._live:
            # Effect auto-runs when signals change
            self._render_effect = Effect(lambda: self._live.update(self._render()))

            async for line in generate_lines(num_lines):
                self.add_line(line)
                # Record manually (no event system)
                self._recorded.append({
                    "type": "LogLine",
                    "index": line.index,
                    "source": line.source,
                    "message": line.message,
                    "level": line.level,
                })

            self._render_effect.dispose()

        return {
            "total": self._total(),
            "recorded": len(self._recorded),
            "sources": list(self._source_colors().keys()),
        }


# =============================================================================
# APPROACH 2: EMITTERS ONLY (hlab pattern)
# =============================================================================

@dataclass
class LogEvent:
    """Event emitted for each log line."""
    type: str
    index: int
    source: str
    message: str
    level: str | None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "index": self.index,
            "source": self.source,
            "message": self.message,
            "level": self.level,
            "ts": self.ts,
        }


class EmittersOnlyLogs:
    """
    Pure ev pattern: Events are primary, emitter maintains mutable state.

    Flow:
        async generator → emit(LogEvent) → Emitter.emit()
                                                ↓
                                    mutable state update
                                                ↓
                                          render UI

    This is how hlab works. State is mutable, updated imperatively on each event.
    """

    def __init__(self, max_visible: int = 15):
        self._max_visible = max_visible

        # Mutable state (updated on each event)
        self._lines: deque[LogLine] = deque(maxlen=max_visible)
        self._source_colors: dict[str, str] = {}
        self._total = 0

        # Recording
        self._recorded: list[dict] = []

        # UI
        self._live: Live | None = None

    def emit(self, event: LogEvent) -> None:
        """Receive event, update state, record, refresh UI."""
        # Record
        self._recorded.append(event.to_dict())

        # Update mutable state
        if event.type == "LogLine":
            line = LogLine(
                index=event.index,
                source=event.source,
                message=event.message,
                level=event.level,
                ts=event.ts,
            )
            self._lines.append(line)  # O(1) - deque append
            self._total += 1

            # Assign color
            if event.source not in self._source_colors:
                self._source_colors[event.source] = COLORS[len(self._source_colors) % len(COLORS)]

        # Refresh UI
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        rendered = []
        for line in self._lines:
            text = Text()
            color = self._source_colors.get(line.source, "white")
            text.append(f"{line.source:12}", style=color)
            text.append(" │ ", style="dim")
            style = {"error": "red bold", "warn": "yellow", "debug": "dim"}.get(line.level)
            text.append(line.message, style=style)
            rendered.append(text)

        body = Group(*rendered) if rendered else Text("[dim]Waiting...[/dim]")
        return Panel(body, title=f"[bold]Emitters Only[/bold] ({self._total} lines)")

    async def run(self, num_lines: int = 30):
        console = Console()
        self._live = Live(console=console, refresh_per_second=20)

        with self._live:
            self._live.update(self._render())

            async for line in generate_lines(num_lines):
                # Emit event (this is what operations do in hlab)
                self.emit(LogEvent(
                    type="LogLine",
                    index=line.index,
                    source=line.source,
                    message=line.message,
                    level=line.level,
                ))

        return {
            "total": self._total,
            "recorded": len(self._recorded),
            "sources": list(self._source_colors.keys()),
        }


# =============================================================================
# APPROACH 3: SIGNALS → COMPUTED → EFFECT(EMITTERS)
# =============================================================================

class SignalsToEmittersLogs:
    """
    Hybrid: Signals for state, Effect bridges to event emission.

    Flow:
        lines: Signal ←── update ←── async generator
              ↓
        visible_lines: Computed
              ↓
        Effect → emit events + render UI

    State is reactive (Signals), but events are emitted for recording/replay.
    Best of both? Or worst of both?
    """

    def __init__(self, max_visible: int = 15):
        from reaktiv import Signal, Computed

        # State (Signals)
        self._lines: Signal[list[LogLine]] = Signal([])
        self._source_colors: Signal[dict[str, str]] = Signal({})

        # Derived
        self._visible = Computed(lambda: self._lines()[-max_visible:])
        self._total = Computed(lambda: len(self._lines()))

        # Event recording (emitter-style)
        self._recorded: list[dict] = []
        self._pending_emissions: list[LogLine] = []

        # UI
        self._live: Live | None = None

    def _assign_color(self, source: str) -> str:
        colors = self._source_colors()
        if source not in colors:
            new_color = COLORS[len(colors) % len(COLORS)]
            self._source_colors.set({**colors, source: new_color})
        return self._source_colors()[source]

    def add_line(self, line: LogLine) -> None:
        """Add a line - queues for emission, updates signal."""
        self._assign_color(line.source)
        self._pending_emissions.append(line)
        self._lines.update(lambda ls: [*ls, line])

    def _emit_pending(self) -> None:
        """Emit queued events (called from Effect or manually)."""
        for line in self._pending_emissions:
            self._recorded.append({
                "type": "LogLine",
                "index": line.index,
                "source": line.source,
                "message": line.message,
                "level": line.level,
                "ts": line.ts,
            })
        self._pending_emissions.clear()

    def _render(self) -> Panel:
        # Emit any pending events
        self._emit_pending()

        lines = self._visible()
        colors = self._source_colors()

        rendered = []
        for line in lines:
            text = Text()
            color = colors.get(line.source, "white")
            text.append(f"{line.source:12}", style=color)
            text.append(" │ ", style="dim")
            style = {"error": "red bold", "warn": "yellow", "debug": "dim"}.get(line.level)
            text.append(line.message, style=style)
            rendered.append(text)

        body = Group(*rendered) if rendered else Text("[dim]Waiting...[/dim]")
        return Panel(body, title=f"[bold]Signals→Events[/bold] ({self._total()} lines)")

    async def run(self, num_lines: int = 30):
        from reaktiv import Effect

        console = Console()
        self._live = Live(console=console, refresh_per_second=20)

        with self._live:
            # Effect renders AND emits events
            render_effect = Effect(lambda: self._live.update(self._render()))

            async for line in generate_lines(num_lines):
                self.add_line(line)

            render_effect.dispose()

        return {
            "total": self._total(),
            "recorded": len(self._recorded),
            "sources": list(self._source_colors().keys()),
        }


# =============================================================================
# COMPARISON RUNNER
# =============================================================================

async def run_comparison():
    console = Console()

    console.print("\n[bold]═══ Logs Viewer: Three Architectures ═══[/bold]\n")

    results = {}

    # 1. Signals Only
    console.print("[bold cyan]1. Signals Only[/bold cyan]")
    console.print("   State: Signal[list] (immutable updates)")
    console.print("   UI: Effect auto-triggers on Signal change")
    console.print("   Recording: Manual (no event system)\n")
    await asyncio.sleep(0.5)

    signals_only = SignalsOnlyLogs()
    results["signals_only"] = await signals_only.run(30)
    console.print()

    await asyncio.sleep(1)

    # 2. Emitters Only
    console.print("[bold green]2. Emitters Only (hlab pattern)[/bold green]")
    console.print("   State: Mutable deque + dict")
    console.print("   UI: Manual refresh on emit()")
    console.print("   Recording: Events captured naturally\n")
    await asyncio.sleep(0.5)

    emitters_only = EmittersOnlyLogs()
    results["emitters_only"] = await emitters_only.run(30)
    console.print()

    await asyncio.sleep(1)

    # 3. Signals → Events
    console.print("[bold yellow]3. Signals → Events (hybrid)[/bold yellow]")
    console.print("   State: Signal[list] (immutable updates)")
    console.print("   UI: Effect renders + emits events")
    console.print("   Recording: Events emitted from Effect\n")
    await asyncio.sleep(0.5)

    hybrid = SignalsToEmittersLogs()
    results["hybrid"] = await hybrid.run(30)
    console.print()

    # Summary
    console.print("\n[bold]═══ Results ═══[/bold]\n")

    for name, r in results.items():
        console.print(f"[bold]{name}[/bold]: {r['total']} lines, {r['recorded']} recorded, {len(r['sources'])} sources")

    console.print("\n[bold]═══ Tradeoffs ═══[/bold]")
    console.print("""
┌─────────────────┬────────────────┬────────────────┬────────────────┐
│ Aspect          │ Signals Only   │ Emitters Only  │ Hybrid         │
├─────────────────┼────────────────┼────────────────┼────────────────┤
│ State mutation  │ Immutable O(n) │ Mutable O(1)   │ Immutable O(n) │
│ UI update       │ Auto (Effect)  │ Manual         │ Auto (Effect)  │
│ Recording       │ Manual/extra   │ Natural        │ In Effect      │
│ Replay          │ Hard           │ Easy           │ Possible       │
│ Complexity      │ Low            │ Low            │ Medium         │
│ Derivations     │ Computed       │ Manual         │ Computed       │
└─────────────────┴────────────────┴────────────────┴────────────────┘

For append-only streams (logs): Emitters Only wins on simplicity + performance.
For complex derived state: Signals Only wins on declarative derivations.
Hybrid adds complexity without clear benefit for this use case.
    """)


def main():
    asyncio.run(run_comparison())


if __name__ == "__main__":
    main()
