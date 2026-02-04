"""Fidelity: zoom, output mode, and format handling for CLI tools.

Separates three orthogonal concerns:
- Zoom (detail level): -v/-q flags, stackable
- Output Mode (experience): auto-detected or explicit -i/--static/--live
- Format (serialization): --json/--plain or auto-detected

Usage:
    from cells.fidelity import run_cli, CliContext, Zoom

    def render(ctx: CliContext, data: dict) -> Block:
        return status_view(data, zoom=ctx.zoom, width=ctx.width)

    run_cli(sys.argv[1:], render=render, fetch=fetch_data)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import TYPE_CHECKING, Callable, Generic, TypeVar

if TYPE_CHECKING:
    from typing import AsyncIterator

    from .block import Block

T = TypeVar("T")  # State type
R = TypeVar("R")  # Return type


# =============================================================================
# Core Types
# =============================================================================


class Zoom(IntEnum):
    """Detail level for rendering."""

    MINIMAL = 0  # One-liner, counts only
    SUMMARY = 1  # Key information, tree structure
    DETAILED = 2  # Everything visible, nested expansion
    FULL = 3  # All fields, full depth


class OutputMode(Enum):
    """Delivery mechanism."""

    AUTO = "auto"  # Detect from TTY/pipe
    STATIC = "static"  # print_block, scrolls away
    LIVE = "live"  # InPlaceRenderer, cursor control
    INTERACTIVE = "interactive"  # Surface, alt screen


class Format(Enum):
    """Serialization format."""

    AUTO = "auto"  # Detect from TTY
    ANSI = "ansi"  # Styled terminal output
    PLAIN = "plain"  # No escape codes
    JSON = "json"  # Machine-readable


@dataclass(frozen=True)
class CliContext:
    """Resolved runtime context."""

    zoom: Zoom
    mode: OutputMode  # Resolved (never AUTO)
    format: Format  # Resolved (never AUTO)
    is_tty: bool
    width: int
    height: int


# =============================================================================
# Resolution Logic
# =============================================================================


def resolve_mode(requested: OutputMode, is_tty: bool, is_pipe: bool) -> OutputMode:
    """Resolve AUTO to concrete mode."""
    if requested != OutputMode.AUTO:
        return requested
    if is_pipe:
        return OutputMode.STATIC
    if is_tty:
        return OutputMode.LIVE
    return OutputMode.STATIC


def resolve_format(requested: Format, is_tty: bool, mode: OutputMode) -> Format:
    """Resolve AUTO to concrete format."""
    if requested != Format.AUTO:
        return requested
    if mode == OutputMode.INTERACTIVE:
        return Format.ANSI
    if is_tty:
        return Format.ANSI
    return Format.PLAIN


def detect_context(
    zoom: Zoom,
    mode: OutputMode,
    fmt: Format,
) -> CliContext:
    """Detect and resolve full runtime context."""
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    is_pipe = not is_tty

    resolved_mode = resolve_mode(mode, is_tty, is_pipe)
    resolved_format = resolve_format(fmt, is_tty, resolved_mode)

    size = shutil.get_terminal_size()
    return CliContext(
        zoom=zoom,
        mode=resolved_mode,
        format=resolved_format,
        is_tty=is_tty,
        width=size.columns,
        height=size.lines,
    )


# =============================================================================
# Argument Parsing
# =============================================================================


def add_cli_args(parser: argparse.ArgumentParser) -> None:
    """Add standard zoom/mode/format arguments."""
    # Zoom group
    zoom_group = parser.add_mutually_exclusive_group()
    zoom_group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Minimal output (zoom=0)",
    )
    zoom_group.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase detail level (-v=detailed, -vv=full)",
    )

    # Mode group
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive TUI mode",
    )
    mode_group.add_argument(
        "--static",
        action="store_true",
        help="Static output, no animation",
    )
    mode_group.add_argument(
        "--live",
        action="store_true",
        help="Live output with in-place updates",
    )

    # Format
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON output (implies --static)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Plain text, no ANSI codes",
    )


def parse_zoom(args: argparse.Namespace, default: Zoom = Zoom.SUMMARY) -> Zoom:
    """Parse zoom level from args."""
    if getattr(args, "quiet", False):
        return Zoom.MINIMAL
    verbose = getattr(args, "verbose", 0)
    if verbose >= 2:
        return Zoom.FULL
    if verbose == 1:
        return Zoom.DETAILED
    return default


def parse_mode(args: argparse.Namespace) -> OutputMode:
    """Parse output mode from args."""
    if getattr(args, "interactive", False):
        return OutputMode.INTERACTIVE
    if getattr(args, "static", False):
        return OutputMode.STATIC
    if getattr(args, "live", False):
        return OutputMode.LIVE
    return OutputMode.AUTO


def parse_format(args: argparse.Namespace) -> Format:
    """Parse format from args."""
    if getattr(args, "json", False):
        return Format.JSON
    if getattr(args, "plain", False):
        return Format.PLAIN
    return Format.AUTO


# =============================================================================
# CLI Runner
# =============================================================================


@dataclass
class CliRunner(Generic[T]):
    """CLI runner with sensible defaults and explicit overrides."""

    # Required: how to render state to Block
    render: Callable[[CliContext, T], "Block"]

    # Required: how to fetch state (sync)
    fetch: Callable[[], T]

    # Optional: streaming fetch for live mode
    fetch_stream: Callable[[], "AsyncIterator[T]"] | None = None

    # Optional: custom handlers for specific modes
    handlers: dict[OutputMode, Callable[[CliContext], R]] | None = None

    # Defaults
    default_zoom: Zoom = Zoom.SUMMARY

    # Optional: description for help
    description: str | None = None

    # Optional: program name
    prog: str | None = None

    # Optional: callback to add custom args
    add_args: Callable[[argparse.ArgumentParser], None] | None = None

    def run(self, args: list[str]) -> int:
        """Parse args, resolve context, dispatch."""
        parser = argparse.ArgumentParser(
            description=self.description,
            prog=self.prog,
        )
        add_cli_args(parser)

        if self.add_args is not None:
            self.add_args(parser)

        parsed = parser.parse_args(args)

        zoom = parse_zoom(parsed, self.default_zoom)
        mode = parse_mode(parsed)
        fmt = parse_format(parsed)

        # JSON implies static mode
        if fmt == Format.JSON and mode == OutputMode.AUTO:
            mode = OutputMode.STATIC

        ctx = detect_context(zoom, mode, fmt)

        return self._dispatch(ctx)

    def _dispatch(self, ctx: CliContext) -> int:
        """Dispatch to appropriate output mechanism."""
        # Check for custom handler
        if self.handlers and ctx.mode in self.handlers:
            result = self.handlers[ctx.mode](ctx)
            return result if isinstance(result, int) else 0

        # JSON format special case
        if ctx.format == Format.JSON:
            state = self.fetch()
            print(json.dumps(state, default=str))
            return 0

        # Dispatch by mode
        if ctx.mode == OutputMode.STATIC:
            return self._run_static(ctx)

        elif ctx.mode == OutputMode.LIVE:
            return self._run_live(ctx)

        elif ctx.mode == OutputMode.INTERACTIVE:
            # Falls back to LIVE if no custom handler
            return self._run_live(ctx)

        return 0

    def _run_static(self, ctx: CliContext) -> int:
        """Run with static output (print_block)."""
        from .writer import print_block

        state = self.fetch()
        block = self.render(ctx, state)
        print_block(block, use_ansi=(ctx.format == Format.ANSI))
        return 0

    def _run_live(self, ctx: CliContext) -> int:
        """Run with InPlaceRenderer."""
        import asyncio

        from .inplace import InPlaceRenderer

        if self.fetch_stream is not None:
            # Streaming mode: update as data arrives
            async def stream():
                with InPlaceRenderer() as renderer:
                    async for state in self.fetch_stream():
                        block = self.render(ctx, state)
                        renderer.render(block)
                    # Keep final output visible
                    renderer.finalize()

            asyncio.run(stream())
            return 0

        # No streaming: just fetch and render
        with InPlaceRenderer() as renderer:
            state = self.fetch()
            block = self.render(ctx, state)
            renderer.finalize(block)
        return 0


def run_cli(
    args: list[str],
    render: Callable[[CliContext, T], "Block"],
    fetch: Callable[[], T],
    *,
    fetch_stream: Callable[[], "AsyncIterator[T]"] | None = None,
    handlers: dict[OutputMode, Callable[[CliContext], R]] | None = None,
    default_zoom: Zoom = Zoom.SUMMARY,
    description: str | None = None,
    prog: str | None = None,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
) -> int:
    """Run a CLI tool with zoom/mode/format handling.

    Args:
        args: Command-line arguments (sys.argv[1:])
        render: Function to render state to Block
        fetch: Function to fetch state (sync)
        fetch_stream: Optional async iterator for streaming updates
        handlers: Custom handlers for specific output modes
        default_zoom: Default zoom level (SUMMARY)
        description: Help text description
        prog: Program name
        add_args: Callback to add custom arguments

    Returns:
        Exit code (0 for success)
    """
    return CliRunner(
        render=render,
        fetch=fetch,
        fetch_stream=fetch_stream,
        handlers=handlers,
        default_zoom=default_zoom,
        description=description,
        prog=prog,
        add_args=add_args,
    ).run(args)


# =============================================================================
# Backward Compatibility (Deprecated)
# =============================================================================


class Fidelity(IntEnum):
    """Output fidelity levels.

    DEPRECATED: Use Zoom, OutputMode, and Format instead.
    """

    QUIET = 0  # F0: machine-readable, no decoration
    NORMAL = 1  # F1: default terminal output
    VERBOSE = 2  # F2: enhanced output, colors
    FULL = 3  # F3: full TUI or maximum decoration


@dataclass(frozen=True)
class HarnessContext:
    """Resolved runtime context.

    DEPRECATED: Use CliContext instead.
    """

    fidelity: Fidelity
    is_tty: bool
    width: int
    height: int


def fidelity_to_zoom(f: Fidelity) -> Zoom:
    """Convert Fidelity to Zoom.

    DEPRECATED: Migration helper.
    """
    return Zoom(f.value)


def detect_fidelity(args: argparse.Namespace) -> Fidelity:
    """Determine fidelity from parsed args.

    DEPRECATED: Use parse_zoom() instead.
    """
    if getattr(args, "quiet", False):
        return Fidelity.QUIET

    verbose = getattr(args, "verbose", 0)
    if verbose >= 2:
        return Fidelity.FULL
    if verbose == 1:
        return Fidelity.VERBOSE

    return Fidelity.NORMAL


def add_fidelity_args(parser: argparse.ArgumentParser) -> None:
    """Add -q, -f, --quiet, --verbose flags to an ArgumentParser.

    DEPRECATED: Use add_cli_args() instead.
    """
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
    if fidelity in handlers:
        return handlers[fidelity]

    for level in reversed(range(int(fidelity))):
        f = Fidelity(level)
        if f in handlers:
            return handlers[f]

    raise ValueError(
        f"No handler for fidelity {fidelity.name} or lower. "
        f"Available: {[f.name for f in handlers.keys()]}"
    )


def _detect_context_legacy(fidelity: Fidelity | None = None) -> HarnessContext:
    """Detect full context: fidelity, TTY, terminal size.

    DEPRECATED: Use detect_context() instead.
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


def run_with_fidelity(
    args: list[str],
    handlers: dict[Fidelity, Callable[[HarnessContext], T]],
    *,
    parser: argparse.ArgumentParser | None = None,
    description: str | None = None,
) -> T:
    """Parse args, detect context, dispatch to appropriate handler.

    DEPRECATED: Use run_cli() instead.
    """
    if parser is None:
        parser = argparse.ArgumentParser(description=description)
        add_fidelity_args(parser)

    parsed = parser.parse_args(args)
    fidelity = detect_fidelity(parsed)
    ctx = _detect_context_legacy(fidelity)

    handler = _find_handler(ctx.fidelity, handlers)
    return handler(ctx)
