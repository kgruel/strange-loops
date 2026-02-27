#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Compose — spatial combination of Blocks.

Blocks are immutable. Composition functions take Blocks in,
return new Blocks out: join, pad, border, truncate.
This is how you build layouts without a mutable canvas.

Run: uv run demos/primitives/compose.py
"""

from painted import (
    Block, Style, Wrap, Align,
    join_horizontal, join_vertical, pad, border, truncate,
    print_block, ROUNDED, HEAVY, DOUBLE,
)


def header(text: str) -> Block:
    """Dim section header."""
    return Block.text(f"  {text}", Style(dim=True))


def spacer() -> Block:
    return Block.text("", Style())


# --- join_horizontal: side by side ---

h_joined = join_horizontal(
    Block.text("  cpu ", Style(fg="green", bold=True)),
    Block.text(" mem ", Style(fg="yellow", bold=True)),
    Block.text(" net ", Style(fg="cyan", bold=True)),
)

h_gapped = join_horizontal(
    Block.text("  cpu ", Style(fg="green", bold=True)),
    Block.text(" mem ", Style(fg="yellow", bold=True)),
    Block.text(" net ", Style(fg="cyan", bold=True)),
    gap=2,
)

horizontal = join_vertical(
    header("join_horizontal"),
    spacer(),
    h_joined,
    h_gapped,
)

# --- join_vertical + alignment ---

short = Block.text("  ok", Style(fg="green"))
long = Block.text("  deploy complete", Style(fg="cyan"))

alignment = join_vertical(
    header("alignment"),
    spacer(),
    join_horizontal(
        border(join_vertical(short, long, align=Align.START),
               title="START", style=Style(dim=True)),
        border(join_vertical(short, long, align=Align.CENTER),
               title="CENTER", style=Style(dim=True)),
        border(join_vertical(short, long, align=Align.END),
               title="END", style=Style(dim=True)),
        gap=1,
    ),
)

# --- pad: margins ---

content = Block.text("content", Style(fg="cyan"))

padding = join_vertical(
    header("pad"),
    spacer(),
    join_horizontal(
        border(content, title="no pad", style=Style(dim=True)),
        border(pad(content, left=2, right=2),
               title="h-pad", style=Style(dim=True)),
        border(pad(content, left=2, right=2, top=1, bottom=1),
               title="all", style=Style(dim=True)),
        gap=1,
    ),
)

# --- border: box drawing ---

inner = Block.text("status: ok", Style(fg="green"))

borders = join_vertical(
    header("border"),
    spacer(),
    join_horizontal(
        border(inner, chars=ROUNDED, title="ROUNDED"),
        border(inner, chars=HEAVY, title="HEAVY"),
        border(inner, chars=DOUBLE, title="DOUBLE"),
        gap=1,
    ),
)

# --- truncate: cut to width ---

wide = Block.text("  the configuration file could not be parsed", Style(fg="red"))

trunc = join_vertical(
    header("truncate"),
    spacer(),
    wide,
    truncate(wide, width=30),
    truncate(wide, width=18),
)

# --- wrap: text fitting with Block.text(width=, wrap=) ---

text = "the quick brown fox jumps over the lazy dog"

wrapping = join_vertical(
    header("wrap modes (Block.text with width=20)"),
    spacer(),
    join_horizontal(
        border(Block.text(text, Style(), width=20, wrap=Wrap.NONE),
               title="NONE", style=Style(dim=True)),
        border(Block.text(text, Style(), width=20, wrap=Wrap.ELLIPSIS),
               title="ELLIPSIS", style=Style(dim=True)),
        gap=1,
    ),
    spacer(),
    join_horizontal(
        border(Block.text(text, Style(), width=20, wrap=Wrap.WORD),
               title="WORD", style=Style(dim=True)),
        border(Block.text(text, Style(), width=20, wrap=Wrap.CHAR),
               title="CHAR", style=Style(dim=True)),
        gap=1,
    ),
)

# --- Composition: everything together ---

body = join_vertical(
    Block.text(" CPU   45%", Style(fg="green")),
    Block.text(" MEM  2.1G", Style(fg="yellow")),
    Block.text(" NET  12MB", Style(fg="cyan")),
)
panel = border(pad(body, left=1, right=1), title="Status", style=Style(fg="blue"))

composed = join_vertical(
    header("composition"),
    spacer(),
    join_horizontal(Block.text("  ", Style()), panel),
)

# --- Print it ---

print_block(join_vertical(
    spacer(),
    horizontal,
    spacer(),
    alignment,
    spacer(),
    padding,
    spacer(),
    borders,
    spacer(),
    trunc,
    spacer(),
    wrapping,
    spacer(),
    composed,
    spacer(),
))
