#!/usr/bin/env python3
"""Demo 01: Cell and Style — the atomic unit.

A Cell is a single character with a Style. That's it.
Style holds colors (fg/bg) and attributes (bold, italic, etc).
Both are immutable (frozen dataclasses).

Run: uv run python demos/demo_01_cell.py
"""

from cells import Cell, Style, EMPTY_CELL

# --- Style: colors and attributes ---

plain = Style()
red = Style(fg="red")
bold_green = Style(fg="green", bold=True)
warning = Style(fg="black", bg="yellow", bold=True)

print("Styles are data:")
print(f"  plain:      {plain}")
print(f"  red:        {red}")
print(f"  bold_green: {bold_green}")
print(f"  warning:    {warning}")
print()

# --- Style.merge: combine styles ---

base = Style(fg="blue", bold=True)
overlay = Style(italic=True, fg="red")  # fg overrides, italic adds
merged = base.merge(overlay)

print("Style.merge() combines styles (overlay wins for colors):")
print(f"  base:    {base}")
print(f"  overlay: {overlay}")
print(f"  merged:  {merged}")
print()

# --- Cell: character + style ---

cell_a = Cell("A", red)
cell_star = Cell("*", warning)

print("Cells are character + style pairs:")
print(f"  cell_a:    {cell_a}")
print(f"  cell_star: {cell_star}")
print()

# --- EMPTY_CELL: the default ---

print(f"EMPTY_CELL is a space with no style: {EMPTY_CELL}")
print()

# --- Immutability ---

print("Both are frozen (immutable):")
try:
    cell_a.char = "B"  # type: ignore
except Exception as e:
    print(f"  cell_a.char = 'B' -> {type(e).__name__}: {e}")

# --- What's next? ---

print()
print("Cells are data. To display them, we need a Buffer (demo_02).")
