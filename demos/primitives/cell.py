#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Cell and Style — the visual atom.

Style controls how a character looks: color, weight, emphasis.
Cell pairs a character with a Style. Together they're the smallest
unit of terminal output.

Run: uv run demos/primitives/cell.py
"""

from painted import Block, Style, join_vertical, print_block


def row(label: str, style: Style) -> Block:
    """Label + styled sample on one line."""
    return Block.text(f"  {label:<16} deploy OK", style)


def swatch(color: str) -> Block:
    """A colored block swatch."""
    return Block.text(f"  {color:<10}", Style(fg=color))


# --- Attributes: what Style can express on a single character ---

attributes = join_vertical(
    Block.text("  attributes", Style(dim=True)),
    Block.text("", Style()),
    row("bold", Style(bold=True)),
    row("italic", Style(italic=True)),
    row("underline", Style(underline=True)),
    row("dim", Style(dim=True)),
    row("reverse", Style(reverse=True)),
)

# --- Foreground colors ---

fg_colors = join_vertical(
    Block.text("  foreground", Style(dim=True)),
    Block.text("", Style()),
    swatch("red"),
    swatch("green"),
    swatch("blue"),
    swatch("yellow"),
    swatch("cyan"),
    swatch("magenta"),
)

# --- Background colors ---

bg_colors = join_vertical(
    Block.text("  background", Style(dim=True)),
    Block.text("", Style()),
    Block.text("  red       ", Style(bg="red", fg="white")),
    Block.text("  green     ", Style(bg="green", fg="black")),
    Block.text("  blue      ", Style(bg="blue", fg="white")),
    Block.text("  yellow    ", Style(bg="yellow", fg="black")),
    Block.text("  cyan      ", Style(bg="cyan", fg="black")),
    Block.text("  magenta   ", Style(bg="magenta", fg="white")),
)

# --- Combinations ---

combos = join_vertical(
    Block.text("  combinations", Style(dim=True)),
    Block.text("", Style()),
    row("bold + green", Style(bold=True, fg="green")),
    row("dim + italic", Style(dim=True, italic=True)),
    row("reverse + cyan", Style(reverse=True, fg="cyan")),
    row("bold + underline", Style(bold=True, underline=True, fg="yellow")),
    row("bg + bold", Style(bg="blue", fg="white", bold=True)),
)

# --- Merge: styles compose ---

base = Style(fg="blue", bold=True)
overlay = Style(italic=True, fg="red")
merged = base.merge(overlay)

merge_demo = join_vertical(
    Block.text("  merge", Style(dim=True)),
    Block.text("", Style()),
    Block.text("  base             deploy OK", base),
    Block.text("  + overlay        deploy OK", overlay),
    Block.text("  = merged         deploy OK", merged),
)

# --- Output ---

output = join_vertical(
    Block.text("", Style()),
    attributes,
    Block.text("", Style()),
    fg_colors,
    Block.text("", Style()),
    bg_colors,
    Block.text("", Style()),
    combos,
    Block.text("", Style()),
    merge_demo,
    Block.text("", Style()),
)

print_block(output)
