"""Homelab Monitoring TUI: real-time view of homelab state.

Uses shape_lens to auto-render tick payloads at configurable zoom levels.

Run:
    uv run python experiments/homelab/viz.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from glob import glob as globfn
from pathlib import Path

from data import Runner, Source
from dsl import (
    compile_loop,
    compile_vertex_recursive,
    materialize_vertex,
    parse_loop_file,
    parse_vertex_file,
    validate,
)
from vertex import Vertex
from cells import Block, Style, join_vertical, join_horizontal, pad, border
from cells.tui import Surface
from cells.lens import shape_lens


# -- Styles ------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
CYAN = Style(fg="cyan")
GREEN = Style(fg="green")
YELLOW = Style(fg="yellow")
RED = Style(fg="red")


# -- DSL Loading -------------------------------------------------------------

def load_vertex_and_sources(vertex_path: Path) -> tuple[Vertex, list[Source]]:
    """Load vertex and sources from DSL files."""
    ast = parse_vertex_file(vertex_path)
    validate(ast)

    compiled = compile_vertex_recursive(ast)
    vertex = materialize_vertex(compiled)

    sources = []
    if ast.sources:
        for pattern in ast.sources:
            full_pattern = str(vertex_path.parent / pattern)
            for loop_path in globfn(full_pattern, recursive=True):
                loop_ast = parse_loop_file(Path(loop_path))
                validate(loop_ast)
                sources.append(compile_loop(loop_ast))

    return vertex, sources


# -- App ---------------------------------------------------------------------

class HomelabApp(Surface):
    """TUI for homelab monitoring with shape_lens rendering."""

    def __init__(self, vertex: Vertex, runner: Runner):
        super().__init__(
            fps_cap=30,
            on_start=self._on_start,
            on_stop=self._on_stop,
        )
        self._vertex = vertex
        self._runner = runner
        self._runner_task: asyncio.Task | None = None
        self._tick_count = 0
        self._w = 80
        self._h = 24
        self._zoom = 2  # Start at full detail
        # Track latest tick payloads (state resets after boundary fires)
        self._health_state: dict = {}
        self._alerts_state: dict = {}
        self._errors_state: dict = {}
        # Stack ticks from discovered vertices
        self._infra_state: dict = {}
        self._media_state: dict = {}

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    async def _on_start(self) -> None:
        """Start the runner when TUI mounts."""
        self._runner_task = asyncio.create_task(self._run_runner())

    async def _run_runner(self) -> None:
        """Run the Runner in background."""
        try:
            async for tick in self._runner.run():
                self._tick_count += 1
                # Capture tick payloads (state resets after boundary)
                payload = tick.payload if isinstance(tick.payload, dict) else {}
                if tick.name == "health":
                    self._health_state = payload
                elif tick.name == "alerts":
                    self._alerts_state = payload
                elif tick.name == "source.error":
                    self._errors_state = payload
                elif tick.name == "infra.health":
                    self._infra_state = payload
                elif tick.name == "media.health":
                    self._media_state = payload
                self.mark_dirty()
        except asyncio.CancelledError:
            pass

    async def _on_stop(self) -> None:
        """Cleanup when TUI exits."""
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
        await self._runner.stop()

    def render(self) -> None:
        if self._buf is None:
            return

        width = self._w - 4  # Padding
        panel_width = (width - 4) // 2  # Two columns
        now = datetime.now().strftime("%H:%M:%S")

        # Header
        header = Block.text(
            f"Homelab Monitor | {now} | ticks: {self._tick_count} | zoom: {self._zoom} (+/-)",
            BOLD,
            width=width
        )

        # Stack panels (primary data)
        infra_content = shape_lens(self._infra_state or {"status": "waiting..."}, self._zoom, panel_width - 4)
        infra_panel = border(infra_content, title="Infra Stack", style=CYAN)

        media_content = shape_lens(self._media_state or {"status": "waiting..."}, self._zoom, panel_width - 4)
        media_panel = border(media_content, title="Media Stack", style=CYAN)

        # Secondary panels
        errors_content = shape_lens(self._errors_state or {"status": "none"}, self._zoom, panel_width - 4)
        errors_panel = border(errors_content, title="Errors", style=RED if self._errors_state.get("errors") else GREEN)

        alerts_content = shape_lens(self._alerts_state or {"status": "waiting..."}, self._zoom, panel_width - 4)
        alerts_panel = border(alerts_content, title="Alerts", style=YELLOW)

        # Layout: stacks on top row, errors/alerts on second row
        stacks_row = join_horizontal(infra_panel, Block.empty(2, infra_panel.height), media_panel)
        secondary_row = join_horizontal(errors_panel, Block.empty(2, errors_panel.height), alerts_panel)

        help_text = "[q]uit  [+/-] zoom  [r]efresh"
        help_line = Block.text(help_text, DIM, width=width)

        content = join_vertical(
            header,
            Block.empty(width, 1),
            stacks_row,
            Block.empty(width, 1),
            secondary_row,
            Block.empty(width, 1),
            help_line,
        )

        padded = pad(content, left=2, top=1)

        # Clear and paint
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def on_key(self, key: str) -> None:
        if key in ("q", "Q", "escape"):
            self.quit()
        elif key in ("+", "="):
            self._zoom = min(self._zoom + 1, 3)
            self.mark_dirty()
        elif key in ("-", "_"):
            self._zoom = max(self._zoom - 1, 0)
            self.mark_dirty()
        elif key == "r":
            self.mark_dirty()


# -- Main --------------------------------------------------------------------

async def main():
    """Run the homelab TUI."""
    here = Path(__file__).parent
    vertex_path = here / "root.vertex"

    vertex, sources = load_vertex_and_sources(vertex_path)
    runner = Runner(vertex)
    for source in sources:
        runner.add(source)

    print(f"Starting homelab monitor with {len(sources)} source(s)...")

    app = HomelabApp(vertex, runner)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
