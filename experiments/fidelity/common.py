"""Common utilities for fidelity spectrum demos."""

from __future__ import annotations

import os
import sys
from enum import IntEnum

from cells import Block, print_block


class Fidelity(IntEnum):
    """Fidelity levels from minimal to interactive."""

    MINIMAL = 0  # -q: one line, bare minimum
    STANDARD = 1  # default: typical CLI output
    STYLED = 2  # -v: styled, structured output
    INTERACTIVE = 3  # -vv: full TUI


def parse_fidelity(args: list[str]) -> Fidelity:
    """Parse fidelity from command-line args.

    -q/--quiet -> MINIMAL (0)
    (nothing)  -> STANDARD (1)
    -v         -> STYLED (2)
    -vv        -> INTERACTIVE (3)
    """
    if "-q" in args or "--quiet" in args:
        return Fidelity.MINIMAL

    v_count = 0
    for arg in args:
        if arg == "-vv":
            v_count = max(v_count, 2)
        elif arg == "-v" or arg == "--verbose":
            v_count += 1

    return Fidelity(min(v_count + 1, 3))


def is_interactive() -> bool:
    """Check if stdout is a TTY and supports interactive mode."""
    return sys.stdout.isatty()


def terminal_width() -> int:
    """Get terminal width, defaulting to 80."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def output_block(block: Block) -> None:
    """Print a Block to stdout without alt screen."""
    print_block(block)


def output_plain(text: str) -> None:
    """Print plain text to stdout."""
    print(text)
