#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Replay testing — emission capture and observation traces.

TestSurface replays scripted inputs and captures both frames and emissions.
This demo builds a small deploy app, tests it with two scenarios, and
renders the results at every zoom level.

    uv run demos/patterns/testing.py -q        # pass/fail summary
    uv run demos/patterns/testing.py           # emission traces
    uv run demos/patterns/testing.py -v        # traces + frame snapshots
    uv run demos/patterns/testing.py -vv       # bordered sections + diff counts
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
    truncate,
    ROUNDED,
)
from painted.icon_set import current_icons
from painted.palette import current_palette
from painted.tui import Layer, Pop, Push, Quit, Stay, Surface, TestSurface, render_layers


# --- App under test: DeployApp ---

SERVICES = ("api-gateway", "auth-service", "worker", "scheduler", "metrics")


def _get_layers(state: dict) -> tuple[Layer, ...]:
    return state["layers"]


def _set_layers(state: dict, layers: tuple[Layer, ...]) -> dict:
    return {**state, "layers": layers}


def _base_layer() -> Layer:
    """Base layer: j/k navigate, enter confirms, q quits."""

    def handle(key: str, ls: int, app_state: dict):
        if key == "j":
            return min(ls + 1, len(SERVICES) - 1), app_state, Stay()
        if key == "k":
            return max(ls - 1, 0), app_state, Stay()
        if key == "enter":
            name = SERVICES[ls]
            return ls, app_state, Push(layer=_confirm_layer(name))
        if key == "q":
            return ls, app_state, Quit()
        return ls, app_state, Stay()

    def render(ls: int, app_state: dict, view):
        for i, svc in enumerate(SERVICES):
            marker = ">" if i == ls else " "
            view.put_text(0, i, f"{marker} {svc}", Style(bold=(i == ls)))

    return Layer(name="base", state=0, handle=handle, render=render)


def _confirm_layer(service_name: str) -> Layer:
    """Confirm layer: y confirms (Pop with result), n cancels (Pop with None)."""

    def handle(key: str, ls: str, app_state: dict):
        if key == "y":
            return ls, app_state, Pop(result=ls)
        if key == "n":
            return ls, app_state, Pop(result=None)
        return ls, app_state, Stay()

    def render(ls: str, app_state: dict, view):
        view.put_text(0, 0, f"Deploy {ls}? (y/n)", Style(bold=True))

    return Layer(name="confirm", state=service_name, handle=handle, render=render)


class DeployApp(Surface):
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

        # Domain emissions after handle_key
        layers = _get_layers(new_state)
        base_layer = layers[0]
        selected = base_layer.state

        if key in ("j", "k") and len(layers) == 1:
            self.emit("deploy.select", service=SERVICES[selected], index=selected)

        if pop_result is not None:
            self.emit("deploy.confirmed", service=pop_result)

        if should_quit:
            self.quit()


# --- Test scenarios ---


@dataclass(frozen=True)
class Scenario:
    name: str
    keys: list[str]
    expected_emissions: list[str]     # emission kinds that MUST appear
    unexpected_emissions: list[str]   # emission kinds that must NOT appear


SCENARIOS = (
    Scenario(
        name="confirm deploy",
        keys=["j", "enter", "y", "q"],
        expected_emissions=["deploy.select", "deploy.confirmed"],
        unexpected_emissions=[],
    ),
    Scenario(
        name="cancel deploy",
        keys=["j", "enter", "n", "q"],
        expected_emissions=["deploy.select"],
        unexpected_emissions=["deploy.confirmed"],
    ),
)


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    emissions: list[tuple[str, dict]]
    frames: list[object]  # CapturedFrame
    passed: bool
    checks: list[tuple[str, bool]]  # (description, passed)


def run_scenario(scenario: Scenario) -> ScenarioResult:
    app = DeployApp()
    harness = TestSurface(app, width=40, height=8, input_queue=scenario.keys)
    frames = harness.run_to_completion()
    emissions = harness.emissions

    emission_kinds = [e[0] for e in emissions]
    checks: list[tuple[str, bool]] = []

    for kind in scenario.expected_emissions:
        ok = kind in emission_kinds
        checks.append((f"{kind} emitted", ok))

    for kind in scenario.unexpected_emissions:
        ok = kind not in emission_kinds
        checks.append((f"{kind} not emitted", ok))

    passed = all(ok for _, ok in checks)
    return ScenarioResult(
        scenario=scenario,
        emissions=emissions,
        frames=frames,
        passed=passed,
        checks=checks,
    )


# --- Rendering ---


def _emission_block(kind: str, data: dict) -> Block:
    """Render one emission as a styled line."""
    p = current_palette()
    style = p.accent if kind.startswith("deploy.") else p.muted
    data_str = " ".join(f"{k}={v}" for k, v in data.items())
    return join_horizontal(
        Block.text(f"  {kind:<20s}", style),
        Block.text(f" {data_str}", Style(dim=True)),
    )


def _check_block(description: str, passed: bool) -> Block:
    p = current_palette()
    icons = current_icons()
    icon = icons.check if passed else icons.cross
    style = p.success if passed else p.error
    return Block.text(f"  {icon} {description}", style)


def _render_minimal(results: list[ScenarioResult], width: int) -> Block:
    p = current_palette()
    icons = current_icons()
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    all_passed = passed == total
    icon = icons.check if all_passed else icons.cross
    style = p.success if all_passed else p.error
    return truncate(Block.text(f"{icon} {passed}/{total} scenarios passed", style), width)


def _render_summary(results: list[ScenarioResult], width: int) -> Block:
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []

    for result in results:
        icon = icons.check if result.passed else icons.cross
        style = p.success if result.passed else p.error
        header = Block.text(f"{icon} {result.scenario.name}", style)

        emission_lines = [_emission_block(k, d) for k, d in result.emissions]
        trace = join_vertical(*emission_lines) if emission_lines else Block.text("  (no emissions)", Style(dim=True))

        check_lines = [_check_block(desc, ok) for desc, ok in result.checks]
        checks = join_vertical(*check_lines)

        sections.append(join_vertical(
            header,
            Block.text("  emissions:", Style(dim=True)),
            trace,
            checks,
            Block.text("", Style()),
        ))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    footer = _render_minimal(results, width)

    return truncate(join_vertical(*sections, footer), width)


def _render_detailed(results: list[ScenarioResult], width: int) -> Block:
    """Summary + frame text snapshots at key moments."""
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []

    for result in results:
        icon = icons.check if result.passed else icons.cross
        style = p.success if result.passed else p.error
        header = Block.text(f"{icon} {result.scenario.name}", style)
        keys_str = " -> ".join(result.scenario.keys)
        keys_line = Block.text(f"  keys: {keys_str}", Style(dim=True))

        emission_lines = [_emission_block(k, d) for k, d in result.emissions]
        trace = join_vertical(*emission_lines) if emission_lines else Block.text("  (no emissions)", Style(dim=True))

        check_lines = [_check_block(desc, ok) for desc, ok in result.checks]
        checks = join_vertical(*check_lines)

        # Frame snapshots: initial, after each key
        frame_blocks: list[Block] = []
        for i, frame in enumerate(result.frames):
            label = "initial" if i == 0 else f"after '{result.scenario.keys[i - 1]}'"
            frame_header = Block.text(f"  [{label}]", Style(dim=True))
            text = frame.text.rstrip()
            frame_text = Block.text(f"    {text.split(chr(10))[0]}", Style(dim=True))
            frame_blocks.append(join_vertical(frame_header, frame_text))

        frames_section = join_vertical(*frame_blocks) if frame_blocks else Block.empty(0, 0)

        sections.append(join_vertical(
            header,
            keys_line,
            Block.text("  emissions:", Style(dim=True)),
            trace,
            checks,
            Block.text("  frames:", Style(dim=True)),
            frames_section,
            Block.text("", Style()),
        ))

    footer = _render_minimal(results, width)
    return truncate(join_vertical(*sections, footer), width)


def _render_full(results: list[ScenarioResult], width: int) -> Block:
    """Bordered sections with diff write counts."""
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []

    for result in results:
        icon = icons.check if result.passed else icons.cross
        style = p.success if result.passed else p.error

        keys_str = " -> ".join(result.scenario.keys)
        keys_line = Block.text(f"keys: {keys_str}", Style(dim=True))

        emission_lines = [_emission_block(k, d) for k, d in result.emissions]
        trace = join_vertical(*emission_lines) if emission_lines else Block.text("(no emissions)", Style(dim=True))

        check_lines = [_check_block(desc, ok) for desc, ok in result.checks]
        checks = join_vertical(*check_lines)

        # Frame details with write counts
        frame_blocks: list[Block] = []
        for i, frame in enumerate(result.frames):
            label = "initial" if i == 0 else f"after '{result.scenario.keys[i - 1]}'"
            write_count = len(frame.writes)
            frame_header = Block.text(f"[{label}] ({write_count} writes)", Style(dim=True))
            first_line = frame.text.split("\n")[0].rstrip()
            frame_text = Block.text(f"  {first_line}", Style(dim=True))
            frame_blocks.append(join_vertical(frame_header, frame_text))

        frames_section = join_vertical(*frame_blocks) if frame_blocks else Block.empty(0, 0)

        inner = join_vertical(
            keys_line,
            Block.text("", Style()),
            Block.text("emissions:", Style(dim=True)),
            trace,
            Block.text("", Style()),
            checks,
            Block.text("", Style()),
            Block.text("frames:", Style(dim=True)),
            frames_section,
        )

        title = f"{icon} {result.scenario.name}"
        sections.append(border(pad(inner, right=max(0, min(60, width - 4) - inner.width)), title=title, chars=ROUNDED))
        sections.append(Block.text("", Style()))

    footer = _render_minimal(results, width)
    return join_vertical(*sections, footer)


# --- Main render dispatch ---


def _render(ctx: CliContext, results: list[ScenarioResult]) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(results, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(results, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return _render_full(results, ctx.width)
    return _render_detailed(results, ctx.width)


def _fetch() -> list[ScenarioResult]:
    return [run_scenario(s) for s in SCENARIOS]


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="testing.py",
    )


if __name__ == "__main__":
    sys.exit(main())
