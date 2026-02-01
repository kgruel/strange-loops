"""Cadence Visualization: animated heartbeat hierarchy.

Demonstrates the Cadence/Source split with nested timer loops:
- Pulse (1s) → Breath (5 pulses) → Minute (12 breaths)
- Triggered sources that fold facts from lower levels
- Feedback loop: variance → rate adjustment
- Full TUI with maximum fidelity visualization

Run:
    uv run python experiments/cadence_viz.py
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from data import Fact
from vertex import Peer, Vertex, Tick
from cells import Block, Style, Cell, join_vertical, join_horizontal, border, pad, ROUNDED
from cells.tui import Surface
from cells.widgets import progress_bar, ProgressState


# -- Configuration -----------------------------------------------------------

PULSE_INTERVAL = 1.0      # Base pulse rate (seconds)
PULSES_PER_BREATH = 5     # Pulses before breath boundary
BREATHS_PER_MINUTE = 12   # Breaths before minute boundary
MAX_FACT_STREAM = 20      # Facts to display in stream
RATE_HISTORY_SIZE = 60    # Samples for sparkline


# -- Styles ------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
CYAN = Style(fg="cyan")
CYAN_BOLD = Style(fg="cyan", bold=True)
GREEN = Style(fg="green")
GREEN_BOLD = Style(fg="green", bold=True)
YELLOW = Style(fg="yellow")
YELLOW_BOLD = Style(fg="yellow", bold=True)
RED = Style(fg="red")
MAGENTA = Style(fg="magenta")
MAGENTA_BOLD = Style(fg="magenta", bold=True)
WHITE_BOLD = Style(bold=True)


# -- Sparkline Rendering -----------------------------------------------------

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int, style: Style = DIM) -> Block:
    """Render values as a braille-style sparkline."""
    if not values:
        return Block.text("─" * width, style, width=width)

    # Normalize to 0-1 range
    min_v = min(values)
    max_v = max(values)
    rng = max_v - min_v if max_v != min_v else 1.0

    # Sample or pad to width
    if len(values) >= width:
        sampled = values[-width:]
    else:
        sampled = values

    chars = []
    for v in sampled:
        normalized = (v - min_v) / rng
        idx = min(int(normalized * (len(SPARK_CHARS) - 1)), len(SPARK_CHARS) - 1)
        chars.append(SPARK_CHARS[idx])

    # Pad left if needed
    result = "".join(chars).rjust(width, "─")
    return Block.text(result, style, width=width)


# -- Fold Functions ----------------------------------------------------------

def pulse_fold(state: dict, payload: dict) -> dict:
    """Fold pulse facts: count, track rate, calculate jitter."""
    ts = payload.get("ts", time.time())
    count = state["count"] + 1

    # Track intervals for jitter calculation
    intervals = list(state["intervals"])
    if state["last_ts"] > 0:
        interval = ts - state["last_ts"]
        intervals.append(interval)
        if len(intervals) > 10:
            intervals = intervals[-10:]

    # Calculate jitter (stddev of intervals)
    jitter = 0.0
    if len(intervals) >= 2:
        mean = sum(intervals) / len(intervals)
        variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
        jitter = variance ** 0.5

    return {
        "count": count,
        "last_ts": ts,
        "intervals": intervals,
        "jitter": jitter,
        "avg_rate": sum(intervals) / len(intervals) if intervals else 1.0,
    }


def breath_fold(state: dict, payload: dict) -> dict:
    """Fold breath facts: aggregate pulse summaries."""
    pulse_count = state["pulse_count"] + payload.get("pulse_count", 1)
    rates = list(state["rates"])
    if "avg_rate" in payload:
        rates.append(payload["avg_rate"])
        if len(rates) > PULSES_PER_BREATH:
            rates = rates[-PULSES_PER_BREATH:]

    avg_rate = sum(rates) / len(rates) if rates else 1.0
    drift = avg_rate - PULSE_INTERVAL

    return {
        "pulse_count": pulse_count,
        "breath_count": state["breath_count"],
        "rates": rates,
        "avg_rate": avg_rate,
        "drift": drift,
    }


def minute_fold(state: dict, payload: dict) -> dict:
    """Fold minute facts: aggregate breath summaries."""
    total_pulses = state["total_pulses"] + payload.get("pulse_count", 0)
    breath_count = state["breath_count"] + 1

    rates = list(state["rates"])
    if "avg_rate" in payload:
        rates.append(payload["avg_rate"])
        if len(rates) > BREATHS_PER_MINUTE:
            rates = rates[-BREATHS_PER_MINUTE:]

    avg_rate = sum(rates) / len(rates) if rates else 1.0

    # Calculate variance
    variance = 0.0
    if len(rates) >= 2:
        mean = sum(rates) / len(rates)
        variance = sum((x - mean) ** 2 for x in rates) / len(rates)

    # Health score: 1.0 = perfect, 0.0 = bad
    # Based on how close avg_rate is to target and variance
    rate_error = abs(avg_rate - PULSE_INTERVAL) / PULSE_INTERVAL
    health = max(0.0, 1.0 - rate_error - variance * 10)

    return {
        "total_pulses": total_pulses,
        "breath_count": breath_count,
        "rates": rates,
        "avg_rate": avg_rate,
        "variance": variance,
        "health": health,
        "last_report": time.time(),
    }


# -- Initial States ----------------------------------------------------------

PULSE_INITIAL = {
    "count": 0,
    "last_ts": 0.0,
    "intervals": [],
    "jitter": 0.0,
    "avg_rate": 1.0,
}

BREATH_INITIAL = {
    "pulse_count": 0,
    "breath_count": 0,
    "rates": [],
    "avg_rate": 1.0,
    "drift": 0.0,
}

MINUTE_INITIAL = {
    "total_pulses": 0,
    "breath_count": 0,
    "rates": [],
    "avg_rate": 1.0,
    "variance": 0.0,
    "health": 1.0,
    "last_report": 0.0,
}


# -- Fact Stream Entry -------------------------------------------------------

@dataclass(frozen=True)
class FactEntry:
    """A fact in the stream display."""
    ts: float
    kind: str
    summary: str
    style: Style = DIM


# -- Visualization Helpers ---------------------------------------------------

def render_dots(count: int, total: int, active_style: Style, inactive_style: Style, width: int) -> Block:
    """Render a row of dots showing progress."""
    cells = []
    dots_width = min(total, width - 10)  # Leave room for count

    for i in range(dots_width):
        if i < count % total:
            cells.append(Cell("●", active_style))
        else:
            cells.append(Cell("○", inactive_style))

    # Add count
    count_str = f" [{count}/{total}]"
    for ch in count_str:
        cells.append(Cell(ch, DIM))

    # Pad to width
    while len(cells) < width:
        cells.append(Cell(" ", Style()))

    return Block([cells[:width]], width)


def render_pulse_panel(pulse_state: dict, breath_progress: float, width: int) -> Block:
    """Render the pulse panel with animated dots and progress bar."""
    lines = []

    # Header
    lines.append(Block.text("PULSE", CYAN_BOLD, width=width))
    lines.append(Block.empty(width, 1))

    # Pulse dots (show position within current breath)
    pulse_in_breath = pulse_state["count"] % PULSES_PER_BREATH
    dots = render_dots(pulse_in_breath, PULSES_PER_BREATH, CYAN_BOLD, DIM, width)
    lines.append(dots)
    lines.append(Block.empty(width, 1))

    # Stats line
    rate_str = f"rate: {pulse_state['avg_rate']:.3f}s"
    jitter_str = f"jitter: ±{pulse_state['jitter']*1000:.1f}ms"
    stats = f"{rate_str}  {jitter_str}"
    lines.append(Block.text(stats, DIM, width=width))
    lines.append(Block.empty(width, 1))

    # Progress bar toward next breath
    progress = ProgressState(value=breath_progress)
    bar = progress_bar(progress, width - 6, filled_style=CYAN, empty_style=DIM)
    pct_str = f" {int(breath_progress * 100):3d}%"
    pct_block = Block.text(pct_str, DIM)
    bar_line = join_horizontal(bar, pct_block)
    lines.append(bar_line)

    return join_vertical(*lines)


def render_breath_panel(breath_state: dict, width: int) -> Block:
    """Render the breath panel with breath count and stats."""
    lines = []

    # Header
    lines.append(Block.text("BREATH", GREEN_BOLD, width=width))
    lines.append(Block.empty(width, 1))

    # Breath dots
    breath_count = breath_state["breath_count"]
    breath_in_minute = breath_count % BREATHS_PER_MINUTE
    dots = render_dots(breath_in_minute, BREATHS_PER_MINUTE, GREEN_BOLD, DIM, min(width, BREATHS_PER_MINUTE + 10))
    lines.append(dots)
    lines.append(Block.empty(width, 1))

    # Stats
    lines.append(Block.text(f"pulses: {breath_state['pulse_count']}", DIM, width=width))
    lines.append(Block.text(f"avg_rate: {breath_state['avg_rate']:.3f}s", DIM, width=width))

    # Drift with color
    drift = breath_state["drift"]
    drift_style = GREEN if abs(drift) < 0.01 else YELLOW if abs(drift) < 0.05 else RED
    drift_sign = "+" if drift >= 0 else ""
    lines.append(Block.text(f"drift: {drift_sign}{drift*1000:.1f}ms", drift_style, width=width))

    return join_vertical(*lines)


def render_minute_panel(minute_state: dict, width: int) -> Block:
    """Render the minute panel with aggregated stats and health."""
    lines = []

    # Header
    lines.append(Block.text("MINUTE", MAGENTA_BOLD, width=width))
    lines.append(Block.empty(width, 1))

    # Counts
    lines.append(Block.text(f"breaths: {minute_state['breath_count']}/{BREATHS_PER_MINUTE}", DIM, width=width))
    lines.append(Block.text(f"pulses: {minute_state['total_pulses']}/{PULSES_PER_BREATH * BREATHS_PER_MINUTE}", DIM, width=width))
    lines.append(Block.empty(width, 1))

    # Rate stats
    lines.append(Block.text(f"avg rate: {minute_state['avg_rate']:.3f}s", DIM, width=width))
    lines.append(Block.text(f"variance: ±{minute_state['variance']*1000:.2f}ms", DIM, width=width))
    lines.append(Block.empty(width, 1))

    # Health bar
    health = minute_state["health"]
    health_style = GREEN if health > 0.8 else YELLOW if health > 0.5 else RED
    health_progress = ProgressState(value=health)
    health_bar = progress_bar(health_progress, width - 12, filled_style=health_style, empty_style=DIM)
    health_label = Block.text("health: ", DIM)
    pct = Block.text(f" {int(health * 100):3d}%", health_style)
    lines.append(join_horizontal(health_label, health_bar, pct))

    # Last report
    if minute_state["last_report"] > 0:
        ts_str = datetime.fromtimestamp(minute_state["last_report"]).strftime("%H:%M:%S")
        lines.append(Block.empty(width, 1))
        lines.append(Block.text(f"last: {ts_str}", DIM, width=width))

    return join_vertical(*lines)


def render_fact_stream(facts: list[FactEntry], width: int, height: int) -> Block:
    """Render scrolling fact stream."""
    lines = []

    # Header
    lines.append(Block.text("FACT STREAM", WHITE_BOLD, width=width))
    lines.append(Block.text("─" * width, DIM, width=width))

    # Facts (newest first)
    display_facts = list(reversed(facts[-height:]))
    for entry in display_facts:
        ts_str = datetime.fromtimestamp(entry.ts).strftime("%H:%M:%S.") + f"{int((entry.ts % 1) * 1000):03d}"
        line = f"{ts_str}  {entry.kind:12s} {entry.summary}"
        if len(line) > width:
            line = line[:width-1] + "…"
        lines.append(Block.text(line, entry.style, width=width))

    # Pad to height
    while len(lines) < height:
        lines.append(Block.empty(width, 1))

    return join_vertical(*lines)


def render_feedback_panel(rate_history: list[float], current_rate: float, feedback_active: bool, width: int) -> Block:
    """Render feedback loop status with sparkline."""
    lines = []

    # Status line
    status = "ACTIVE" if feedback_active else "STABLE"
    status_style = YELLOW_BOLD if feedback_active else GREEN
    status_text = f"Rate adjustment: {status}"
    target_text = f"target: {PULSE_INTERVAL:.2f}s"
    current_text = f"current: {current_rate:.3f}s"
    line1 = f"{status_text}  |  {target_text}  |  {current_text}"
    lines.append(Block.text(line1[:width], status_style if feedback_active else DIM, width=width))

    # Sparkline
    spark_width = width - 12
    spark = sparkline(rate_history, spark_width, CYAN)
    spark_label = Block.text("rate: ", DIM)
    lines.append(join_horizontal(spark_label, spark))

    return join_vertical(*lines)


def render_help_line(paused: bool, width: int) -> Block:
    """Render help/control line."""
    pause_key = "[p]lay" if paused else "[p]ause"
    help_text = f"[q]uit  {pause_key}  [r]eset  [+/-] speed"
    centered = help_text.center(width)
    return Block.text(centered, DIM, width=width)


# -- Main Application --------------------------------------------------------

class CadenceMonitorApp(Surface):
    """Full TUI demonstrating cadence hierarchy with animated visualization."""

    def __init__(self):
        super().__init__(fps_cap=30, on_emit=self._handle_emit)
        self._w = 80
        self._h = 40

        # Peer identity
        self.peer = Peer("cadence-monitor")

        # Vertices for each timescale
        self.pulse_vertex = Vertex("pulse")
        self.pulse_vertex.register("pulse", PULSE_INITIAL.copy(), pulse_fold)

        self.breath_vertex = Vertex("breath")
        self.breath_vertex.register("breath", BREATH_INITIAL.copy(), breath_fold)

        self.minute_vertex = Vertex("minute")
        self.minute_vertex.register("minute", MINUTE_INITIAL.copy(), minute_fold)

        # Timer state
        self._last_pulse = time.time()
        self._pulse_interval = PULSE_INTERVAL
        self._pulse_count = 0
        self._breath_count = 0

        # Fact stream
        self._facts: deque[FactEntry] = deque(maxlen=MAX_FACT_STREAM)

        # Rate history for sparkline
        self._rate_history: deque[float] = deque(maxlen=RATE_HISTORY_SIZE)

        # UI state
        self._paused = False
        self._feedback_active = False

        # Flash effects (tick -> frame_count remaining)
        self._pulse_flash = 0
        self._breath_flash = 0
        self._minute_flash = 0

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def update(self) -> None:
        """Called every frame — drives timers and animations."""
        # Decay flash effects
        if self._pulse_flash > 0:
            self._pulse_flash -= 1
            self.mark_dirty()
        if self._breath_flash > 0:
            self._breath_flash -= 1
            self.mark_dirty()
        if self._minute_flash > 0:
            self._minute_flash -= 1
            self.mark_dirty()

        if self._paused:
            return

        now = time.time()
        if now - self._last_pulse >= self._pulse_interval:
            self._emit_pulse(now)
            self._last_pulse = now
            self.mark_dirty()

    def _emit_pulse(self, ts: float) -> None:
        """Emit a pulse fact, potentially triggering breath/minute boundaries."""
        self._pulse_count += 1

        # Create pulse fact
        pulse_fact = Fact.of("pulse", self.peer.name, ts=ts, count=self._pulse_count)
        self.pulse_vertex.receive(pulse_fact)

        # Record in stream
        self._add_fact("pulse", f"count={self._pulse_count}", CYAN)

        # Track rate
        pulse_state = self.pulse_vertex.state("pulse")
        if pulse_state["avg_rate"] > 0:
            self._rate_history.append(pulse_state["avg_rate"])

        # Trigger flash
        self._pulse_flash = 3

        # Check for breath boundary
        if self._pulse_count % PULSES_PER_BREATH == 0:
            self._emit_breath(ts, pulse_state)

    def _emit_breath(self, ts: float, pulse_state: dict) -> None:
        """Emit a breath fact when pulse boundary fires."""
        self._breath_count += 1

        # Forward pulse summary to breath
        breath_fact = Fact.of(
            "breath",
            self.peer.name,
            ts=ts,
            pulse_count=PULSES_PER_BREATH,
            avg_rate=pulse_state["avg_rate"],
            jitter=pulse_state["jitter"],
        )
        self.breath_vertex.receive(breath_fact)

        # Update breath state with count
        breath_state = self.breath_vertex.state("breath")
        # Manually update breath count since we're not using boundaries
        self.breath_vertex._engines["breath"].projection._state = {
            **breath_state,
            "breath_count": self._breath_count,
        }

        # Record in stream
        self._add_fact("breath.tick", f"breath={self._breath_count} avg={pulse_state['avg_rate']:.3f}s", GREEN_BOLD)

        # Trigger flash
        self._breath_flash = 5

        # Check for minute boundary
        if self._breath_count % BREATHS_PER_MINUTE == 0:
            self._emit_minute(ts)

    def _emit_minute(self, ts: float) -> None:
        """Emit a minute fact when breath boundary fires."""
        breath_state = self.breath_vertex.state("breath")

        # Forward breath summary to minute
        minute_fact = Fact.of(
            "minute",
            self.peer.name,
            ts=ts,
            pulse_count=breath_state["pulse_count"],
            avg_rate=breath_state["avg_rate"],
            drift=breath_state["drift"],
        )
        self.minute_vertex.receive(minute_fact)

        minute_state = self.minute_vertex.state("minute")

        # Record in stream
        health_pct = int(minute_state["health"] * 100)
        self._add_fact("minute.report", f"health={health_pct}% pulses={minute_state['total_pulses']}", MAGENTA_BOLD)

        # Trigger flash
        self._minute_flash = 8

        # Feedback: adjust rate based on variance
        self._apply_feedback(minute_state)

    def _apply_feedback(self, minute_state: dict) -> None:
        """Apply feedback: adjust pulse rate based on variance."""
        variance = minute_state["variance"]
        avg_rate = minute_state["avg_rate"]

        # If rate is drifting, nudge it back toward target
        rate_error = avg_rate - PULSE_INTERVAL

        if abs(rate_error) > 0.01 or variance > 0.001:
            # Apply correction (dampened)
            correction = -rate_error * 0.1
            new_rate = max(0.5, min(2.0, self._pulse_interval + correction))

            if abs(new_rate - self._pulse_interval) > 0.001:
                self._pulse_interval = new_rate
                self._feedback_active = True
                self._add_fact("rate.adjust", f"new_rate={new_rate:.3f}s", YELLOW_BOLD)
            else:
                self._feedback_active = False
        else:
            self._feedback_active = False

    def _add_fact(self, kind: str, summary: str, style: Style) -> None:
        """Add a fact to the display stream."""
        self._facts.append(FactEntry(ts=time.time(), kind=kind, summary=summary, style=style))

    def _handle_emit(self, kind: str, data: dict) -> None:
        """Handle UI emissions."""
        pass  # Not using UI emissions in this demo

    def render(self) -> None:
        if self._buf is None:
            return

        # Get current states
        pulse_state = self.pulse_vertex.state("pulse")
        breath_state = self.breath_vertex.state("breath")
        minute_state = self.minute_vertex.state("minute")

        # Calculate breath progress
        pulses_in_breath = self._pulse_count % PULSES_PER_BREATH
        breath_progress = pulses_in_breath / PULSES_PER_BREATH

        # Layout calculations
        content_width = min(self._w - 4, 76)
        panel_width = (content_width - 4) // 2

        # Build panels
        pulse_panel = render_pulse_panel(pulse_state, breath_progress, content_width - 4)
        pulse_bordered = border(pulse_panel, title="PULSE", style=CYAN if self._pulse_flash > 0 else DIM, title_style=CYAN_BOLD)

        breath_panel = render_breath_panel(breath_state, panel_width - 2)
        breath_bordered = border(breath_panel, title="BREATH", style=GREEN if self._breath_flash > 0 else DIM, title_style=GREEN_BOLD)

        minute_panel = render_minute_panel(minute_state, panel_width - 2)
        minute_bordered = border(minute_panel, title="MINUTE", style=MAGENTA if self._minute_flash > 0 else DIM, title_style=MAGENTA_BOLD)

        # Fact stream (dynamic height)
        stream_height = max(8, self._h - 30)
        fact_stream = render_fact_stream(list(self._facts), content_width - 4, stream_height)
        fact_bordered = border(fact_stream, title="FACTS", style=DIM, title_style=WHITE_BOLD)

        # Feedback panel
        feedback_panel = render_feedback_panel(
            list(self._rate_history),
            self._pulse_interval,
            self._feedback_active,
            content_width - 4,
        )
        feedback_bordered = border(feedback_panel, title="FEEDBACK", style=YELLOW if self._feedback_active else DIM, title_style=YELLOW_BOLD if self._feedback_active else DIM)

        # Help line
        help_line = render_help_line(self._paused, content_width)

        # Compose layout
        mid_row = join_horizontal(breath_bordered, Block.empty(2, 1), minute_bordered)

        # Title
        title_text = "CADENCE MONITOR"
        if self._paused:
            title_text += " [PAUSED]"
        title = Block.text(title_text.center(content_width), WHITE_BOLD, width=content_width)

        content = join_vertical(
            title,
            Block.empty(content_width, 1),
            pulse_bordered,
            Block.empty(content_width, 1),
            mid_row,
            Block.empty(content_width, 1),
            fact_bordered,
            Block.empty(content_width, 1),
            feedback_bordered,
            Block.empty(content_width, 1),
            help_line,
        )

        # Center in screen
        padded = pad(content, left=2, top=1)

        # Paint to buffer
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()
        elif key == "p":
            self._paused = not self._paused
            self.mark_dirty()
        elif key == "r":
            self._reset()
        elif key in ("+", "="):
            self._pulse_interval = max(0.1, self._pulse_interval - 0.1)
            self._add_fact("speed.up", f"interval={self._pulse_interval:.2f}s", YELLOW)
            self.mark_dirty()
        elif key in ("-", "_"):
            self._pulse_interval = min(3.0, self._pulse_interval + 0.1)
            self._add_fact("speed.down", f"interval={self._pulse_interval:.2f}s", YELLOW)
            self.mark_dirty()

    def _reset(self) -> None:
        """Reset all state."""
        self._pulse_count = 0
        self._breath_count = 0
        self._pulse_interval = PULSE_INTERVAL
        self._last_pulse = time.time()
        self._facts.clear()
        self._rate_history.clear()
        self._feedback_active = False

        # Reset vertices
        self.pulse_vertex._engines["pulse"].projection.reset(PULSE_INITIAL.copy())
        self.breath_vertex._engines["breath"].projection.reset(BREATH_INITIAL.copy())
        self.minute_vertex._engines["minute"].projection.reset(MINUTE_INITIAL.copy())

        self._add_fact("reset", "all state cleared", WHITE_BOLD)
        self.mark_dirty()


# -- Main --------------------------------------------------------------------

async def main():
    app = CadenceMonitorApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
