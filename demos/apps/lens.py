#!/usr/bin/env python3
"""Lens — content-to-Block transformation at zoom levels.

Lens bundles a render function with zoom metadata for semantic zooming.
This demo shows a JSON inspector with adjustable zoom levels.

Run: uv run python demos/cells/apps/lens.py
Press '+'/'-' to adjust zoom level, 'q' to quit.
"""

import asyncio
from dataclasses import dataclass, replace

from fidelis import (
    Block,
    Style,
    join_vertical,
    pad,
    border,
    ROUNDED,
)
from fidelis.tui import Surface
from fidelis.lens import shape_lens, SHAPE_LENS


SAMPLE_DATA = {
    "name": "Alice",
    "age": 30,
    "tags": ["developer", "python", "async"],
    "address": {
        "city": "NYC",
        "zip": "10001",
    },
}


@dataclass(frozen=True)
class AppState:
    """Application state."""

    zoom: int = 2
    width: int = 80
    height: int = 24


class LensApp(Surface):
    def __init__(self):
        super().__init__()
        self._state = AppState()

    def layout(self, width: int, height: int) -> None:
        self._state = replace(self._state, width=width, height=height)

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())

        # Title
        title = Block.text(" Lens Demo - JSON Inspector ", Style(fg="cyan", bold=True))
        title.paint(self._buf, 2, 1)

        # Zoom level indicator
        zoom_text = f"Zoom: {self._state.zoom} / {SHAPE_LENS.max_zoom}"
        zoom_block = Block.text(zoom_text, Style(fg="yellow", bold=True))
        zoom_block.paint(self._buf, 2, 3)

        # Zoom bar visualization
        bar = ["["]
        for i in range(SHAPE_LENS.max_zoom + 1):
            if i == self._state.zoom:
                bar.append("*")
            else:
                bar.append("-")
        bar.append("]")
        bar_text = "".join(bar)
        bar_block = Block.text(bar_text, Style(fg="green"))
        bar_block.paint(self._buf, 12 + len(zoom_text), 3)

        # Render the data using shape_lens
        content_width = max(40, self._state.width - 10)
        data_block = shape_lens(SAMPLE_DATA, self._state.zoom, content_width)

        # Wrap in a border
        data_block = pad(data_block, left=1, right=1, top=1, bottom=1)
        data_block = border(data_block, ROUNDED, Style(fg="blue"), title="Data")

        data_block.paint(self._buf, 4, 5)

        # Instructions
        instructions = [
            Block.text("+/-  change zoom", Style(dim=True)),
            Block.text("q    quit", Style(dim=True)),
        ]
        y = self._state.height - 3
        for inst in instructions:
            inst.paint(self._buf, 4, y)
            y += 1

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return

        if key in ("+", "="):
            new_zoom = min(SHAPE_LENS.max_zoom, self._state.zoom + 1)
            self._state = replace(self._state, zoom=new_zoom)

        if key in ("-", "_"):
            new_zoom = max(0, self._state.zoom - 1)
            self._state = replace(self._state, zoom=new_zoom)


if __name__ == "__main__":
    asyncio.run(LensApp().run())
