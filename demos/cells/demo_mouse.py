#!/usr/bin/env python3
"""Demo: Mouse input — drawable canvas with click, drag, and scroll.

Features:
- Click to place colored dots
- Drag to draw lines
- Scroll to change brush color
- Right-click to erase
- 'c' to clear canvas
- 'q' to quit

Run: uv run python demos/cells/demo_mouse.py
"""

import asyncio
from cells import (
    Surface,
    Block,
    Style,
    MouseEvent,
    MouseButton,
    MouseAction,
)

PALETTE = [
    "#ff5555",  # red
    "#55ff55",  # green
    "#5555ff",  # blue
    "#ffff55",  # yellow
    "#ff55ff",  # magenta
    "#55ffff",  # cyan
    "#ffffff",  # white
    "#ff8800",  # orange
]


class DrawCanvas(Surface):
    def __init__(self):
        super().__init__(enable_mouse=True)
        self.color_idx = 0
        self.canvas: dict[tuple[int, int], str] = {}  # (x, y) -> color
        self.last_pos: tuple[int, int] | None = None
        self.mouse_pos: tuple[int, int] = (0, 0)
        self.drawing = False

    def layout(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def render(self) -> None:
        # Clear with dots
        self._buf.fill(0, 0, self.width, self.height, "·", Style(dim=True))

        # Draw canvas pixels
        for (x, y), color in self.canvas.items():
            if 0 <= x < self.width and 1 <= y < self.height - 1:
                self._buf.put_text(x, y, "█", Style(fg=color))

        # Status bar at top
        color = PALETTE[self.color_idx]
        status = Block.text(
            f" Mouse Demo │ Color: █ │ Scroll=color, Click=draw, Right=erase, c=clear, q=quit ",
            Style(fg="black", bg="white"),
        )
        # Colorize the block character in status
        status_text = f" Mouse Demo │ Color: "
        self._buf.put_text(0, 0, status_text, Style(fg="black", bg="white"))
        self._buf.put_text(len(status_text), 0, "█", Style(fg=color, bg="white"))
        rest = f" │ Scroll=color, Click=draw, Right=erase, c=clear, q=quit "
        self._buf.put_text(len(status_text) + 1, 0, rest, Style(fg="black", bg="white"))
        # Fill rest of status bar
        filled = len(status_text) + 1 + len(rest)
        if filled < self.width:
            self._buf.put_text(filled, 0, " " * (self.width - filled), Style(bg="white"))

        # Coordinates at bottom
        mx, my = self.mouse_pos
        coords = f" ({mx}, {my}) "
        self._buf.put_text(0, self.height - 1, coords, Style(dim=True))

        # Brush preview follows cursor (if in canvas area)
        if 1 <= my < self.height - 1:
            preview_char = "○" if not self.drawing else "●"
            self._buf.put_text(mx, my, preview_char, Style(fg=color, bold=True))

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key == "c":
            self.canvas.clear()
        elif key == "1":
            self.color_idx = 0
        elif key == "2":
            self.color_idx = 1
        elif key == "3":
            self.color_idx = 2
        elif key == "4":
            self.color_idx = 3
        elif key == "5":
            self.color_idx = 4
        elif key == "6":
            self.color_idx = 5
        elif key == "7":
            self.color_idx = 6
        elif key == "8":
            self.color_idx = 7

    def on_mouse(self, event: MouseEvent) -> None:
        self.mouse_pos = (event.x, event.y)

        # Scroll changes color
        if event.is_scroll:
            if event.button == MouseButton.SCROLL_UP:
                self.color_idx = (self.color_idx - 1) % len(PALETTE)
            else:
                self.color_idx = (self.color_idx + 1) % len(PALETTE)
            return

        # Right click erases
        if event.button == MouseButton.RIGHT:
            if event.action == MouseAction.PRESS:
                self._erase_at(event.x, event.y)
            return

        # Left click/drag draws
        if event.button == MouseButton.LEFT:
            if event.action == MouseAction.PRESS:
                self.drawing = True
                self._draw_at(event.x, event.y)
                self.last_pos = (event.x, event.y)
            elif event.action == MouseAction.RELEASE:
                self.drawing = False
                self.last_pos = None
            elif event.action == MouseAction.MOVE and self.drawing:
                # Draw line from last position to current
                if self.last_pos:
                    self._draw_line(self.last_pos, (event.x, event.y))
                self.last_pos = (event.x, event.y)

        # Motion without button (hover) - just update cursor position
        if event.button == MouseButton.NONE and event.action == MouseAction.MOVE:
            pass  # Cursor position already updated

    def _draw_at(self, x: int, y: int) -> None:
        """Draw a pixel at the given position."""
        if 1 <= y < self.height - 1:  # Stay within canvas area
            self.canvas[(x, y)] = PALETTE[self.color_idx]

    def _erase_at(self, x: int, y: int) -> None:
        """Erase pixel at the given position."""
        self.canvas.pop((x, y), None)

    def _draw_line(self, p1: tuple[int, int], p2: tuple[int, int]) -> None:
        """Draw a line between two points using Bresenham's algorithm."""
        x1, y1 = p1
        x2, y2 = p2

        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy

        while True:
            self._draw_at(x1, y1)
            if x1 == x2 and y1 == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x1 += sx
            if e2 < dx:
                err += dx
                y1 += sy


if __name__ == "__main__":
    asyncio.run(DrawCanvas().run())
