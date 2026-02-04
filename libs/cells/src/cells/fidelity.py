"""Fidelity: unified arg parsing + TTY detection + mode dispatch.

CLI tools with multiple output modes: quiet (machine-readable), normal,
verbose, and full TUI. FidelityHarness detects context and dispatches
to the appropriate handler.

Usage:
    from cells.fidelity import Fidelity, run_with_fidelity

    def quiet(ctx): print('{"ok": true}')
    def normal(ctx): print("OK")

    run_with_fidelity(sys.argv[1:], {
        Fidelity.QUIET: quiet,
        Fidelity.NORMAL: normal,
    })
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, TypeVar

T = TypeVar("T")


class Fidelity(IntEnum):
    """Output fidelity levels."""

    QUIET = 0  # F0: machine-readable, no decoration
    NORMAL = 1  # F1: default terminal output
    VERBOSE = 2  # F2: enhanced output, colors
    FULL = 3  # F3: full TUI or maximum decoration


@dataclass(frozen=True)
class HarnessContext:
    """Resolved runtime context."""

    fidelity: Fidelity
    is_tty: bool
    width: int
    height: int


def detect_fidelity(args: argparse.Namespace) -> Fidelity:
    """Determine fidelity from parsed args.

    Looks for: quiet (F0), verbose count (F2/F3), default (F1).
    """
    if getattr(args, "quiet", False):
        return Fidelity.QUIET

    verbose = getattr(args, "verbose", 0)
    if verbose >= 2:
        return Fidelity.FULL
    if verbose == 1:
        return Fidelity.VERBOSE

    return Fidelity.NORMAL


def detect_context(fidelity: Fidelity | None = None) -> HarnessContext:
    """Detect full context: fidelity, TTY, terminal size.

    If fidelity is None, defaults to F1 for TTY, F0 for non-TTY.
    """
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    if fidelity is None:
        fidelity = Fidelity.NORMAL if is_tty else Fidelity.QUIET

    size = shutil.get_terminal_size()
    return HarnessContext(
        fidelity=fidelity,
        is_tty=is_tty,
        width=size.columns,
        height=size.lines,
    )


def add_fidelity_args(parser: argparse.ArgumentParser) -> None:
    """Add -q, -f, --quiet, --verbose flags to an ArgumentParser."""
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode: minimal, machine-readable output",
    )
    parser.add_argument(
        "-f",
        "--verbose",
        action="count",
        default=0,
        help="Verbose mode: -f for enhanced, -ff for full TUI",
    )


def _find_handler(
    fidelity: Fidelity,
    handlers: dict[Fidelity, Callable[[HarnessContext], T]],
) -> Callable[[HarnessContext], T]:
    """Find handler for fidelity, falling back to lower levels."""
    # Try exact match first
    if fidelity in handlers:
        return handlers[fidelity]

    # Fall back to lower fidelity levels
    for level in reversed(range(int(fidelity))):
        f = Fidelity(level)
        if f in handlers:
            return handlers[f]

    # No handler found
    raise ValueError(
        f"No handler for fidelity {fidelity.name} or lower. "
        f"Available: {[f.name for f in handlers.keys()]}"
    )


def run_with_fidelity(
    args: list[str],
    handlers: dict[Fidelity, Callable[[HarnessContext], T]],
    *,
    parser: argparse.ArgumentParser | None = None,
    description: str | None = None,
) -> T:
    """Parse args, detect context, dispatch to appropriate handler.

    Args:
        args: sys.argv[1:] or equivalent
        handlers: mapping of Fidelity -> handler function
            At minimum, provide NORMAL handler; others fall back gracefully.
        parser: Optional pre-configured ArgumentParser. If None, creates one.
        description: Description for auto-created parser.

    Returns:
        Result from the invoked handler.
    """
    if parser is None:
        parser = argparse.ArgumentParser(description=description)
        add_fidelity_args(parser)

    parsed = parser.parse_args(args)
    fidelity = detect_fidelity(parsed)
    ctx = detect_context(fidelity)

    handler = _find_handler(ctx.fidelity, handlers)
    return handler(ctx)
