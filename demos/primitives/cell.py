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


def spacer() -> Block:
    return Block.text("", Style())


def demo_attributes() -> Block:
    return join_vertical(
        Block.text("  attributes", Style(dim=True)),
        spacer(),
        row("bold", Style(bold=True)),
        row("italic", Style(italic=True)),
        row("underline", Style(underline=True)),
        row("dim", Style(dim=True)),
        row("reverse", Style(reverse=True)),
    )


def demo_foreground() -> Block:
    return join_vertical(
        Block.text("  foreground", Style(dim=True)),
        spacer(),
        swatch("red"),
        swatch("green"),
        swatch("blue"),
        swatch("yellow"),
        swatch("cyan"),
        swatch("magenta"),
    )


def demo_background() -> Block:
    return join_vertical(
        Block.text("  background", Style(dim=True)),
        spacer(),
        Block.text("  red       ", Style(bg="red", fg="white")),
        Block.text("  green     ", Style(bg="green", fg="black")),
        Block.text("  blue      ", Style(bg="blue", fg="white")),
        Block.text("  yellow    ", Style(bg="yellow", fg="black")),
        Block.text("  cyan      ", Style(bg="cyan", fg="black")),
        Block.text("  magenta   ", Style(bg="magenta", fg="white")),
    )


def demo_combinations() -> Block:
    return join_vertical(
        Block.text("  combinations", Style(dim=True)),
        spacer(),
        row("bold + green", Style(bold=True, fg="green")),
        row("dim + italic", Style(dim=True, italic=True)),
        row("reverse + cyan", Style(reverse=True, fg="cyan")),
        row("bold + underline", Style(bold=True, underline=True, fg="yellow")),
        row("bg + bold", Style(bg="blue", fg="white", bold=True)),
    )


def demo_merge() -> Block:
    base = Style(fg="blue", bold=True)
    overlay = Style(italic=True, fg="red")
    merged = base.merge(overlay)
    return join_vertical(
        Block.text("  merge", Style(dim=True)),
        spacer(),
        Block.text("  base             deploy OK", base),
        Block.text("  + overlay        deploy OK", overlay),
        Block.text("  = merged         deploy OK", merged),
    )


def build_output() -> Block:
    return join_vertical(
        spacer(),
        demo_attributes(),
        spacer(),
        demo_foreground(),
        spacer(),
        demo_background(),
        spacer(),
        demo_combinations(),
        spacer(),
        demo_merge(),
        spacer(),
    )


output = build_output()


def demo() -> None:
    print_block(output)


if __name__ == "__main__":
    demo()
