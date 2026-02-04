"""Emitters — cells-based output for hlab.

Output discipline: UI→stderr, result→stdout
All rendering uses cells (no Rich).
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, TYPE_CHECKING

from cells import Block, Style, Zoom, print_block

from .lenses import status_view, status_view_with_pending, render_plain, PendingState
from .theme import DEFAULT_THEME, Theme

if TYPE_CHECKING:
    from typing import AsyncIterator
    from vertex import Tick


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


class LiveCliEmitter:
    """CLI emitter with live spinner updates during fetch.

    Shows spinners for expected stacks, updates display as each arrives.
    Uses ANSI cursor control for smooth redraw.
    """

    def __init__(
        self,
        zoom: Zoom,
        expected_stacks: list[str],
        *,
        width: int | None = None,
        theme: Theme = DEFAULT_THEME,
    ) -> None:
        self._zoom = zoom
        self._expected = frozenset(expected_stacks)
        self._received: dict[str, dict] = {}
        self._pending = PendingState(pending=self._expected)
        self._width = width or _terminal_width()
        self._theme = theme
        self._last_height = 0

    async def run(self, tick_stream: "AsyncIterator[Tick]") -> dict[str, dict]:
        """Stream ticks, updating display as each arrives.

        Returns the final stacks dict after all expected stacks received.
        """
        if not _is_tty():
            # Non-TTY: just collect and print at the end
            async for tick in tick_stream:
                self._received[tick.name] = tick.payload
            text = render_plain(self._received, self._theme)
            sys.stderr.write(text + "\n")
            return self._received

        # TTY: live updates with spinners
        sys.stderr.write("\033[?25l")  # hide cursor
        try:
            while self._pending.pending:
                self._render()
                try:
                    tick = await asyncio.wait_for(
                        tick_stream.__anext__(),
                        timeout=0.1,
                    )
                    self._received[tick.name] = tick.payload
                    # Remove from pending
                    self._pending = PendingState(
                        pending=self._pending.pending - {tick.name},
                        spinner_frame=self._pending.spinner_frame,
                    )
                except asyncio.TimeoutError:
                    # Advance spinner
                    self._pending = self._pending.tick()
                except StopAsyncIteration:
                    break

            # Final render
            self._render()
            sys.stderr.write("\n")  # newline after final output
        finally:
            sys.stderr.write("\033[?25h")  # show cursor

        return self._received

    def _render(self) -> None:
        """Render current state to stderr with ANSI redraw."""
        # Move cursor up to overwrite previous output
        if self._last_height > 0:
            sys.stderr.write(f"\033[{self._last_height}A")
            sys.stderr.write("\033[J")  # clear from cursor to end

        # Render with pending state
        block = status_view_with_pending(
            self._received,
            self._pending,
            self._zoom,
            self._width,
            self._theme,
        )
        print_block(block, stream=sys.stderr)
        self._last_height = block.height
