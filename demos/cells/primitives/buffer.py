#!/usr/bin/env python3
"""Buffer — the 2D canvas.

Buffer is a 2D grid of Cells. You put characters at coordinates,
and it stores them. Writer converts the buffer to ANSI for display.

Run: uv run python demos/cells/primitives/buffer.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cells import Style
from cells.tui import Buffer
from demo_utils import render_buffer

# --- Create a buffer ---

buf = Buffer(20, 5)
print("Empty 20x5 buffer (filled with EMPTY_CELL by default):")
render_buffer(buf)
print()

# --- put: single character ---

buf.put(0, 0, "A", Style(fg="red", bold=True))
buf.put(1, 0, "B", Style(fg="green"))
buf.put(2, 0, "C", Style(fg="blue"))

print("After put() at (0,0), (1,0), (2,0):")
render_buffer(buf)
print()

# --- put_text: string horizontally ---

buf.put_text(0, 2, "Hello, Buffer!", Style(fg="yellow"))

print("After put_text() at (0,2):")
render_buffer(buf)
print()

# --- fill: rectangle ---

buf.fill(15, 1, 4, 3, "█", Style(fg="magenta"))

print("After fill() - 4x3 block at (15,1):")
render_buffer(buf)
print()

# --- Out of bounds: silently ignored ---

buf.put(100, 100, "X", Style())  # no-op
buf.put_text(18, 4, "OVERFLOW", Style(fg="red"))  # partially visible

print("Out-of-bounds writes are clipped:")
render_buffer(buf)
print()

# --- get: read back ---

cell = buf.get(0, 0)
print(f"buf.get(0, 0) -> char={cell.char!r}, fg={cell.style.fg}")

# --- What's next? ---

print()
print("Buffer is the canvas. BufferView adds clipped regions (demo_03).")
