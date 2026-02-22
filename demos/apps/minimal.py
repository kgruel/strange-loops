#!/usr/bin/env python3
"""Minimal — the simplest Surface application.

Surface handles:
- Alternate screen (clean terminal)
- Keyboard input
- Terminal resize (SIGWINCH)
- Diff-based rendering (only changed cells update)

Subclass and override: layout(), render(), on_key(), update()

Run: uv run python demos/cells/apps/minimal.py
Press 'q' to quit, arrow keys to move, 'c' to cycle colors.
"""

import asyncio
from fidelis import Block, Style, border
from fidelis.tui import Surface

COLORS = ["red", "green", "yellow", "blue", "magenta", "cyan"]


class MinimalApp(Surface):
    def __init__(self):
        super().__init__()
        self.x = 5
        self.y = 3
        self.color_idx = 0
        self.message = "Arrow keys move, 'c' changes color, 'q' quits"

    def layout(self, width: int, height: int) -> None:
        """Called on startup and resize."""
        self.term_width = width
        self.term_height = height

    def render(self) -> None:
        """Called each frame. Paint into self._buf."""
        # Clear with background
        self._buf.fill(0, 0, self._buf.width, self._buf.height, "·", Style(dim=True))

        # Status bar at top
        status = f" {self.term_width}x{self.term_height} | pos=({self.x},{self.y}) "
        self._buf.put_text(0, 0, status, Style(fg="black", bg="white"))

        # Movable box
        color = COLORS[self.color_idx]
        content = Block.text(f" {color} ", Style(fg=color, bold=True))
        box = border(content, style=Style(fg=color))
        box.paint(self._buf, self.x, self.y)

        # Instructions at bottom
        self._buf.put_text(0, self._buf.height - 1, self.message, Style(dim=True))

    def on_key(self, key: str) -> None:
        """Handle keyboard input. Keys are named strings."""
        if key == "q":
            self.quit()
        elif key == "c":
            self.color_idx = (self.color_idx + 1) % len(COLORS)
        elif key == "up":
            self.y = max(1, self.y - 1)
        elif key == "down":
            self.y = min(self.term_height - 5, self.y + 1)
        elif key == "right":
            self.x = min(self.term_width - 10, self.x + 1)
        elif key == "left":
            self.x = max(0, self.x - 1)


if __name__ == "__main__":
    asyncio.run(MinimalApp().run())
