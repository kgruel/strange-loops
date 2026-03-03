#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Frame timing — per-phase render loop profiling with FrameTimer.

FrameTimer instruments each frame's phases (input, render, diff),
capturing wall-clock timing that flows through the lens pipeline.
Complementary to profiler.py: timing shows *when* time is spent
(per frame), profiler shows *where* (call tree).

    uv run demos/patterns/timing.py -q       # avg frame time
    uv run demos/patterns/timing.py          # phase breakdown
    uv run demos/patterns/timing.py -v       # sparklines + flame graph
    uv run demos/patterns/timing.py -vv      # frame-by-frame detail
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass

from painted import (
    Block,
    CliContext,
    Style,
    Zoom,
    border,
    join_vertical,
    pad,
    run_cli,
    truncate,
    ROUNDED,
)
from painted._timer import FrameTimer
from painted.palette import current_palette
from painted.tui import Buffer, Layer, Pop, Push, Quit, Stay, Surface, render_layers
from painted.views import chart_lens, flame_lens
from painted.writer import Writer


# --- Data model ---


@dataclass(frozen=True)
class TimingData:
    """Per-frame timing results from an instrumented render loop."""

    frame_count: int
    avg_total_ms: float
    max_total_ms: float
    phase_names: tuple[str, ...]
    phase_avgs: dict[str, float]
    frame_totals: tuple[float, ...]
    frame_phases: tuple[dict[str, float], ...]
    frame_labels: tuple[str, ...]
    frame_writes: tuple[int, ...]


# --- Sample data (deterministic, for golden tests) ---

SAMPLE_TIMING = TimingData(
    frame_count=9,
    avg_total_ms=0.15,
    max_total_ms=0.42,
    phase_names=("input", "update", "render", "diff"),
    phase_avgs={"input": 0.019, "update": 0.001, "render": 0.106, "diff": 0.024},
    frame_totals=(0.42, 0.12, 0.11, 0.10, 0.10, 0.11, 0.18, 0.18, 0.03),
    frame_phases=(
        {"update": 0.01, "render": 0.35, "diff": 0.06},
        {"input": 0.02, "update": 0.00, "render": 0.08, "diff": 0.02},
        {"input": 0.02, "update": 0.00, "render": 0.07, "diff": 0.02},
        {"input": 0.02, "update": 0.00, "render": 0.06, "diff": 0.02},
        {"input": 0.02, "update": 0.00, "render": 0.06, "diff": 0.02},
        {"input": 0.02, "update": 0.00, "render": 0.07, "diff": 0.02},
        {"input": 0.03, "update": 0.00, "render": 0.12, "diff": 0.03},
        {"input": 0.03, "update": 0.00, "render": 0.12, "diff": 0.03},
        {"input": 0.01, "update": 0.00, "render": 0.02, "diff": 0.00},
    ),
    frame_labels=(
        "initial",
        "after 'j'",
        "after 'j'",
        "after 'j'",
        "after 'k'",
        "after 'k'",
        "after 'enter'",
        "after 'escape'",
        "after 'q'",
    ),
    frame_writes=(77, 27, 22, 19, 19, 22, 43, 43, 0),
)


# --- Mini app under test ---
# (Same workload as profiler.py — list navigation with detail layer)

_ITEMS = (
    "api-gateway",
    "auth-service",
    "worker",
    "scheduler",
    "metrics",
    "logger",
    "cache",
    "queue",
    "storage",
    "monitor",
)

_SCENARIO_INPUTS = ["j", "j", "j", "k", "k", "enter", "escape", "q"]


def _get_layers(state: dict) -> tuple[Layer, ...]:
    return state["layers"]


def _set_layers(state: dict, layers: tuple[Layer, ...]) -> dict:
    return {**state, "layers": layers}


def _base_layer() -> Layer:
    def handle(key: str, ls: int, app_state: dict):
        if key == "j":
            return min(ls + 1, len(_ITEMS) - 1), app_state, Stay()
        if key == "k":
            return max(ls - 1, 0), app_state, Stay()
        if key == "enter":
            return ls, app_state, Push(layer=_detail_layer(_ITEMS[ls]))
        if key == "q":
            return ls, app_state, Quit()
        return ls, app_state, Stay()

    def render(ls: int, app_state: dict, view):
        for i, item in enumerate(_ITEMS):
            marker = ">" if i == ls else " "
            view.put_text(0, i, f"{marker} {item}", Style(bold=(i == ls)))

    return Layer(name="list", state=0, handle=handle, render=render)


def _detail_layer(name: str) -> Layer:
    def handle(key: str, ls: str, app_state: dict):
        if key in ("escape", "q"):
            return ls, app_state, Pop(result=None)
        return ls, app_state, Stay()

    def render(ls: str, app_state: dict, view):
        view.put_text(0, 0, f"Detail: {ls}", Style(bold=True))
        view.put_text(0, 1, "Press escape to go back", Style(dim=True))

    return Layer(name="detail", state=name, handle=handle, render=render)


class _TimingApp(Surface):
    def __init__(self):
        super().__init__()
        self.state: dict = {"layers": (_base_layer(),)}

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        render_layers(self.state, self._buf, _get_layers)

    def on_key(self, key: str) -> None:
        new_state, should_quit, _ = self.handle_key(
            key,
            self.state,
            _get_layers,
            _set_layers,
        )
        self.state = new_state
        if should_quit:
            self.quit()


# --- Instrumented run ---


def _fetch() -> TimingData:
    """Run the scenario with per-phase FrameTimer instrumentation."""
    app = _TimingApp()
    timer = FrameTimer(profile=True)

    # Setup (mirrors TestSurface, but we control the loop)
    app._writer = Writer(io.StringIO())
    buf = Buffer(80, 24)
    prev = Buffer(80, 24)
    app._buf = buf
    app._prev = prev
    app.layout(80, 24)
    app._running = True
    app._dirty = True

    frame_labels: list[str] = []

    def _do_frame(input_key: str | None = None) -> None:
        nonlocal prev
        timer.begin_frame()

        if input_key is not None:
            with timer.phase("input"):
                app.on_key(input_key)
                app.emit("ui.key", key=input_key)
            app._dirty = True

        with timer.phase("update"):
            app.update()
        with timer.phase("render"):
            app.render()
        with timer.phase("diff"):
            writes = buf.diff(prev)

        timer.set_meta("writes", len(writes))
        timer.end_frame()

        prev = buf.clone()
        app._prev = prev

    # Initial frame
    _do_frame()
    frame_labels.append("initial")

    # Input frames
    for key in _SCENARIO_INPUTS:
        if not app._running:
            break
        _do_frame(key)
        frame_labels.append(f"after '{key}'")

    # Extract data from timer log
    log = timer._log
    phase_names = timer.phase_names()

    return TimingData(
        frame_count=len(log),
        avg_total_ms=round(timer.avg_total(), 4),
        max_total_ms=round(max(r.total for r in log), 4) if log else 0.0,
        phase_names=tuple(phase_names),
        phase_avgs={name: round(timer.avg(name), 4) for name in phase_names},
        frame_totals=tuple(round(r.total, 4) for r in log),
        frame_phases=tuple({k: round(v, 4) for k, v in r.phases.items()} for r in log),
        frame_labels=tuple(frame_labels),
        frame_writes=tuple(int(r.meta.get("writes", 0)) for r in log),
    )


# --- Zoom 0: one-line summary ---


def render_minimal(data: TimingData, width: int) -> Block:
    """Single-line timing summary."""
    result = Block.text(
        f"{data.frame_count} frames, avg {data.avg_total_ms:.2f}ms/frame, "
        f"max {data.max_total_ms:.2f}ms",
        Style(),
    )
    return truncate(result, width)


# --- Zoom 1: phase breakdown ---


def render_summary(data: TimingData, width: int) -> Block:
    """Phase averages + frame total sparkline."""
    p = current_palette()
    rows: list[Block] = [
        Block.text("Frame Timing", Style(bold=True)),
        Block.text(
            f"  {data.frame_count} frames, avg {data.avg_total_ms:.2f}ms, "
            f"max {data.max_total_ms:.2f}ms",
            Style(dim=True),
        ),
        Block.text("", Style()),
        Block.text("Phase averages (ms):", Style(dim=True)),
    ]

    for name in data.phase_names:
        avg = data.phase_avgs.get(name, 0.0)
        style = p.accent if avg > data.avg_total_ms * 0.3 else Style()
        rows.append(Block.text(f"  {name:>8s}: {avg:.3f}", style))

    rows.append(Block.text("", Style()))
    rows.append(Block.text("Frame totals:", Style(dim=True)))
    sparkline = chart_lens(list(data.frame_totals), 1, min(60, width - 2))
    rows.append(sparkline)

    return truncate(join_vertical(*rows), width)


# --- Zoom 2: charts + flame ---


def render_detailed(data: TimingData, width: int) -> Block:
    """Per-frame bar chart + phase flame graph."""
    sections: list[Block] = []
    inner_width = min(width - 4, 70)

    # Per-frame totals as labeled bar chart (indexed labels to avoid dict collapse)
    frame_data = {
        f"F{i} {lbl}": t for i, (lbl, t) in enumerate(zip(data.frame_labels, data.frame_totals))
    }
    chart_block = chart_lens(frame_data, 3, inner_width)
    sections.append(border(chart_block, title="Frame Totals (ms)", chars=ROUNDED))
    sections.append(Block.text("", Style()))

    # Write counts per frame
    write_data = {
        f"F{i} {lbl}": w for i, (lbl, w) in enumerate(zip(data.frame_labels, data.frame_writes))
    }
    write_chart = chart_lens(write_data, 3, inner_width)
    sections.append(border(write_chart, title="Cell Writes per Frame", chars=ROUNDED))
    sections.append(Block.text("", Style()))

    # Phase proportions as horizontal flame
    phase_data = {
        name: data.phase_avgs[name] for name in data.phase_names if data.phase_avgs[name] > 0
    }
    if phase_data:
        flame_h = flame_lens(phase_data, 1, inner_width)
        sections.append(border(flame_h, title="Phase Proportions (avg)", chars=ROUNDED))
        sections.append(Block.text("", Style()))

    # Phase cost as vertical flame
    if phase_data:
        flame_v = flame_lens(phase_data, 1, inner_width, height=10)
        sections.append(border(flame_v, title="Phase Cost", chars=ROUNDED))

    return join_vertical(*sections)


# --- Zoom 3: frame-by-frame detail ---


def render_full(data: TimingData, width: int) -> Block:
    """Per-frame detail cards with phase breakdown."""
    p = current_palette()
    sections: list[Block] = []
    inner_width = min(width - 4, 70)

    for i in range(data.frame_count):
        total = data.frame_totals[i]
        label = data.frame_labels[i]
        phases = data.frame_phases[i]
        writes = data.frame_writes[i]

        is_hot = total > data.avg_total_ms * 2
        style = p.warning if is_hot else Style()
        hot_marker = " HOT" if is_hot else ""

        rows: list[Block] = [
            Block.text(f"{total:.3f}ms{hot_marker}  ({writes} writes)", style),
        ]
        for name in data.phase_names:
            ms = phases.get(name, 0.0)
            rows.append(Block.text(f"  {name:>8s}: {ms:.3f}ms", Style(dim=True)))

        inner = join_vertical(*rows)
        sections.append(
            border(
                pad(inner, right=max(0, min(50, width - 4) - inner.width)),
                title=f"Frame {i}: {label}",
                chars=ROUNDED,
            )
        )

    sections.append(Block.text("", Style()))

    # Phase flame (horizontal)
    phase_data = {
        name: data.phase_avgs[name] for name in data.phase_names if data.phase_avgs[name] > 0
    }
    if phase_data:
        flame_h = flame_lens(phase_data, 1, inner_width)
        sections.append(border(flame_h, title="Phase Proportions", chars=ROUNDED))

    return join_vertical(*sections)


# --- run_cli integration ---


def _render(ctx: CliContext, data: TimingData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return render_minimal(data, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return render_summary(data, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return render_full(data, ctx.width)
    return render_detailed(data, ctx.width)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="timing.py",
    )


if __name__ == "__main__":
    sys.exit(main())
