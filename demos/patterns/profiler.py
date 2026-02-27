#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Self-profiling — painted introspects its own rendering performance.

TestSurface profiles a mini TUI app, then renders the results at every
zoom level through run_cli. Demonstrates lens composition: chart_lens
for frame cost bars, tree_lens for emission timeline, flame_lens for
proportional breakdown.

    uv run demos/patterns/profiler.py -q        # summary stats
    uv run demos/patterns/profiler.py           # emission traces
    uv run demos/patterns/profiler.py -v        # frame chart + flame graph
    uv run demos/patterns/profiler.py -vv       # frame-by-frame detail
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from painted import (
    Block,
    CliContext,
    Style,
    Zoom,
    border,
    join_horizontal,
    join_vertical,
    pad,
    run_cli,
    ROUNDED,
)
from painted.views import chart_lens, flame_lens, tree_lens
from painted.palette import current_palette
from painted.tui import Layer, Pop, Push, Quit, Stay, Surface, TestSurface, render_layers


# --- Data model ---


@dataclass(frozen=True)
class FrameProfile:
    """Performance metrics for a single rendered frame."""
    index: int
    label: str
    write_count: int
    is_hot: bool


@dataclass(frozen=True)
class EmissionSummary:
    """Aggregate count for one emission kind."""
    kind: str
    count: int


@dataclass(frozen=True)
class ProfileData:
    """Complete profiling results from a TestSurface run."""
    scenario_name: str
    dimensions: str
    input_count: int
    frame_count: int
    total_writes: int
    avg_writes: float
    max_writes: int
    hot_frame_count: int
    frames: tuple[FrameProfile, ...]
    emission_summary: tuple[EmissionSummary, ...]
    emissions_raw: tuple[tuple[str, dict], ...]


# --- Mini app under test ---


_ITEMS = (
    "api-gateway", "auth-service", "worker", "scheduler",
    "metrics", "logger", "cache", "queue", "storage", "monitor",
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


class _ProfileApp(Surface):
    def __init__(self):
        super().__init__()
        self.state: dict = {"layers": (_base_layer(),)}

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        render_layers(self.state, self._buf, _get_layers)

    def on_key(self, key: str) -> None:
        new_state, should_quit, pop_result = self.handle_key(
            key, self.state, _get_layers, _set_layers,
        )
        self.state = new_state
        layers = _get_layers(new_state)
        base = layers[0]
        selected = base.state

        if key in ("j", "k") and len(layers) == 1:
            self.emit("list.select", service=_ITEMS[selected], index=selected)
        if key == "enter" and len(layers) > 1:
            self.emit("list.open", service=_ITEMS[selected])
        if pop_result is None and key == "escape":
            self.emit("list.close", service=_ITEMS[selected])
        if should_quit:
            self.quit()


# --- Profile extraction ---


def _extract_profile(name: str, harness: TestSurface, frames: list) -> ProfileData:
    """Pure function: extract ProfileData from a completed TestSurface run."""
    write_counts = [len(f.writes) for f in frames]
    avg = sum(write_counts) / len(write_counts) if write_counts else 0.0
    threshold = avg * 2

    frame_profiles = tuple(
        FrameProfile(
            index=i,
            label="initial" if i == 0 else f"after '{_SCENARIO_INPUTS[i - 1]}'",
            write_count=wc,
            is_hot=wc > threshold,
        )
        for i, wc in enumerate(write_counts)
    )

    kind_counts: dict[str, int] = {}
    for kind, _ in harness.emissions:
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    emission_summary = tuple(
        EmissionSummary(kind=k, count=c)
        for k, c in sorted(kind_counts.items(), key=lambda x: -x[1])
    )

    return ProfileData(
        scenario_name=name,
        dimensions=f"{harness.width}x{harness.height}",
        input_count=len(_SCENARIO_INPUTS),
        frame_count=len(frames),
        total_writes=sum(write_counts),
        avg_writes=round(avg, 1),
        max_writes=max(write_counts) if write_counts else 0,
        hot_frame_count=sum(1 for f in frame_profiles if f.is_hot),
        frames=frame_profiles,
        emission_summary=emission_summary,
        emissions_raw=tuple((k, d) for k, d in harness.emissions),
    )


def _fetch() -> ProfileData:
    """Run the scenario and extract profiling data."""
    app = _ProfileApp()
    harness = TestSurface(app, width=80, height=24, input_queue=_SCENARIO_INPUTS)
    frames = harness.run_to_completion()
    return _extract_profile("list_nav", harness, frames)


# --- Zoom 0: one-line summary ---


def render_minimal(data: ProfileData) -> Block:
    """Single-line profiling summary."""
    return Block.text(
        f"{data.frame_count} frames, {data.total_writes} writes, "
        f"avg {data.avg_writes:.0f}/frame",
        Style(),
    )


# --- Zoom 1: emission traces ---


def render_summary(data: ProfileData) -> Block:
    """Scenario overview with emission counts."""
    p = current_palette()
    rows: list[Block] = [
        Block.text(f"Scenario: {data.scenario_name}", Style(bold=True)),
        Block.text(f"  {data.input_count} inputs, {data.dimensions}", Style(dim=True)),
        Block.text("", Style()),
        Block.text(f"Frames:    {data.frame_count}", Style()),
        Block.text(
            f"Writes:    {data.total_writes} total "
            f"(avg {data.avg_writes:.0f}, max {data.max_writes})",
            Style(),
        ),
    ]

    if data.hot_frame_count:
        rows.append(Block.text(
            f"Hot frames: {data.hot_frame_count} (>2x avg)", p.warning,
        ))

    rows.append(Block.text("", Style()))
    rows.append(Block.text("Emissions:", Style(dim=True)))
    for es in data.emission_summary:
        style = p.accent if not es.kind.startswith("ui.") else Style(dim=True)
        rows.append(Block.text(f"  {es.count:>3}x  {es.kind}", style))

    return join_vertical(*rows)


# --- Zoom 2: frame chart + flame graph ---


def render_detailed(data: ProfileData, width: int) -> Block:
    """Per-frame write chart and emission flame graph."""
    p = current_palette()
    sections: list[Block] = []

    # Frame write counts as bar chart
    frame_data = {f.label: f.write_count for f in data.frames}
    chart_block = chart_lens(frame_data, 3, min(width - 4, 70))
    sections.append(border(chart_block, title="Writes per Frame", chars=ROUNDED))
    sections.append(Block.text("", Style()))

    # Hot frame callouts
    hot_frames = [f for f in data.frames if f.is_hot]
    if hot_frames:
        hot_rows = [Block.text("Hot frames (>2x average):", p.warning)]
        for f in hot_frames:
            hot_rows.append(Block.text(
                f"  Frame {f.index} ({f.label}): {f.write_count} writes", p.warning,
            ))
        sections.append(join_vertical(*hot_rows))
        sections.append(Block.text("", Style()))

    # Emission proportions as flame graph
    emission_data = {es.kind: es.count for es in data.emission_summary}
    if emission_data:
        flame_block = flame_lens(emission_data, 1, min(width - 4, 70))
        sections.append(border(flame_block, title="Emission Proportions", chars=ROUNDED))

    return join_vertical(*sections)


# --- Zoom 3: frame-by-frame breakdown ---


def render_full(data: ProfileData, width: int) -> Block:
    """Frame-by-frame detail with full emission tree."""
    p = current_palette()
    sections: list[Block] = []

    # Per-frame detail
    for frame in data.frames:
        style = p.warning if frame.is_hot else Style()
        hot_marker = " HOT" if frame.is_hot else ""
        header = Block.text(
            f"Frame {frame.index}: {frame.write_count} writes{hot_marker}",
            style,
        )
        label_line = Block.text(f"  {frame.label}", Style(dim=True))
        inner = join_vertical(header, label_line)
        sections.append(border(
            pad(inner, right=max(0, min(50, width - 4) - inner.width)),
            title=f"Frame {frame.index}",
            chars=ROUNDED,
        ))

    sections.append(Block.text("", Style()))

    # Emission frequency chart
    emission_data = {es.kind: es.count for es in data.emission_summary}
    if emission_data:
        chart_block = chart_lens(emission_data, 3, min(width - 4, 70))
        sections.append(border(chart_block, title="Emission Frequency", chars=ROUNDED))
        sections.append(Block.text("", Style()))

    # Full emission tree
    emission_tree: dict[str, dict[str, int]] = {}
    for kind, data_dict in data.emissions_raw:
        category = kind.split(".")[0] if "." in kind else kind
        if category not in emission_tree:
            emission_tree[category] = {}
        detail = " ".join(f"{k}={v}" for k, v in data_dict.items())
        entry = f"{kind}: {detail}" if detail else kind
        count = emission_tree[category].get(entry, 0)
        emission_tree[category][entry] = count + 1

    if emission_tree:
        tree_block = tree_lens(emission_tree, 2, min(width - 4, 70))
        sections.append(border(tree_block, title="Emission Timeline", chars=ROUNDED))

    return join_vertical(*sections)


# --- run_cli integration ---


def _render(ctx: CliContext, data: ProfileData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:
        return render_summary(data)
    if ctx.zoom == Zoom.FULL:
        return render_full(data, ctx.width)
    return render_detailed(data, ctx.width)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="profiler.py",
    )


if __name__ == "__main__":
    sys.exit(main())
