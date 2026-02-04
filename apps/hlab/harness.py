"""Harness — fidelity detection and run() entry point for hlab.

Output discipline: UI→stderr, result→stdout
Fidelity controls both rendering detail AND output mode.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from enum import Enum, auto
from typing import Any, Awaitable, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import AsyncIterator
    from vertex import Tick


class OutputMode(Enum):
    """Output modes for hlab commands."""

    CLI = auto()  # print_block() after fetch (fidelity 0-2)
    TUI = auto()  # Persistent Surface (fidelity 3+)
    JSON = auto()  # Machine output (--json)


def detect_fidelity(*, quiet: bool, fidelity_count: int) -> int:
    """Detect fidelity level from CLI flags.

    Args:
        quiet: -q flag was passed
        fidelity_count: Number of -f flags passed

    Returns:
        Fidelity level:
        - 0: minimal (one-liner summary)
        - 1: styled (default, user-friendly)
        - 2: visual (borders, more detail)
        - 3: TUI (full interactive Surface)
    """
    if quiet:
        return 0
    if fidelity_count == 0:
        return 1
    return min(fidelity_count + 1, 3)


def fidelity_to_mode(fidelity: int) -> OutputMode:
    """Map fidelity level to output mode.

    fidelity 0-2 → CLI (fetch all, print_block once)
    fidelity 3+  → TUI (persistent Surface, keyboard quit)
    """
    return OutputMode.TUI if fidelity >= 3 else OutputMode.CLI


def build_parser(
    *,
    prog: str = "hlab",
    description: str | None = None,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
) -> argparse.ArgumentParser:
    """Build argument parser with fidelity flags.

    Args:
        prog: Program name
        description: Program description
        add_args: Callback to add command-specific arguments

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Fidelity group
    fidelity_group = parser.add_mutually_exclusive_group()
    fidelity_group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Minimal output (fidelity 0)",
    )
    fidelity_group.add_argument(
        "-f",
        "--fidelity",
        action="count",
        default=0,
        help="Increase fidelity: -f=visual, -ff=TUI",
    )

    # JSON output
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output to stdout",
    )

    # Command-specific args
    if add_args is not None:
        add_args(parser)

    return parser


def run(
    operation: Callable[[], Awaitable[dict[str, Any]]],
    *,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
    description: str | None = None,
    prog: str = "hlab",
    loader: Callable[[], tuple[Any, list[Any], list[str]]] | None = None,
) -> int:
    """Run an hlab command with fidelity-based output.

    This is the thin harness pattern: parse args, detect mode, dispatch.

    Args:
        operation: Async function that fetches data (returns dict)
        add_args: Callback to add command-specific arguments
        description: Program description for help
        prog: Program name
        loader: Optional function returning (vertex, sources, expected_stack_names)
                for streaming mode. If provided and TTY, uses live spinners.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = build_parser(prog=prog, description=description, add_args=add_args)
    args = parser.parse_args()

    # Detect mode
    if args.json:
        mode = OutputMode.JSON
        fidelity = 1  # Fidelity ignored for JSON
    else:
        fidelity = detect_fidelity(quiet=args.quiet, fidelity_count=args.fidelity)
        mode = fidelity_to_mode(fidelity)

    # Dispatch by mode
    try:
        if mode == OutputMode.JSON:
            return _run_json(operation)
        elif mode == OutputMode.TUI:
            return _run_tui()
        elif fidelity == 2 and loader is not None and _is_tty():
            # Streaming mode with spinners (F2 only)
            return _run_cli_streaming(loader, fidelity)
        else:
            return _run_cli(operation, fidelity)
    except KeyboardInterrupt:
        return 130


def _is_tty() -> bool:
    """Check if stderr is a TTY."""
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


def _run_json(operation: Callable[[], Awaitable[dict[str, Any]]]) -> int:
    """Run in JSON mode: fetch data, print JSON to stdout."""
    data = asyncio.run(operation())
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def _run_cli(operation: Callable[[], Awaitable[dict[str, Any]]], fidelity: int) -> int:
    """Run in CLI mode: fetch data, render with cells, print to stderr."""
    from .emitters import CliEmitter

    data = asyncio.run(operation())
    emitter = CliEmitter(fidelity=fidelity)
    emitter.emit(data)
    return 0


def _run_cli_streaming(
    loader: Callable[[], tuple[Any, list[Any], list[str]]],
    fidelity: int,
) -> int:
    """Run in CLI streaming mode: show spinners as ticks arrive."""
    from .emitters import LiveCliEmitter
    from data import Runner

    async def stream() -> dict[str, dict]:
        vertex, sources, expected = loader()
        runner = Runner(vertex)
        for s in sources:
            runner.add(s)

        emitter = LiveCliEmitter(fidelity, expected)
        return await emitter.run(runner.run())

    asyncio.run(stream())
    return 0


def _run_tui() -> int:
    """Run in TUI mode: launch interactive Surface."""
    from .tui import HlabApp

    app = HlabApp()
    asyncio.run(app.run())
    return 0
