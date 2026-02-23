#!/usr/bin/env python3
"""Block — immutable rectangles for composition.

Block is a rectangle of Cells with known dimensions.
Unlike Buffer, blocks are immutable — you compose them, not mutate them.
This is the unit of composition for building UIs.

Run: uv run python demos/primitives/block.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fidelis import Block, Style, Wrap
from fidelis.tui import Buffer
from demo_utils import render_buffer

# --- Block.text: create from a string ---

block = Block.text("Hello, Block!", Style(fg="green"))

print(f"Block.text() with no width constraint:")
print(f"  width={block.width}, height={block.height}")

buf = Buffer(20, 3)
block.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- Fixed width: truncates by default ---

block_fixed = Block.text("This is a longer message", Style(fg="cyan"), width=12)

print(f"Block.text() with width=12 (truncates):")
print(f"  width={block_fixed.width}, height={block_fixed.height}")

buf = Buffer(20, 3)
block_fixed.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- Wrap modes ---

long_text = "The quick brown fox jumps over the lazy dog"

print("Wrap modes with width=15:")
print()

# NONE (default): truncate
block_none = Block.text(long_text, Style(fg="yellow"), width=15, wrap=Wrap.NONE)
print(f"Wrap.NONE (truncate): height={block_none.height}")
buf = Buffer(20, 3)
block_none.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# ELLIPSIS: truncate with …
block_ellipsis = Block.text(long_text, Style(fg="magenta"), width=15, wrap=Wrap.ELLIPSIS)
print(f"Wrap.ELLIPSIS: height={block_ellipsis.height}")
buf = Buffer(20, 3)
block_ellipsis.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# CHAR: break at any character
block_char = Block.text(long_text, Style(fg="red"), width=15, wrap=Wrap.CHAR)
print(f"Wrap.CHAR (break anywhere): height={block_char.height}")
buf = Buffer(20, block_char.height + 2)
block_char.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# WORD: break at word boundaries
block_word = Block.text(long_text, Style(fg="blue"), width=15, wrap=Wrap.WORD)
print(f"Wrap.WORD (break at spaces): height={block_word.height}")
buf = Buffer(20, block_word.height + 2)
block_word.paint(buf, x=1, y=1)
render_buffer(buf)
print()

# --- Block.empty: blank rectangle ---

empty = Block.empty(8, 3, Style(bg="blue"))
print("Block.empty(8, 3) with blue background:")
buf = Buffer(12, 5)
empty.paint(buf, x=2, y=1)
render_buffer(buf)
print()

# --- Blocks are immutable ---

print("Blocks are immutable — paint() copies cells into the buffer.")
print("To modify, create a new block or use compose functions (demo_05).")
