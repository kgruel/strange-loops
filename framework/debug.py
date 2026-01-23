"""Debug pane: system metrics, rate multiplier, and pluggable mass actions."""

from __future__ import annotations

import resource
from typing import Callable

from reaktiv import Signal

from render import StyledBlock, Style, join_horizontal, join_vertical, border

from .instrument import metrics
from .store import EventStore
from .ui import sparkline


def _budget_color(pct: float) -> str:
    """Return color name based on frame budget percentage."""
    if pct < 50:
        return "green"
    elif pct < 80:
        return "yellow"
    else:
        return "red"


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

    def render(self) -> StyledBlock:
        """Render the debug pane. Call this from your app's render() method."""
        # Record RSS as a gauge so it shows up alongside instrument data
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = rss_bytes / 1048576
        metrics.gauge("rss_mb", rss_mb)

        snap = metrics.snapshot()
        elapsed = snap["elapsed_sec"]
        timings = snap["timings"]
        counters = snap["counters"]
        gauges = snap["gauges"]

        header = Style(bold=True, underline=True)
        dim = Style(dim=True)
        plain = Style()
        bold = Style(bold=True)

        rows: list[StyledBlock] = []

        # --- Frame budget ---
        render_t = timings.get("render")
        if render_t:
            samples = metrics.timing_samples("render")
            spark = sparkline(samples, width=10, max_value=16.67)
            # Budget: 16.67ms = 60fps target
            budget_pct = (render_t["avg_ms"] / 16.67) * 100
            color = _budget_color(budget_pct)
            rows.append(join_horizontal(
                StyledBlock.text("Frame ", bold),
                StyledBlock.text(spark + " ", plain),
                StyledBlock.text(f"{budget_pct:>3.0f}%", Style(fg=color, bold=True)),
                StyledBlock.text(f"  avg={render_t['avg_ms']:.1f}", dim),
                StyledBlock.text(f" p95={render_t['p95_ms']:.1f}ms", dim),
            ))
            # Projection vs render breakdown
            proj_advance = [n for n in timings if n.endswith(".advance")]
            if proj_advance:
                proj_sum = sum(timings[n]["avg_ms"] for n in proj_advance)
                rows.append(join_horizontal(
                    StyledBlock.text("       ", plain),
                    StyledBlock.text(f"proj={proj_sum:.1f}", dim),
                    StyledBlock.text(f" render={render_t['avg_ms'] - proj_sum:.1f}ms", dim),
                ))
            rows.append(StyledBlock.text("", plain))

        # --- Per-projection metrics ---
        # Extract unique projection names from dot-separated keys: proj.{name}.*
        proj_names: set[str] = set()
        for key in list(timings) + list(counters) + list(gauges):
            if key.startswith("proj."):
                parts = key.split(".")
                if len(parts) >= 3:
                    proj_names.add(parts[1])
        if proj_names:
            rows.append(StyledBlock.text("Projections", header))
            for name in sorted(proj_names):
                advance_t = timings.get(f"proj.{name}.advance")
                avg_ms = advance_t["avg_ms"] if advance_t else 0.0
                fold_rate = metrics.rate(f"proj.{name}.events_folded")
                lag = gauges.get(f"proj.{name}.lag", 0.0)
                # Color lag: green <2ms, yellow <5ms, red >=5ms
                lag_color = "green" if lag < 2 else ("yellow" if lag < 5 else "red")
                rows.append(join_horizontal(
                    StyledBlock.text(f"  {name:<14}", plain),
                    StyledBlock.text(f"avg={avg_ms:>5.1f}", dim),
                    StyledBlock.text(f" {fold_rate:>5.0f}/s", dim),
                    StyledBlock.text(f" lag=", dim),
                    StyledBlock.text(f"{lag:>4.1f}", Style(fg=lag_color)),
                ))
            rows.append(StyledBlock.text("", plain))

        # --- Store breakdown ---
        rows.append(StyledBlock.text("Store", header))
        in_mem = len(self.store.events)
        ev_rate = metrics.rate("events_added")
        store_parts: list[StyledBlock] = [StyledBlock.text("  ", plain)]
        store_parts.append(StyledBlock.text(f"mem={in_mem}", plain))
        store_parts.append(StyledBlock.text(f"  {ev_rate:.0f}ev/s", dim))
        store_parts.append(StyledBlock.text(f"  rss={rss_mb:.0f}MB", dim))
        if self.store._offset > 0:
            store_parts.append(StyledBlock.text(
                f"  evicted={self.store._offset}/{self.store.total}", dim
            ))
        if self.store._file is not None and self.store._path is not None:
            disk_mb = self.store._path.stat().st_size / 1048576
            store_parts.append(StyledBlock.text(f"  disk={disk_mb:.1f}MB", dim))
        rows.append(join_horizontal(*store_parts))
        rows.append(StyledBlock.text("", plain))

        # --- Debounce ratio ---
        frames = counters.get("frames_rendered", 0)
        effects = counters.get("effect_fires", 0)
        if frames > 0 and effects > 0:
            ratio = effects / frames
            rows.append(join_horizontal(
                StyledBlock.text("Debounce ", bold),
                StyledBlock.text(f"{effects}:{frames}", plain),
                StyledBlock.text(f" ({ratio:.1f}x)", dim),
            ))
            rows.append(StyledBlock.text("", plain))

        # --- Other timings (non-render, non-projection) ---
        other_timings = {n: t for n, t in timings.items()
                         if n != "render"
                         and not n.startswith("proj.")}
        if other_timings:
            rows.append(StyledBlock.text("Timings", header))
            for name, t in sorted(other_timings.items()):
                rows.append(join_horizontal(
                    StyledBlock.text(f"  {name:<14}", plain),
                    StyledBlock.text(f"avg={t['avg_ms']:>5.2f}", dim),
                    StyledBlock.text(f" p95={t['p95_ms']:>5.2f}ms", dim),
                ))
            rows.append(StyledBlock.text("", plain))

        # --- Extra metrics (app-specific) ---
        if self._extra_metrics:
            extras = self._extra_metrics()
            if extras:
                for label, value in extras:
                    rows.append(join_horizontal(
                        StyledBlock.text(f"  {label:<14}", plain),
                        StyledBlock.text(value, dim),
                    ))
                rows.append(StyledBlock.text("", plain))

        # --- Controls (compact one-line) ---
        rate = self.rate_multiplier()
        rate_str = f"{rate:.0f}x" if rate == int(rate) else f"{rate}x"
        ctrl_parts = [f"+/-={rate_str}"]
        for key, (label, _) in sorted(self._actions.items()):
            ctrl_parts.append(f"{key}={label}")
        ctrl_parts.append("D=hide")
        rows.append(join_horizontal(
            StyledBlock.text(" ".join(ctrl_parts), dim),
        ))

        content = join_vertical(*rows)
        return border(
            content,
            title="Debug",
            style=Style(fg="magenta"),
            title_style=Style(fg="magenta", bold=True),
        )
