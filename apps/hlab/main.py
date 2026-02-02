"""hlab — homelab monitoring.

Usage:
    uv run python apps/hlab/main.py              # TUI
    uv run python apps/hlab/main.py --once       # single fetch, print, exit
    uv run python apps/hlab/main.py --json       # single fetch, JSON output
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from cells import Block, Style, join_vertical, join_horizontal, border, pad, ROUNDED
from cells.tui import Surface

from dsl import parse_vertex_file, parse_loop_file, compile_vertex_recursive, compile_loop, materialize_vertex
from data import Runner
from vertex import Tick


HERE = Path(__file__).parent
VERTEX_FILE = HERE / "status.vertex"


# -- Styles ------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
GREEN = Style(fg="green")
YELLOW = Style(fg="yellow")
RED = Style(fg="red")
CYAN = Style(fg="cyan")


# -- Load DSL ----------------------------------------------------------------

def load():
    """Load vertex and sources from DSL files."""
    ast = parse_vertex_file(VERTEX_FILE)
    compiled = compile_vertex_recursive(ast)
    vertex = materialize_vertex(compiled)

    sources = []
    for source_path in ast.sources:
        full_path = VERTEX_FILE.parent / source_path
        loop_ast = parse_loop_file(full_path)
        sources.append(compile_loop(loop_ast))

    return vertex, sources


# -- Data helpers ------------------------------------------------------------

def stack_health(containers: list[dict]) -> tuple[int, int]:
    """Returns (healthy, total) for a stack."""
    total = len(containers)
    healthy = sum(
        1 for c in containers
        if c.get("State") == "running" and c.get("Health") in ("healthy", "")
    )
    return healthy, total


# -- Render ------------------------------------------------------------------

def render_stack(name: str, containers: list[dict], zoom: int, width: int) -> Block:
    """Render a single stack at given zoom level."""
    h, t = stack_health(containers)
    all_healthy = h == t
    icon = "✓" if all_healthy else "✗"
    header_style = Style(fg="green", bold=True) if all_healthy else Style(fg="red", bold=True)

    header = Block.text(f"{icon} {name}: {h}/{t}", header_style, width=width)

    if zoom == 0:
        return header

    rows = [header]
    for c in containers:
        cname = c.get("Name", "?")
        state = c.get("State", "?")
        health = c.get("Health", "")
        uptime = c.get("RunningFor", "")

        if state == "running" and health == "healthy":
            style = GREEN
            status = "healthy"
        elif state == "running":
            style = Style(fg="blue")
            status = health or "running"
        else:
            style = RED
            status = state

        line = f"  {cname}: {status}"
        if zoom >= 2 and uptime:
            line += f" ({uptime})"
        rows.append(Block.text(line, style, width=width))

    return join_vertical(*rows)


def render_all(stacks: dict[str, list[dict]], zoom: int, width: int) -> Block:
    """Render all stacks. stacks = {name: [containers]}."""
    if not stacks:
        return Block.text("No data", DIM, width=width)

    panel_width = (width - 4) // 2
    panels = []

    for name in sorted(stacks.keys()):
        panel = render_stack(name, stacks[name], zoom, panel_width - 4)
        panels.append(border(panel, title=name, style=CYAN))

    # Arrange in 2-column grid
    rows = []
    for i in range(0, len(panels), 2):
        left = panels[i]
        if i + 1 < len(panels):
            right = panels[i + 1]
            rows.append(join_horizontal(left, Block.empty(2, left.height), right))
        else:
            rows.append(left)

    return join_vertical(*rows)


# -- TUI ---------------------------------------------------------------------

class HlabApp(Surface):
    """Main TUI for hlab."""

    def __init__(self):
        super().__init__(fps_cap=30, on_start=self._on_start)
        # State: {stack_name: [containers]}
        self._stacks: dict[str, list[dict]] = {}
        self._zoom = 1
        self._loading = True
        self._error: str | None = None
        self._w = 80
        self._h = 24

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    async def _on_start(self) -> None:
        asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            vertex, sources = load()
            runner = Runner(vertex)
            for s in sources:
                runner.add(s)

            async for tick in runner.run():
                # tick.name IS the stack name (infra, media, dev, minecraft)
                # tick.payload = {containers: [...]}
                containers = tick.payload.get("containers", [])
                self._stacks[tick.name] = containers
                self._loading = False
                self.mark_dirty()
        except Exception as e:
            self._error = str(e)
            self._loading = False
            self.mark_dirty()

    def on_key(self, key: str) -> None:
        if key in ("q", "Q", "escape"):
            self.quit()
        elif key in ("+", "="):
            self._zoom = min(3, self._zoom + 1)
            self.mark_dirty()
        elif key in ("-", "_"):
            self._zoom = max(0, self._zoom - 1)
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        width = self._w - 4
        now = datetime.now().strftime("%H:%M:%S")

        # Header
        total_healthy = sum(stack_health(c)[0] for c in self._stacks.values())
        total_containers = sum(len(c) for c in self._stacks.values())
        status = f"{len(self._stacks)} stacks, {total_healthy}/{total_containers} healthy"

        header = Block.text(
            f"hlab | {now} | {status} | zoom: {self._zoom}",
            BOLD,
            width=width
        )

        # Content
        if self._error:
            content = Block.text(f"Error: {self._error}", RED, width=width)
        elif self._loading and not self._stacks:
            content = Block.text("Fetching...", DIM, width=width)
        else:
            content = render_all(self._stacks, self._zoom, width)

        # Help
        help_line = Block.text("[q]uit  [+/-] zoom", DIM, width=width)

        # Compose
        body = join_vertical(
            header,
            Block.empty(width, 1),
            content,
            Block.empty(width, 1),
            help_line,
        )

        padded = pad(body, left=2, top=1)

        # Paint
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)


# -- CLI ---------------------------------------------------------------------

async def fetch_stacks() -> dict[str, list[dict]]:
    """Fetch once and return {stack_name: [containers]}."""
    vertex, sources = load()
    runner = Runner(vertex)
    for s in sources:
        runner.add(s)

    stacks = {}
    async for tick in runner.run():
        stacks[tick.name] = tick.payload.get("containers", [])
    return stacks


async def main_async() -> int:
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0

    if "--json" in args:
        stacks = await fetch_stacks()
        print(json.dumps(stacks, indent=2, default=str))
        return 0

    if "--once" in args:
        stacks = await fetch_stacks()
        for name, containers in sorted(stacks.items()):
            h, t = stack_health(containers)
            icon = "✓" if h == t else "✗"
            print(f"{icon} {name}: {h}/{t}")
        return 0

    # Default: TUI
    app = HlabApp()
    await app.run()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
