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
