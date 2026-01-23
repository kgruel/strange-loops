"""Debug pane: system metrics, rate multiplier, and pluggable mass actions."""

from __future__ import annotations

import resource
from typing import Callable

from reaktiv import Signal
from rich.panel import Panel
from rich.text import Text

from .instrument import metrics
from .store import EventStore


_RATE_STEPS = [1.0, 2.0, 5.0, 10.0, 50.0, 100.0]


class DebugPane:
    """Reusable debug pane providing metrics display and simulation rate control.

    Reads live instrumentation data from the ``metrics`` singleton
    (framework.instrument) when visible. Metrics collection is enabled
    automatically on show and disabled on hide (zero-cost when hidden).

    Usage:
        debug = DebugPane(store=my_store, actions={"B": ("bulk spawn (10)", spawn_fn)})

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

    def toggle(self) -> None:
        currently_visible = self.visible()
        self.visible.set(not currently_visible)
        if not currently_visible:
            # Becoming visible — enable metrics collection
            metrics.enable()
        else:
            # Becoming hidden — disable (zero-cost)
            metrics.disable()

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
        """Legacy hook — render timing now comes from metrics.time('render')."""
        pass

    def render(self) -> Panel:
        """Render the debug pane. Call this from your app's render() method."""
        # Record RSS as a gauge so it shows up alongside instrument data
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = rss_bytes / 1048576
        metrics.gauge("rss_mb", rss_mb)

        snap = metrics.snapshot()

        lines = []

        # --- Counters ---
        if snap["counters"]:
            lines.append("[bold underline]Counters[/bold underline]")
            elapsed = snap["elapsed_sec"]
            for name, val in sorted(snap["counters"].items()):
                rate = val / elapsed if elapsed > 0 else 0.0
                lines.append(f"  {name:<20} {val:>7,}  ({rate:>6.1f}/s)")
            lines.append("")

        # --- Timings ---
        if snap["timings"]:
            lines.append("[bold underline]Timings[/bold underline]")
            for name, t in sorted(snap["timings"].items()):
                lines.append(
                    f"  {name:<20} last={t['last_ms']:>6.2f}  "
                    f"avg={t['avg_ms']:>6.2f}  p95={t['p95_ms']:>6.2f} ms"
                )
            lines.append("")

        # --- Gauges ---
        if snap["gauges"]:
            lines.append("[bold underline]Gauges[/bold underline]")
            for name, val in sorted(snap["gauges"].items()):
                lines.append(f"  {name:<20} {val:>10.1f}")
            lines.append("")

        # Extra metrics from caller (app-specific)
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
