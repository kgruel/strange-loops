"""Fidelity-aware Lens experiment.

Demonstrates zoom-to-fidelity mapping:
- Generate a build pipeline with nested phases
- Each phase is a bounded loop producing a Tick
- Main build loop collects phase ticks into build tick
- FidelityLens renders at different zoom levels

The key insight: Lens zoom levels map to fidelity depth.
    zoom=0  →  Tick summary only (name + status)
    zoom=1  →  Tick payload (all fields)
    zoom=2  →  Tick + contributing facts from Store.between()
    zoom=3+ →  Recursive: nested ticks expand with reduced zoom

Run:
    uv run python experiments/fidelity_lens.py
    uv run python experiments/fidelity_lens.py --interactive
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from atoms import Fact
from vertex import Peer, Tick
from vertex.store import EventStore
from cells import Block, Style, join_vertical, join_horizontal, border


# -- Domain Types -------------------------------------------------------------


@dataclass(frozen=True)
class PhaseResult:
    """Result of a build phase."""

    name: str
    status: str  # "success" | "failed" | "skipped"
    duration_sec: float
    item_count: int  # files, units, tests, etc.


@dataclass(frozen=True)
class BuildResult:
    """Result of a complete build."""

    commit: str
    status: str
    duration_sec: float
    phases: list[PhaseResult]


# -- Simulated Build Data -----------------------------------------------------


def simulate_build(commit: str, start_time: float) -> tuple[list[Fact], list[Tick], Tick]:
    """Simulate a build pipeline, returning facts, phase ticks, and build tick.

    For this experiment, we simulate the nested structure directly rather than
    running actual Vertex loops. This proves the rendering pattern.
    """
    facts: list[Fact] = []
    phase_ticks: list[Tick] = []
    t = start_time

    # Phase 1: Lint
    lint_start = t
    lint_facts = []
    for i, fname in enumerate(["main.py", "utils.py", "config.py", "api.py"]):
        fact = Fact(
            kind="lint.file",
            ts=t,
            payload={"file": f"src/{fname}", "warnings": i % 2, "errors": 0},
            observer="linter",
        )
        lint_facts.append(fact)
        facts.append(fact)
        t += 0.7

    lint_tick = Tick(
        name="lint",
        ts=datetime.fromtimestamp(t, tz=timezone.utc),
        since=datetime.fromtimestamp(lint_start, tz=timezone.utc),
        payload={"status": "success", "files": 4, "warnings": 2, "errors": 0},
        origin="build-pipeline",
    )
    phase_ticks.append(lint_tick)
    t += 0.2

    # Phase 2: Compile
    compile_start = t
    compile_facts = []
    units = ["auth", "core", "api", "utils", "models", "handlers", "middleware"]
    for unit in units:
        fact = Fact(
            kind="compile.unit",
            ts=t,
            payload={"unit": unit, "duration": 3.5 + len(unit) * 0.3},
            observer="compiler",
        )
        compile_facts.append(fact)
        facts.append(fact)
        t += 4.0

    compile_tick = Tick(
        name="compile",
        ts=datetime.fromtimestamp(t, tz=timezone.utc),
        since=datetime.fromtimestamp(compile_start, tz=timezone.utc),
        payload={"status": "success", "units": 7, "duration": 28.0},
        origin="build-pipeline",
    )
    phase_ticks.append(compile_tick)
    t += 0.3

    # Phase 3: Test
    test_start = t
    test_facts = []
    test_names = [
        "test_auth_login",
        "test_auth_logout",
        "test_auth_refresh",
        "test_api_list",
        "test_api_create",
        "test_api_update",
        "test_api_delete",
        "test_core_init",
        "test_core_shutdown",
        "test_utils_parse",
    ]
    for tname in test_names:
        fact = Fact(
            kind="test.case",
            ts=t,
            payload={"name": tname, "status": "pass", "duration": 0.8 + len(tname) * 0.05},
            observer="pytest",
        )
        test_facts.append(fact)
        facts.append(fact)
        t += 1.2

    test_tick = Tick(
        name="test",
        ts=datetime.fromtimestamp(t, tz=timezone.utc),
        since=datetime.fromtimestamp(test_start, tz=timezone.utc),
        payload={"status": "success", "passed": 10, "failed": 0, "skipped": 0},
        origin="build-pipeline",
    )
    phase_ticks.append(test_tick)
    t += 0.2

    # Phase 4: Package
    package_start = t
    fact = Fact(
        kind="package.artifact",
        ts=t,
        payload={"artifact": "app-1.0.0.tar.gz", "size_mb": 12.4},
        observer="packager",
    )
    facts.append(fact)
    t += 4.0

    package_tick = Tick(
        name="package",
        ts=datetime.fromtimestamp(t, tz=timezone.utc),
        since=datetime.fromtimestamp(package_start, tz=timezone.utc),
        payload={"status": "success", "artifacts": 1, "size_mb": 12.4},
        origin="build-pipeline",
    )
    phase_ticks.append(package_tick)

    # Build tick (encompasses all phases)
    total_duration = t - start_time
    build_tick = Tick(
        name="build",
        ts=datetime.fromtimestamp(t, tz=timezone.utc),
        since=datetime.fromtimestamp(start_time, tz=timezone.utc),
        payload={
            "commit": commit,
            "status": "success",
            "duration": round(total_duration, 1),
            "phases": len(phase_ticks),
        },
        origin="build-pipeline",
    )

    return facts, phase_ticks, build_tick


# -- Fidelity Content ---------------------------------------------------------


@dataclass(frozen=True)
class FidelityContent:
    """Content for fidelity-aware rendering: tick + context for traversal."""

    tick: Tick
    store: EventStore | None = None
    # For simulated nested structure (until tick-as-fact composition exists)
    nested_ticks: tuple[Tick, ...] = ()


# -- Fidelity Lens ------------------------------------------------------------

# Styles
DIM = Style(dim=True)
BOLD = Style(bold=True)
SUCCESS = Style(fg="green")
FAILED = Style(fg="red")
INFO = Style(fg="cyan")
HEADER = Style(fg="cyan", bold=True)


def status_style(status: str) -> Style:
    """Get style for a status value."""
    if status == "success" or status == "pass":
        return SUCCESS
    elif status == "failed" or status == "fail":
        return FAILED
    return DIM


def status_icon(status: str) -> str:
    """Get icon for a status value."""
    if status == "success" or status == "pass":
        return "✓"
    elif status == "failed" or status == "fail":
        return "✗"
    elif status == "skipped":
        return "○"
    return "·"


def fidelity_lens(
    content: FidelityContent,
    zoom: int,
    width: int,
) -> Block:
    """Render a Tick at varying fidelity levels.

    zoom=0: Minimal (name + status icon)
    zoom=1: Summary (payload fields)
    zoom=2: Expanded (contributing facts from period)
    zoom=3+: Recursive (nested ticks expand)
    """
    tick = content.tick
    store = content.store
    nested_ticks = content.nested_ticks

    if zoom <= 0:
        return _render_minimal(tick, width)

    if zoom == 1:
        return _render_summary(tick, width)

    # zoom >= 2: expanded with facts
    return _render_expanded(tick, store, nested_ticks, zoom, width)


def _render_minimal(tick: Tick, width: int) -> Block:
    """Zoom 0: just name + status."""
    payload = tick.payload if isinstance(tick.payload, Mapping) else {}
    status = payload.get("status", "unknown")
    icon = status_icon(status)
    style = status_style(status)

    text = f"{icon} {tick.name}"
    if len(text) > width:
        text = text[: width - 1] + "…"

    return Block.text(text, style, width=width)


def _render_summary(tick: Tick, width: int) -> Block:
    """Zoom 1: name + key payload fields."""
    payload = tick.payload if isinstance(tick.payload, Mapping) else {}
    status = payload.get("status", "unknown")
    icon = status_icon(status)

    rows: list[Block] = []

    # Header line
    header = f"{icon} {tick.name}"
    rows.append(Block.text(header, status_style(status), width=width))

    # Payload fields (excluding status which is in header)
    for key, value in payload.items():
        if key == "status":
            continue
        line = f"  {key}: {value}"
        if len(line) > width:
            line = line[: width - 1] + "…"
        rows.append(Block.text(line, DIM, width=width))

    # Timestamp
    ts_str = tick.ts.strftime("%H:%M:%S")
    rows.append(Block.text(f"  ts: {ts_str}", DIM, width=width))

    return join_vertical(*rows)


def _render_expanded(
    tick: Tick,
    store: EventStore | None,
    nested_ticks: tuple[Tick, ...],
    zoom: int,
    width: int,
) -> Block:
    """Zoom 2+: tick + contributing facts/nested ticks."""
    payload = tick.payload if isinstance(tick.payload, Mapping) else {}
    status = payload.get("status", "unknown")
    icon = status_icon(status)

    rows: list[Block] = []

    # Header
    duration = payload.get("duration", "")
    dur_str = f" {duration}s" if duration else ""
    header = f"{icon} {tick.name}{dur_str}"
    rows.append(Block.text(header, status_style(status), width=width))

    # If we have nested ticks, render them as expandable phases
    if nested_ticks:
        rows.append(Block.text("", DIM, width=width))  # spacer

        for i, nested in enumerate(nested_ticks):
            is_last = i == len(nested_ticks) - 1
            branch = "└─" if is_last else "├─"
            pipe = "  " if is_last else "│ "

            # Nested tick at reduced zoom
            nested_content = FidelityContent(
                tick=nested,
                store=store,
                nested_ticks=(),  # no further nesting in simulation
            )

            if zoom <= 2:
                # At zoom 2, show nested as minimal
                nested_block = _render_minimal(nested, width - 3)
                line = f"{branch} "
                prefix = Block.text(line, DIM, width=3)
                row = join_horizontal(prefix, nested_block)
                rows.append(row)
            else:
                # At zoom 3+, expand nested ticks
                nested_block = _render_summary(nested, width - 3)

                # First line with branch
                first_line = f"{branch} "
                prefix = Block.text(first_line, DIM, width=3)

                # Get first row of nested block
                first_nested = Block([nested_block.row(0)], nested_block.width)
                row = join_horizontal(prefix, first_nested)
                rows.append(row)

                # Remaining rows with pipe continuation
                for r in range(1, nested_block.height):
                    cont_prefix = Block.text(f"{pipe} ", DIM, width=3)
                    rest_row = Block([nested_block.row(r)], nested_block.width)
                    rows.append(join_horizontal(cont_prefix, rest_row))

                # If zoom >= 4, show facts from this nested tick's period
                if zoom >= 4 and store and nested.since:
                    facts = store.between(nested.since, nested.ts)
                    for j, fact in enumerate(facts[:5]):  # limit display
                        fact_is_last = j == len(facts[:5]) - 1 and j == len(facts) - 1
                        fact_branch = "  └─" if fact_is_last else "  ├─"
                        fact_line = _format_fact_line(fact, width - 6)
                        rows.append(Block.text(f"{pipe}{fact_branch} {fact_line}", DIM, width=width))

                    if len(facts) > 5:
                        rows.append(Block.text(f"{pipe}     ... {len(facts) - 5} more", DIM, width=width))

    # If no nested ticks but we have store access, show facts directly
    elif store and tick.since:
        facts = store.between(tick.since, tick.ts)
        if facts:
            rows.append(Block.text("", DIM, width=width))  # spacer
            rows.append(Block.text(f"  {len(facts)} facts in period:", DIM, width=width))

            for i, fact in enumerate(facts[:8]):
                is_last = i == len(facts[:8]) - 1 and i == len(facts) - 1
                branch = "  └─" if is_last else "  ├─"
                fact_line = _format_fact_line(fact, width - 5)
                rows.append(Block.text(f"{branch} {fact_line}", DIM, width=width))

            if len(facts) > 8:
                rows.append(Block.text(f"     ... {len(facts) - 8} more", DIM, width=width))
    else:
        # No facts available, show payload
        rows.append(Block.text("", DIM, width=width))
        for key, value in payload.items():
            if key == "status":
                continue
            line = f"  {key}: {value}"
            if len(line) > width:
                line = line[: width - 1] + "…"
            rows.append(Block.text(line, DIM, width=width))

    return join_vertical(*rows)


def _format_fact_line(fact: Fact, max_width: int) -> str:
    """Format a fact as a single line."""
    # Extract key info from payload
    payload = fact.payload
    if isinstance(payload, Mapping):
        # Try common keys for clean display
        if "file" in payload:
            warnings = payload.get("warnings", 0)
            warn_str = f" ({warnings} warn)" if warnings else ""
            detail = f"{payload['file']}{warn_str}"
        elif "unit" in payload:
            dur = payload.get("duration", "")
            dur_str = f" {dur:.1f}s" if dur else ""
            detail = f"{payload['unit']}{dur_str}"
        elif "name" in payload:
            status = payload.get("status", "")
            icon = "✓" if status == "pass" else "✗" if status == "fail" else ""
            dur = payload.get("duration", "")
            dur_str = f" {dur:.1f}s" if dur else ""
            detail = f"{icon} {payload['name']}{dur_str}" if icon else f"{payload['name']}{dur_str}"
        elif "artifact" in payload:
            size = payload.get("size_mb", "")
            size_str = f" ({size}MB)" if size else ""
            detail = f"{payload['artifact']}{size_str}"
        else:
            detail = str(list(payload.values())[0]) if payload else ""
    else:
        detail = str(payload)

    if len(detail) > max_width:
        detail = detail[: max_width - 1] + "…"

    return detail


# -- Non-Interactive Demo -----------------------------------------------------


def demo_zoom_levels():
    """Print all zoom levels for the same tick."""
    print("=" * 60)
    print("Fidelity Lens: Zoom Level Demo")
    print("=" * 60)
    print()

    # Simulate build
    start_time = time.time()
    facts, phase_ticks, build_tick = simulate_build("abc1234", start_time)

    # Create store with all facts
    store: EventStore = EventStore()
    for fact in facts:
        store.append(fact)

    # Create content with nested structure
    content = FidelityContent(
        tick=build_tick,
        store=store,
        nested_ticks=tuple(phase_ticks),
    )

    width = 50

    for zoom in range(5):
        print(f"─── Zoom Level {zoom} " + "─" * (width - 16))
        print()

        block = fidelity_lens(content, zoom, width)

        # Print block rows
        for r in range(block.height):
            row_chars = "".join(cell.char for cell in block.row(r))
            print(row_chars.rstrip())

        print()

    print("=" * 60)
    print()
    print("What this demonstrates:")
    print("  - zoom=0: Minimal (just status)")
    print("  - zoom=1: Summary (payload fields)")
    print("  - zoom=2: Expanded (nested ticks as minimal)")
    print("  - zoom=3: Deep (nested ticks as summary)")
    print("  - zoom=4: Full (nested ticks + their facts)")
    print()


# -- Interactive Surface ------------------------------------------------------


async def interactive_demo():
    """Interactive fidelity exploration."""
    from cells.tui import Surface

    # Simulate build
    start_time = time.time()
    facts, phase_ticks, build_tick = simulate_build("abc1234", start_time)

    # Create store
    store: EventStore = EventStore()
    for fact in facts:
        store.append(fact)

    content = FidelityContent(
        tick=build_tick,
        store=store,
        nested_ticks=tuple(phase_ticks),
    )

    class FidelityExplorer(Surface):
        """Interactive fidelity exploration of a Tick."""

        def __init__(self, content: FidelityContent):
            super().__init__(fps_cap=30)
            self._w = 60
            self._h = 30
            self.content = content
            self.zoom = 1

        def layout(self, width: int, height: int) -> None:
            self._w = width
            self._h = height

        def render(self) -> None:
            if self._buf is None:
                return

            # Render tick at current zoom
            inner_w = min(self._w - 4, 56)
            block = fidelity_lens(self.content, self.zoom, inner_w)

            # Add zoom indicator
            zoom_text = f"zoom: {self.zoom}"
            zoom_block = Block.text(zoom_text, INFO, width=inner_w)

            # Help line
            help_text = "+/-: zoom  q: quit"
            help_block = Block.text(help_text, DIM, width=inner_w)

            # Combine
            spacer = Block.empty(inner_w, 1)
            combined = join_vertical(block, spacer, zoom_block, help_block)

            # Border
            bordered = border(combined, title="fidelity lens")

            # Paint
            self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
            bordered.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

        def on_key(self, key: str) -> None:
            if key in ("+", "=", "l", "Right"):
                self.zoom = min(self.zoom + 1, 5)
                self.mark_dirty()
            elif key in ("-", "_", "h", "Left"):
                self.zoom = max(self.zoom - 1, 0)
                self.mark_dirty()
            elif key in ("q", "escape"):
                self.quit()

    app = FidelityExplorer(content)
    await app.run()


# -- Main ---------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Fidelity-aware Lens experiment")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run interactive TUI demo",
    )
    args = parser.parse_args()

    if args.interactive:
        asyncio.run(interactive_demo())
    else:
        demo_zoom_levels()


if __name__ == "__main__":
    main()
