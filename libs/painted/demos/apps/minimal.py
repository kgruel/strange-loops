#!/usr/bin/env python3
"""Minimal — the simplest Surface application.

Surface handles:
- Alternate screen (clean terminal)
- Keyboard input
- Terminal resize (SIGWINCH)
- Diff-based rendering (only changed cells update)

Subclass and override: layout(), render(), on_key(), update()

Run: uv run python demos/apps/minimal.py
Press 'q' to quit, arrow keys to move, 'c' to cycle colors.
"""

import asyncio
from painted import Block, Style, border
from painted.tui import Surface

COLORS = ["red", "green", "yellow", "blue", "magenta", "cyan"]


class MinimalApp(Surface):
    def __init__(self):
        super().__init__()
        self.x = 5
        self.y = 3
        self.color_idx = 0
        self.message = "Arrow keys move, 'c' changes color, 'q' quits"

    def render(self) -> None:
        """Called each frame. Paint into self._buf."""
        buf = self._buf
        # Clear with background
        buf.fill(0, 0, buf.width, buf.height, "·", Style(dim=True))

        # Status bar at top
        status = f" {buf.width}x{buf.height} | pos=({self.x},{self.y}) "
        buf.put_text(0, 0, status, Style(fg="black", bg="white"))

        # Movable box
        color = COLORS[self.color_idx]
        content = Block.text(f" {color} ", Style(fg=color, bold=True))
        box = border(content, style=Style(fg=color))
        box.paint(buf, self.x, self.y)

        # Instructions at bottom
        buf.put_text(0, buf.height - 1, self.message, Style(dim=True))

    def on_key(self, key: str) -> None:
        """Handle keyboard input. Keys are named strings."""
        buf = self._buf
        if key == "q":
            self.quit()
        elif key == "c":
            self.color_idx = (self.color_idx + 1) % len(COLORS)
        elif key == "up":
            self.y = max(1, self.y - 1)
        elif key == "down":
            self.y = min(buf.height - 5, self.y + 1)
        elif key == "right":
            self.x = min(buf.width - 10, self.x + 1)
        elif key == "left":
            self.x = max(0, self.x - 1)


async def main():
    await MinimalApp().run()


if __name__ == "__main__":
    asyncio.run(main())
