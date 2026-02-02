"""hlab status — DSL-driven container status.

Wire: .vertex → Runner → cells render

    uv run python apps/hlab/demos/status.py -q     # one line
    uv run python apps/hlab/demos/status.py        # tree with counts
    uv run python apps/hlab/demos/status.py -f     # tree with containers
    uv run python apps/hlab/demos/status.py -ff    # interactive TUI

Keys (TUI mode):
  +/- : Zoom in/out
  r   : Refresh
  q   : Quit
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from cells import Block, Style, join_vertical, border, print_block, ROUNDED
from cells.tui import Surface

from dsl import parse_vertex_file, parse_loop_file, compile_vertex_recursive, compile_loop, materialize_vertex
from data import Runner
from vertex import Tick


# Resolve paths relative to this file
HERE = Path(__file__).parent.parent
VERTEX_FILE = HERE / "status.vertex"


# ============================================================================
# Rendering helpers
# ============================================================================


def count_healthy(containers: list[dict]) -> tuple[int, int]:
    """Returns (healthy_count, total_count)."""
    total = len(containers)
    healthy = sum(
        1 for c in containers
        if c.get("State") == "running" and c.get("Health") in ("healthy", "")
    )
    return healthy, total


def stack_icon(healthy: int, total: int) -> tuple[str, Style]:
    if healthy == total:
        return "✓", Style(fg="green", bold=True)
    else:
        return "✗", Style(fg="red", bold=True)


def container_style(c: dict) -> tuple[str, Style]:
    state = c.get("State", "")
    health = c.get("Health", "")
    if state == "running" and health == "healthy":
        return "healthy", Style(fg="green")
    elif state == "running":
        return "running", Style(fg="blue")
    else:
        return state, Style(fg="red")


# ============================================================================
# Load from DSL
# ============================================================================


def load_vertex():
    """Parse and materialize the vertex, return (vertex, sources, source_names)."""
    ast = parse_vertex_file(VERTEX_FILE)
    compiled = compile_vertex_recursive(ast)
    vertex = materialize_vertex(compiled)

    sources = []
    source_names = []  # observer names for ordering
    for source_path in ast.sources:
        full_path = VERTEX_FILE.parent / source_path
        loop_ast = parse_loop_file(full_path)
        source = compile_loop(loop_ast)
        sources.append(source)
        source_names.append(source.observer)

    return vertex, sources, source_names


# ============================================================================
# Render from accumulated ticks
# ============================================================================


def render_from_ticks(ticks: list[Tick], fidelity: int, width: int) -> Block:
    """Render accumulated tick payloads at given fidelity."""
    # Each tick is one source's containers (boundary fires per-source)
    # Accumulate all containers, group by Project
    by_stack: dict[str, list[dict]] = {}

    for tick in ticks:
        containers = tick.payload.get("containers", [])
        for c in containers:
            stack = c.get("Project", "unknown")
            if stack not in by_stack:
                by_stack[stack] = []
            by_stack[stack].append(c)

    if not by_stack:
        return Block.text("No containers", Style(dim=True), width=width)

    return render_stacks(by_stack, fidelity, width)


def render_stacks(by_stack: dict[str, list[dict]], fidelity: int, width: int) -> Block:
    """Render grouped stacks."""
    rows: list[Block] = []
    stack_names = sorted(by_stack.keys())

    for i, name in enumerate(stack_names):
        containers = by_stack[name]
        is_last = (i == len(stack_names) - 1)
        stack_prefix = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "

        h, t = count_healthy(containers)
        icon, style = stack_icon(h, t)

        if fidelity == 0:
            rows.append(Block.text(f"{stack_prefix}{icon} {name}: {h}/{t}", style, width=width))
        else:
            rows.append(Block.text(f"{stack_prefix}{icon} {name}: {h}/{t}", style, width=width))
            for j, c in enumerate(containers):
                c_last = (j == len(containers) - 1)
                c_prefix = "└── " if c_last else "├── "

                cname = c.get("Name", "?")
                status, cstyle = container_style(c)
                uptime = c.get("RunningFor", "")

                text = f"{child_prefix}{c_prefix}{cname} {status}"
                if uptime and fidelity >= 1:
                    text += f" ({uptime})"
                rows.append(Block.text(text, cstyle, width=width))

        if not is_last and fidelity > 0:
            rows.append(Block.text("│", Style(dim=True), width=width))

    return join_vertical(*rows)


def render_minimal(ticks: list[Tick]) -> str:
    """One line summary."""
    by_stack: dict[str, list[dict]] = {}
    total_containers = 0

    for tick in ticks:
        containers = tick.payload.get("containers", [])
        total_containers += len(containers)
        for c in containers:
            stack = c.get("Project", "unknown")
            if stack not in by_stack:
                by_stack[stack] = []
            by_stack[stack].append(c)

    healthy_stacks = 0
    total_stacks = len(by_stack)

    for stack_containers in by_stack.values():
        h, t = count_healthy(stack_containers)
        if h == t:
            healthy_stacks += 1

    icon = "✓" if healthy_stacks == total_stacks else "✗"
    return f"{icon} {healthy_stacks}/{total_stacks} stacks ({total_containers} containers)"


# ============================================================================
# TUI
# ============================================================================


class StatusApp(Surface):
    """Interactive TUI driven by vertex ticks."""

    def __init__(self):
        super().__init__(on_start=self._on_start)
        self._ticks: list[Tick] = []
        self._zoom = 1
        self._loading = True
        self._error: str | None = None
        self._runner: Runner | None = None

    async def _on_start(self) -> None:
        asyncio.create_task(self._run_vertex())

    async def _run_vertex(self) -> None:
        try:
            vertex, sources, _ = load_vertex()
            self._runner = Runner(vertex)
            for source in sources:
                self._runner.add(source)

            async for tick in self._runner.run():
                self._ticks.append(tick)
                self._loading = False
                self.mark_dirty()

        except Exception as e:
            self._error = str(e)
            self._loading = False
            self.mark_dirty()

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()
        elif key in ("+", "="):
            self._zoom = min(3, self._zoom + 1)
            self.mark_dirty()
        elif key == "-":
            self._zoom = max(0, self._zoom - 1)
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        width = self._buf.width - 4

        if self._error:
            content = Block.text(f"Error: {self._error}", Style(fg="red"), width=width)
        elif self._loading and not self._ticks:
            content = Block.text("Fetching...", Style(dim=True), width=width)
        elif self._ticks:
            tree = render_from_ticks(self._ticks, self._zoom, width)
            status = "loading..." if self._loading else f"zoom: {self._zoom}"
            help_line = Block.text(f"{status}  (+/- zoom, q quit)", Style(dim=True), width=width)
            content = join_vertical(tree, Block.text("", Style(), width=width), help_line)
        else:
            content = Block.text("No data", Style(dim=True), width=width)

        bordered = border(content, title="hlab", chars=ROUNDED)
        bordered.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)


# ============================================================================
# CLI
# ============================================================================


def terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def parse_fidelity(args: list[str]) -> int:
    if "-q" in args or "--quiet" in args:
        return 0
    if "-ff" in args:
        return 3
    f_count = sum(1 for arg in args if arg == "-f")
    return min(f_count + 1, 3)


async def run_once() -> list[Tick]:
    """Run vertex, return all ticks."""
    vertex, sources, _ = load_vertex()
    runner = Runner(vertex)
    for source in sources:
        runner.add(source)

    ticks = []
    async for tick in runner.run():
        ticks.append(tick)
    return ticks


async def main_async() -> int:
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0

    fidelity = parse_fidelity(args)
    width = terminal_width()

    if fidelity == 3 and sys.stdout.isatty():
        app = StatusApp()
        await app.run()
        return 0

    # CLI modes: run once, render, exit
    ticks = await run_once()
    if not ticks:
        print("No data", file=sys.stderr)
        return 1

    if fidelity == 0:
        print(render_minimal(ticks))
    else:
        block = render_from_ticks(ticks, fidelity - 1, width - 4)
        print_block(border(block, title="hlab", chars=ROUNDED))

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
