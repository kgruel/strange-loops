#!/usr/bin/env python3
"""Demo 05: Compose — combining blocks.

Blocks are immutable, so you combine them with functions:
join_horizontal, join_vertical, pad, border, truncate.
Each returns a new Block.

Run: uv run python demos/demo_05_compose.py
"""

from cells import (
    Buffer, Block, Style, Align,
    join_horizontal, join_vertical, pad, border, truncate,
    ROUNDED, HEAVY, DOUBLE,
)
from demo_utils import render_buffer

# --- join_horizontal: left to right ---

left = Block.text("LEFT", Style(fg="red"))
middle = Block.text("MID", Style(fg="green"))
right = Block.text("RIGHT", Style(fg="blue"))

joined = join_horizontal(left, middle, right)

print("join_horizontal(left, middle, right):")
buf = Buffer(joined.width + 2, 3)
joined.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- join_horizontal with gap ---

joined_gap = join_horizontal(left, middle, right, gap=2)

print("join_horizontal(..., gap=2):")
buf = Buffer(joined_gap.width + 2, 3)
joined_gap.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- join_vertical: top to bottom ---

top = Block.text("Top line", Style(fg="yellow"))
bottom = Block.text("Bottom", Style(fg="cyan"))

stacked = join_vertical(top, bottom)

print("join_vertical(top, bottom):")
buf = Buffer(stacked.width + 2, stacked.height + 2)
stacked.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- Alignment ---

short = Block.text("Hi", Style(fg="green"))
long = Block.text("Hello world", Style(fg="magenta"))

print("join_vertical with different alignments:")

for align in [Align.START, Align.CENTER, Align.END]:
    aligned = join_vertical(short, long, align=align)
    print(f"  Align.{align.name}:")
    buf = Buffer(aligned.width + 4, aligned.height + 2)
    buf.fill(0, 0, buf.width, buf.height, "·", Style(dim=True))
    aligned.paint(buf, x=2, y=1)
    render_buffer(buf)
    print()

# --- pad: add margins ---

content = Block.text("Padded", Style(fg="cyan"))
padded = pad(content, left=2, right=2, top=1, bottom=1)

print(f"pad(block, left=2, right=2, top=1, bottom=1):")
print(f"  original: {content.width}x{content.height}")
print(f"  padded:   {padded.width}x{padded.height}")
buf = Buffer(padded.width + 2, padded.height + 2)
buf.fill(0, 0, buf.width, buf.height, "░", Style(dim=True))
padded.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- border: wrap with box drawing ---

inner = Block.text("Bordered", Style(fg="green"))
boxed = border(inner)

print("border(block) - default ROUNDED chars:")
buf = Buffer(boxed.width + 2, boxed.height + 2)
boxed.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- border with title ---

titled = border(inner, title="Title", style=Style(fg="blue"))

print("border(block, title='Title'):")
buf = Buffer(titled.width + 2, titled.height + 2)
titled.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- border styles ---

print("Border character sets:")
for name, chars in [("ROUNDED", ROUNDED), ("HEAVY", HEAVY), ("DOUBLE", DOUBLE)]:
    b = border(Block.text(name, Style()), chars=chars)
    buf = Buffer(b.width + 2, b.height + 2)
    b.paint(buf, x=1, y=1)
    render_buffer(buf)
print()

# --- truncate: cut to width ---

wide = Block.text("This is too wide", Style(fg="red"))
narrow = truncate(wide, width=10)

print(f"truncate(block, width=10): '{wide.width}' -> '{narrow.width}'")
buf = Buffer(12, 3)
narrow.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- Composition: combining everything ---

print("Composition example - building a panel:")

title_block = Block.text("Status", Style(fg="white", bold=True))
body = join_vertical(
    Block.text("CPU: 45%", Style(fg="green")),
    Block.text("MEM: 2.1G", Style(fg="yellow")),
    Block.text("NET: 12MB/s", Style(fg="cyan")),
)
panel = border(pad(body, left=1, right=1), title="Status", style=Style(fg="blue"))

buf = Buffer(panel.width + 2, panel.height + 2)
panel.paint(buf, x=1, y=1)
render_buffer(buf)
print()

print("Compose functions are pure: Block in, Block out.")
print("Span/Line give styled text primitives (demo_06).")
