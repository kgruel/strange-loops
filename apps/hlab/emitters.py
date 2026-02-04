"""Emitters — cells-based output for hlab.

Output discipline: UI→stderr, result→stdout
All rendering uses cells (no Rich).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from cells import Block, Style, Zoom, print_block

from .lenses import status_view, render_plain
from .theme import DEFAULT_THEME, Theme


def _is_tty() -> bool:
    """Check if stderr is a TTY."""
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


def _terminal_width() -> int:
    """Get terminal width, default to 80."""
    try:
        import shutil

        return shutil.get_terminal_size().columns
    except Exception:
        return 80


class CliEmitter:
    """CLI emitter: render stacks with cells, print to stderr.

    Zoom maps to visual treatment:
    - MINIMAL: one-liner summary
    - SUMMARY: tree view (default)
    - DETAILED/FULL: bordered tree with uptime and summary

    Non-TTY output uses plain text fallback.
    """

    def __init__(
        self,
        *,
        zoom: Zoom = Zoom.SUMMARY,
        width: int | None = None,
        theme: Theme = DEFAULT_THEME,
    ) -> None:
        self._zoom = zoom
        self._width = width or _terminal_width()
        self._theme = theme

    def emit(self, stacks: dict[str, dict]) -> None:
        """Render stacks and print to stderr."""
        if not _is_tty():
            # Plain text for non-TTY (piped, captured)
            text = render_plain(stacks, self._theme)
            sys.stderr.write(text + "\n")
            return

        block = render_stacks(stacks, self._zoom, self._width, self._theme)
        print_block(block, stream=sys.stderr)


class JsonEmitter:
    """JSON emitter: serialize data to stdout."""

    def emit(self, data: Any) -> None:
        """Write JSON to stdout."""
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")


def render_stacks(
    stacks: dict[str, dict],
    zoom: Zoom,
    width: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render all stacks at the given zoom level.

    Args:
        stacks: {stack_name: payload} where payload has containers, healthy, total
        zoom: MINIMAL=one-liner, SUMMARY=tree, DETAILED/FULL=bordered tree
        width: Available terminal width
        theme: Theme instance

    Returns:
        Block ready for print_block()
    """
    if not stacks:
        return Block.text("No data", Style(dim=True), width=width)

    return status_view(stacks, zoom, width, theme)
