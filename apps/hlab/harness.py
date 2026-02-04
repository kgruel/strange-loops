"""Harness — run_cli wrapper for hlab.

Thin layer over cells.fidelity that provides a custom handler for
INTERACTIVE mode (TUI). Other modes use cells' defaults.

CLI flags:
    -q/--quiet     → Zoom.MINIMAL (one-liner)
    (default)      → Zoom.SUMMARY (tree view)
    -v             → Zoom.DETAILED (bordered tree)
    -vv            → Zoom.FULL (bordered tree)
    -i             → INTERACTIVE (TUI)
    --json         → JSON to stdout
    --plain        → No ANSI codes
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from cells import Block, CliContext, OutputMode, run_cli

from .lenses import status_view
from .theme import DEFAULT_THEME

if TYPE_CHECKING:
    from argparse import ArgumentParser


def render(ctx: CliContext, stacks: dict[str, dict]) -> Block:
    """Render stacks at the requested zoom level."""
    return status_view(stacks, ctx.zoom, ctx.width, DEFAULT_THEME)


def run(
    operation: Callable[[], Awaitable[dict[str, Any]]],
    *,
    add_args: Callable[[ArgumentParser], None] | None = None,
    description: str | None = None,
    prog: str = "hlab",
    loader: Callable[[], tuple[Any, list[Any], list[str]]] | None = None,
) -> int:
    """Run an hlab command with cells CLI harness.

    Args:
        operation: Async function that fetches data (returns dict)
        add_args: Callback to add command-specific arguments
        description: Program description for help
        prog: Program name
        loader: Unused (kept for API compatibility). Streaming mode removed.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Suppress unused parameter warning
    _ = loader

    def fetch() -> dict[str, dict]:
        return asyncio.run(operation())

    def interactive_handler(ctx: CliContext) -> int:
        """Handle INTERACTIVE mode with TUI."""
        return _run_tui()

    try:
        return run_cli(
            sys.argv[1:],
            render=render,
            fetch=fetch,
            description=description,
            prog=prog,
            add_args=add_args,
            handlers={
                OutputMode.INTERACTIVE: interactive_handler,
            },
        )
    except KeyboardInterrupt:
        return 130


def _run_tui() -> int:
    """Run in INTERACTIVE mode with TUI."""
    from .tui import HlabApp

    app = HlabApp()
    asyncio.run(app.run())
    return 0
