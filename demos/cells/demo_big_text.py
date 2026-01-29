#!/usr/bin/env python3
"""Demo: Big Text — block character rendering with multiple sizes and styles.

Features:
- Size 1 (3-row) and Size 2 (5-row) fonts
- Filled and outline formats
- Rainbow color cycling
- Multiple demo modes

Run: uv run python demos/cells/demo_big_text.py
Keys: 1-4 modes, s=size, f=format, q=quit
"""

import asyncio
from cells import Style, border, pad, join_horizontal, ROUNDED
from cells.tui import Surface
from cells.effects import render_big, BigTextFormat


# Color palettes using hex strings (the Color type supports str, int, or hex)
RAINBOW = [
    "#ff3c3c",    # red
    "#ffa028",    # orange
    "#ffe632",    # yellow
    "#50dc50",    # green
    "#3cb4ff",    # cyan
    "#6464ff",    # blue
    "#b464ff",    # purple
    "#ff64b4",    # pink
]

FIRE = [
    "#ffff64",    # bright yellow
    "#ffdc32",    # yellow
    "#ffa01e",    # orange
    "#ff6414",    # red-orange
    "#ff3214",    # red
    "#c81e0a",    # dark red
]

OCEAN = [
    "#64ffff",    # bright cyan
    "#3cdcff",    # light blue
    "#28b4ff",    # sky blue
    "#1e8cdc",    # blue
    "#1464b4",    # deep blue
    "#1e8cdc",    # blue
    "#28b4ff",    # sky blue
]


class BigTextDemo(Surface):
    def __init__(self):
        super().__init__()
        self.frame = 0
        self.mode = 1  # 1: rainbow, 2: fire, 3: sizes, 4: showcase
        self.size = 1  # 1 or 2
        self.format = BigTextFormat.FILLED
        self.color_offset = 0

    def update(self) -> None:
        self.frame += 1

        if self.frame % 3 == 0:
            self.color_offset = (self.color_offset + 1) % len(RAINBOW)
            self.mark_dirty()

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())

        if self.mode == 1:
            self._render_rainbow()
        elif self.mode == 2:
            self._render_fire()
        elif self.mode == 3:
            self._render_sizes()
        else:
            self._render_showcase()

        # Status bar
        size_label = f"size={self.size}"
        fmt_label = "filled" if self.format == BigTextFormat.FILLED else "outline"
        mode_names = {1: "Rainbow", 2: "Fire", 3: "Sizes", 4: "Showcase"}
        status = f"Mode: {mode_names[self.mode]} | {size_label} | {fmt_label} | 1-4:mode s:size f:format q:quit"
        self._buf.put_text(2, self._buf.height - 1, status, Style(dim=True))

    def _render_rainbow(self) -> None:
        """Rainbow cycling text."""
        word = "loops"
        char_blocks = []
        for i, char in enumerate(word):
            color_idx = (self.color_offset + i * 2) % len(RAINBOW)
            style = Style(fg=RAINBOW[color_idx])
            char_blocks.append(render_big(char, style, size=self.size, format=self.format))

        if char_blocks:
            big_block = join_horizontal(*char_blocks, gap=1)
            border_color = RAINBOW[self.color_offset % len(RAINBOW)]
            bordered = border(
                pad(big_block, left=2, right=2, top=1, bottom=1),
                chars=ROUNDED,
                style=Style(fg=border_color)
            )
            x = max(0, (self._buf.width - bordered.width) // 2)
            y = max(0, (self._buf.height - bordered.height) // 2 - 1)
            bordered.paint(self._buf, x, y)

        self._buf.put_text(2, 1, "Rainbow Mode", Style(fg="#646464"))

    def _render_fire(self) -> None:
        """Fire palette animation."""
        word = "fire"
        char_blocks = []
        for i, char in enumerate(word):
            color_idx = (self.color_offset + i) % len(FIRE)
            style = Style(fg=FIRE[color_idx])
            char_blocks.append(render_big(char, style, size=self.size, format=self.format))

        if char_blocks:
            big_block = join_horizontal(*char_blocks, gap=1)
            border_color = FIRE[self.color_offset % len(FIRE)]
            bordered = border(
                pad(big_block, left=2, right=2, top=1, bottom=1),
                chars=ROUNDED,
                style=Style(fg=border_color)
            )
            x = max(0, (self._buf.width - bordered.width) // 2)
            y = max(0, (self._buf.height - bordered.height) // 2 - 1)
            bordered.paint(self._buf, x, y)

        self._buf.put_text(2, 1, "Fire Mode", Style(fg="#646464"))

    def _render_sizes(self) -> None:
        """Compare size 1 and size 2 side by side."""
        y = 2
        self._buf.put_text(2, y, "Size Comparison", Style(fg="#969696"))
        y += 2

        # Size 1
        self._buf.put_text(2, y, "size=1 (3 rows):", Style(dim=True))
        y += 1
        small = render_big("hello", Style(fg="#64c8ff"), size=1, format=self.format)
        small.paint(self._buf, 2, y)
        y += small.height + 2

        # Size 2
        self._buf.put_text(2, y, "size=2 (5 rows):", Style(dim=True))
        y += 1
        big = render_big("hello", Style(fg="#ffc864"), size=2, format=self.format)
        big.paint(self._buf, 2, y)

    def _render_showcase(self) -> None:
        """Static showcase of alphabet, numbers, symbols."""
        y = 1

        # Title
        self._buf.put_text(2, y, "Big Text Showcase", Style(fg="#969696"))
        y += 2

        # Alphabet (first half)
        self._buf.put_text(2, y, "alphabet:", Style(dim=True))
        y += 1
        alpha1 = render_big("abcdefghijklm", Style(fg="#50c8ff"), size=self.size, format=self.format)
        alpha1.paint(self._buf, 2, y)
        y += alpha1.height + 1

        # Alphabet (second half)
        alpha2 = render_big("nopqrstuvwxyz", Style(fg="#50c8ff"), size=self.size, format=self.format)
        alpha2.paint(self._buf, 2, y)
        y += alpha2.height + 1

        # Digits
        self._buf.put_text(2, y, "digits:", Style(dim=True))
        y += 1
        nums = render_big("0123456789", Style(fg="#ffc850"), size=self.size, format=self.format)
        nums.paint(self._buf, 2, y)
        y += nums.height + 1

        # Symbols
        self._buf.put_text(2, y, "symbols:", Style(dim=True))
        y += 1
        syms = render_big("!?.,:-+=#@", Style(fg="#c878ff"), size=self.size, format=self.format)
        syms.paint(self._buf, 2, y)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key == "1":
            self.mode = 1
        elif key == "2":
            self.mode = 2
        elif key == "3":
            self.mode = 3
        elif key == "4":
            self.mode = 4
        elif key == "s":
            self.size = 2 if self.size == 1 else 1
        elif key == "f":
            self.format = (
                BigTextFormat.OUTLINE
                if self.format == BigTextFormat.FILLED
                else BigTextFormat.FILLED
            )


if __name__ == "__main__":
    asyncio.run(BigTextDemo().run())
