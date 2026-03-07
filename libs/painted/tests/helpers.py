"""Shared helpers for tests.

These are intentionally lightweight and dependency-free (beyond painted itself),
and are used across unit + golden tests to avoid copy-pasting utilities.
"""

from __future__ import annotations

import io

from painted import Block, Cell, CliContext, Style, Zoom
from painted.fidelity import OutputMode
from painted.writer import print_block


def static_ctx(zoom: Zoom) -> CliContext:
    """Build a deterministic CliContext for golden/snapshot testing."""
    return CliContext(
        zoom=zoom,
        mode=OutputMode.STATIC,
        use_ansi=False,
        is_tty=False,
        width=80,
        height=24,
    )


def block_to_text(block: Block, *, use_ansi: bool = False) -> str:
    """Render a Block into plain text (or ANSI) via painted.writer.print_block()."""
    buf = io.StringIO()
    print_block(block, buf, use_ansi=use_ansi)
    return buf.getvalue()


def row_text(block: Block, row_idx: int) -> str:
    """Return the characters for a single block row."""
    return "".join(c.char for c in block.row(row_idx))


def text_block(lines: list[str], style: Style | None = None, *, id: str | None = None) -> Block:
    """Build a Block from text lines, padding rows to uniform width."""
    style = style or Style()
    width = max((len(ln) for ln in lines), default=0)
    rows: list[list[Cell]] = []
    for line in lines:
        row = [Cell(ch, style) for ch in line]
        row += [Cell(" ", style)] * (width - len(line))
        rows.append(row)
    return Block(rows, width, id=id)
