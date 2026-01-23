"""Debug pane: system metrics, rate multiplier, and pluggable mass actions."""

from __future__ import annotations

import resource
import time
from typing import Callable

from reaktiv import Signal
from rich.panel import Panel
from rich.text import Text

from .store import EventStore


_RATE_STEPS = [1.0, 2.0, 5.0, 10.0, 50.0, 100.0]


class DebugPane:
    """Reusable debug pane providing metrics display and simulation rate control.

    Usage:
        debug = DebugPane(store=my_store, actions={"B": ("bulk spawn (10)", spawn_fn)})

    The pane tracks events/sec, render time, memory, and exposes a rate_multiplier
    Signal that simulators can read.

    Actions dict maps key -> (label, callable). The callable is invoked with no args
    when the key is pressed while the debug pane is visible.
    """

    def __init__(
        self,
        store: EventStore,
        *,
        actions: dict[str, tuple[str, Callable[[], None]]] | None = None,
        extra_metrics: Callable[[], list[tuple[str, str]]] | None = None,
    ):
        self.store = store
        self._actions = actions or {}
        self._extra_metrics = extra_metrics

        # Signals
        self.visible = Signal(False)
        self.rate_multiplier: Signal[float] = Signal(1.0)

        # Metrics state
        self._render_time_ms: float = 0.0
        self._last_event_count = 0
        self._last_event_time = time.time()
        self._events_per_sec = 0.0

    def toggle(self) -> None:
        self.visible.update(lambda v: not v)

    def cycle_rate(self, up: bool) -> None:
        current = self.rate_multiplier()
        try:
            idx = _RATE_STEPS.index(current)
        except ValueError:
            idx = 0
        if up:
            idx = min(idx + 1, len(_RATE_STEPS) - 1)
        else:
            idx = max(idx - 1, 0)
        self.rate_multiplier.set(_RATE_STEPS[idx])

    def handle_key(self, key: str) -> bool:
        """Handle debug-specific keys. Returns True if key was consumed."""
        if key == "D":
            self.toggle()
            return True
        if not self.visible():
            return False
        if key == "+":
            self.cycle_rate(up=True)
            return True
        if key == "-":
            self.cycle_rate(up=False)
            return True
        if key in self._actions:
            _, callback = self._actions[key]
            callback()
            return True
        return False

    def record_render_time(self, ms: float) -> None:
        self._render_time_ms = ms

    def render(self) -> Panel:
        """Render the debug pane. Call this from your app's render() method."""
        # Update events/sec
        now = time.time()
        current_total = self.store.total
        dt = now - self._last_event_time
        if dt > 0:
            self._events_per_sec = (current_total - self._last_event_count) / dt
        self._last_event_count = current_total
        self._last_event_time = now

        lines = []

        # Metrics
        lines.append("[bold underline]Metrics[/bold underline]")
        lines.append(f"  Events/sec:     {self._events_per_sec:>8.1f}")
        lines.append(f"  Total events:   {self.store.total:>8d}")
        lines.append(f"  Render time:    {self._render_time_ms:>7.2f} ms")

        # Memory RSS (macOS: ru_maxrss is bytes)
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = rss_bytes / 1048576
        lines.append(f"  Memory (RSS):   {rss_mb:>7.1f} MB")

        # Extra metrics from caller
        if self._extra_metrics:
            for label, value in self._extra_metrics():
                lines.append(f"  {label:<16}{value:>8}")

        lines.append("")

        # Rate control
        lines.append("[bold underline]Controls[/bold underline]")
        rate = self.rate_multiplier()
        rate_str = f"{rate:.0f}x" if rate == int(rate) else f"{rate}x"
        lines.append(f"  Rate multiplier: [bold cyan]{rate_str:>5}[/bold cyan]")
        lines.append("    [dim]+/-[/dim] to adjust")
        lines.append("")

        # Actions
        for key, (label, _) in sorted(self._actions.items()):
            lines.append(f"  [dim]{key}[/dim] = {label}")
        lines.append("  [dim]D[/dim] = hide debug pane")

        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold]Debug[/bold]",
            border_style="magenta",
        )
