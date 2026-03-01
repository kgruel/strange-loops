"""Test helpers — bridge from Block to plain text."""
from __future__ import annotations

import io

from painted import Block, print_block


def block_to_text(block: Block, *, use_ansi: bool = False) -> str:
    """Render a Block into plain text via print_block to a StringIO buffer."""
    buf = io.StringIO()
    print_block(block, buf, use_ansi=use_ansi)
    return buf.getvalue()
