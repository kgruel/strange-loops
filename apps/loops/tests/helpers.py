"""Shared test helpers for loops app tests."""

from __future__ import annotations

import io

from painted import Block, print_block


def block_to_text(block: Block, *, use_ansi: bool = False) -> str:
    """Render a Block into plain text via print_block to a StringIO buffer."""
    buf = io.StringIO()
    print_block(block, buf, use_ansi=use_ansi)
    return buf.getvalue()


def block_text(block: Block) -> str:
    """Extract raw text from a Block's cell grid (no ANSI, fast)."""
    return "\n".join(
        "".join(c.char for c in row).rstrip() for row in block._rows
    )
