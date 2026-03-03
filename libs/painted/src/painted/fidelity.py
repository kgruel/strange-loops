"""Fidelity: zoom, output mode, and format handling for CLI tools.

Separates three orthogonal concerns:
- Zoom (detail level): -v/-q flags, stackable
- Output Mode (experience): auto-detected or explicit -i/--static/--live
- Format (serialization): --json/--plain or auto-detected

Usage:
    from painted.fidelity import run_cli, CliContext, Zoom

    def render(ctx: CliContext, data: dict) -> Block:
        return status_view(data, zoom=ctx.zoom, width=ctx.width)

    run_cli(sys.argv[1:], render=render, fetch=fetch_data)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import Enum, IntEnum
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
# Help Data Types
# =============================================================================


@dataclass(frozen=True)
class HelpFlag:
    """A single CLI flag for help rendering."""

    short: str | None  # "-v"
    long: str | None  # "--verbose"
    description: str  # shown at all zoom levels
    detail: str | None = None  # shown at DETAILED+


@dataclass(frozen=True)
class HelpGroup:
    """A group of related flags."""

    name: str  # "Zoom"
    hint: str | None = None  # "(what to show)" — after name at SUMMARY+
    detail: str | None = None  # longer description at DETAILED+
    flags: tuple[HelpFlag, ...] = ()
    min_zoom: Zoom = Zoom.MINIMAL  # zoom level where this group first appears (compact)


@dataclass(frozen=True)
class HelpData:
    """Complete help information for a CLI tool."""

    prog: str | None
    description: str | None
    groups: tuple[HelpGroup, ...]


@dataclass(frozen=True)
class HelpArg:
    """Describes a command argument for help rendering.

    For commands that pre-parse their own args before calling run_cli,
    use this to describe those args so they appear in --help output.
    """

    name: str  # "--since" or "vertex"
    description: str = ""
    default: str | None = None
    positional: bool = False


# =============================================================================
# Resolution Logic
# =============================================================================


def resolve_mode(
    requested: OutputMode,
    is_tty: bool,
    is_pipe: bool,
    default_mode: OutputMode = OutputMode.LIVE,
) -> OutputMode:
    """Resolve AUTO to concrete mode.

    When requested is AUTO, pipes always get STATIC. TTYs get default_mode
    (LIVE by default, but callers can override to STATIC for run-and-exit
    commands that support --live as opt-in).
    """
    if requested != OutputMode.AUTO:
        return requested
    if is_pipe:
        return OutputMode.STATIC
    if is_tty:
        return default_mode
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
    default_mode: OutputMode = OutputMode.LIVE,
) -> CliContext:
    """Detect and resolve full runtime context."""
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    is_pipe = not is_tty

    resolved_mode = resolve_mode(mode, is_tty, is_pipe, default_mode)
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


def setup_defaults(ctx: CliContext) -> None:
    """Set ambient IconSet from resolved runtime context.

    Palette is never auto-set — it's a deliberate aesthetic choice.
    MONO_PALETTE exists for explicit opt-in (e.g., low-vision, e-ink),
    not as a Format.PLAIN default.
    """
    from .icon_set import ASCII_ICONS, use_icons

    if ctx.format == Format.PLAIN:
        use_icons(ASCII_ICONS)


# =============================================================================
# Help Rendering
# =============================================================================


def help_args_to_flags(help_args: list[HelpArg]) -> tuple[HelpFlag, ...]:
    """Convert HelpArgs to HelpFlags for rendering."""
    flags: list[HelpFlag] = []
    for arg in help_args:
        desc = arg.description
        if arg.default is not None:
            suffix = f"(default: {arg.default})"
            desc = f"{desc} {suffix}" if desc else suffix
        flags.append(HelpFlag(short=None, long=arg.name, description=desc))
    return tuple(flags)


def _extract_add_args_flags(
    add_args_fn: Callable[[argparse.ArgumentParser], None],
) -> tuple[HelpFlag, ...]:
    """Extract help flags from an add_args callback by introspecting a temp parser."""
    parser = argparse.ArgumentParser(add_help=False)
    add_args_fn(parser)
    flags: list[HelpFlag] = []
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if action.help is argparse.SUPPRESS:
            continue
        if not action.option_strings:  # positional
            desc = action.help or ""
            flags.append(HelpFlag(short=None, long=action.dest, description=desc))
        else:
            short = None
            long = None
            for s in action.option_strings:
                if s.startswith("--"):
                    long = s
                elif s.startswith("-"):
                    short = s
            desc = action.help or ""
            flags.append(HelpFlag(short=short, long=long, description=desc))
    return tuple(flags)


def _build_help_data(runner: CliRunner[T]) -> HelpData:
    """Construct help data from a CliRunner's config."""
    # Command args (primary) — from help_args and/or add_args
    command_flags: list[HelpFlag] = []
    if runner.help_args is not None:
        command_flags.extend(help_args_to_flags(runner.help_args))
    if runner.add_args is not None:
        command_flags.extend(_extract_add_args_flags(runner.add_args))

    has_command_args = len(command_flags) > 0
    framework_zoom = Zoom.SUMMARY if has_command_args else Zoom.MINIMAL

    # Zoom group — always present
    zoom_flags = (
        HelpFlag("-q", "--quiet", "Minimal output", detail="Also implies --static (no animation)."),
        HelpFlag("-v", "--verbose", "Detailed (-v) or full (-vv)"),
    )
    zoom_group = HelpGroup(
        name="Zoom",
        hint="(what to show)",
        detail="Controls how much detail is rendered. Stackable: -v for detailed, -vv for full.",
        flags=zoom_flags,
        min_zoom=framework_zoom,
    )

    # Mode group — filtered by capability (same logic as add_cli_args)
    has_live = runner.fetch_stream is not None
    has_interactive = runner.handlers is not None and OutputMode.INTERACTIVE in runner.handlers
    mode_flags: list[HelpFlag] = []
    if has_interactive:
        mode_flags.append(HelpFlag("-i", "--interactive", "Interactive TUI"))
    mode_flags.append(
        HelpFlag(None, "--static", "Static output, no animation"),
    )
    if has_live:
        mode_flags.append(
            HelpFlag(None, "--live", "Live output with in-place updates"),
        )

    mode_group: HelpGroup | None = None
    if has_live or has_interactive:
        mode_group = HelpGroup(
            name="Mode",
            hint="(how to deliver)",
            detail="Delivery mechanism. AUTO selects LIVE for TTY, STATIC for pipes.",
            flags=tuple(mode_flags),
            min_zoom=framework_zoom,
        )

    # Format group — always present
    format_flags = (
        HelpFlag(None, "--json", "JSON output", detail="Implies --static."),
        HelpFlag(
            None, "--plain", "Plain text, no ANSI codes", detail="Implies --static when piped."
        ),
    )
    format_group = HelpGroup(
        name="Format",
        hint="(serialization)",
        detail="Output serialization. ANSI is default for TTY, PLAIN for pipes.",
        flags=format_flags,
        min_zoom=framework_zoom,
    )

    # Help flag itself
    help_flags = (HelpFlag("-h", "--help", "Show this help", detail="Add -v for more detail."),)
    help_group = HelpGroup(name="Help", flags=help_flags, min_zoom=framework_zoom)

    groups: list[HelpGroup] = []
    if command_flags:
        groups.append(HelpGroup(name="", flags=tuple(command_flags)))
    groups.append(zoom_group)
    if mode_group is not None:
        groups.append(mode_group)
    groups.append(format_group)
    groups.append(help_group)

    return HelpData(
        prog=runner.prog,
        description=runner.description,
        groups=tuple(groups),
    )


def render_help(data: HelpData, zoom: Zoom, width: int, use_ansi: bool) -> Block:
    """Render help data as a composed Block.

    Each group has a min_zoom that controls when it appears and how much
    detail it shows. The effective zoom for a group is:

        eff = global_zoom - group.min_zoom

    Three rendering states:
      eff < 0  → hidden
      eff == 0 → compact (flag names only, single dim line)
      eff == 1 → expanded (flag columns with descriptions)
      eff >= 2 → expanded + group.detail + flag.detail
    """
    from .block import Block
    from .cell import Style
    from .compose import join_vertical

    rows: list[Block] = []
    dim = Style(dim=True) if use_ansi else Style()
    bold = Style(bold=True) if use_ansi else Style()
    normal = Style()

    # Header: prog + description
    if data.prog or data.description:
        parts: list[str] = []
        if data.prog:
            parts.append(data.prog)
        desc = data.description
        if desc:
            first_line = desc.strip().split("\n")[0].strip()
            parts.append(first_line)
        header = " — ".join(parts) if len(parts) > 1 else parts[0]
        rows.append(Block.text(header, bold))
        rows.append(Block.text("", normal))

    # Flag column width: find widest flag string across visible groups
    flag_strs: list[str] = []
    for group in data.groups:
        for flag in group.flags:
            parts_f: list[str] = []
            if flag.short:
                parts_f.append(flag.short)
            if flag.long:
                parts_f.append(flag.long)
            flag_strs.append(", ".join(parts_f))
    col_width = max((len(s) for s in flag_strs), default=10) + 2  # padding

    def _render_expanded(
        group: HelpGroup, style: Style, header_style: Style, show_detail: bool
    ) -> None:
        """Render a group in expanded form (eff >= 1)."""
        if group.name:
            group_label = group.name
            if group.hint:
                group_label += f" {group.hint}"
            rows.append(Block.text(group_label, header_style))

        if show_detail and group.detail:
            rows.append(Block.text(f"  {group.detail}", dim))

        for flag in group.flags:
            parts_f: list[str] = []
            if flag.short:
                parts_f.append(flag.short)
            if flag.long:
                parts_f.append(flag.long)
            flag_str = ", ".join(parts_f)
            line = f"  {flag_str:<{col_width}}{flag.description}"
            rows.append(Block.text(line, style))

            if show_detail and flag.detail:
                detail_indent = "  " + " " * col_width
                rows.append(Block.text(f"{detail_indent}{flag.detail}", dim))

        rows.append(Block.text("", normal))

    # Collect consecutive compact groups, flush them as a single dim line
    compact_groups: list[HelpGroup] = []

    def _flush_compact() -> None:
        if not compact_groups:
            return
        flag_names: list[str] = []
        for g in compact_groups:
            for flag in g.flags:
                flag_names.append(flag.short or flag.long or "")
        rows.append(Block.text("  " + "  ".join(flag_names), dim))
        rows.append(Block.text("", normal))
        compact_groups.clear()

    for group in data.groups:
        eff = zoom.value - group.min_zoom.value
        if eff < 0:
            continue  # hidden

        if eff == 0:
            compact_groups.append(group)
        else:
            _flush_compact()
            # Dim styling when group is just one step above compact
            if eff == 1:
                dim_bold = Style(bold=True, dim=True) if use_ansi else normal
                _render_expanded(group, dim, dim_bold, show_detail=False)
            else:
                _render_expanded(group, normal, bold, show_detail=True)

    _flush_compact()

    return join_vertical(*rows)


def scan_help_args(args: list[str]) -> tuple[Zoom, Format]:
    """Quick-scan args for zoom and format when --help is present."""
    zoom = Zoom.SUMMARY
    fmt = Format.AUTO

    v_count = 0
    for arg in args:
        if arg == "-h" or arg == "--help":
            continue
        if arg == "-q" or arg == "--quiet":
            zoom = Zoom.MINIMAL
        elif arg.startswith("-v"):
            # Count v's: -v, -vv, -vvv
            if arg.startswith("--verbose"):
                v_count += 1
            else:
                v_count += len(arg) - 1  # strip the dash
        elif arg == "--json":
            fmt = Format.JSON
        elif arg == "--plain":
            fmt = Format.PLAIN

    if zoom != Zoom.MINIMAL and v_count > 0:
        zoom = Zoom.FULL if v_count >= 2 else Zoom.DETAILED

    return zoom, fmt


# =============================================================================
# Argument Parsing
# =============================================================================


def add_cli_args(
    parser: argparse.ArgumentParser,
    *,
    modes: set[OutputMode] | None = None,
) -> None:
    """Add standard zoom/mode/format arguments.

    Args:
        parser: ArgumentParser to add arguments to.
        modes: Supported output modes. When provided, only adds flags for
            modes in the set. When None, adds all flags (backward-compatible).
    """
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

    # Mode group — only add flags for supported modes
    has_live = modes is None or OutputMode.LIVE in modes
    has_interactive = modes is None or OutputMode.INTERACTIVE in modes
    if has_live or has_interactive:
        mode_group = parser.add_mutually_exclusive_group()
        if has_interactive:
            mode_group.add_argument(
                "-i",
                "--interactive",
                action="store_true",
                help="Interactive TUI mode",
            )
        # --static is the "force no animation" escape hatch
        mode_group.add_argument(
            "--static",
            action="store_true",
            help="Static output, no animation",
        )
        if has_live:
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
    render: Callable[[CliContext, T], Block]

    # Required: how to fetch state (sync)
    fetch: Callable[[], T]

    # Optional: streaming fetch for live mode
    fetch_stream: Callable[[], AsyncIterator[T]] | None = None

    # Optional: custom handlers for specific modes
    handlers: dict[OutputMode, Callable[[CliContext], R]] | None = None

    # Defaults
    default_zoom: Zoom = Zoom.SUMMARY
    default_mode: OutputMode = OutputMode.LIVE

    # Optional: description for help
    description: str | None = None

    # Optional: program name
    prog: str | None = None

    # Optional: callback to add custom args
    add_args: Callable[[argparse.ArgumentParser], None] | None = None

    # Optional: describe pre-parsed args for help rendering
    help_args: list[HelpArg] | None = None

    def run(self, args: list[str]) -> int:
        """Parse args, resolve context, dispatch."""
        # Intercept --help before argparse
        if "-h" in args or "--help" in args:
            return self._handle_help(args)

        parser = argparse.ArgumentParser(
            description=self.description,
            prog=self.prog,
            add_help=False,
        )
        # Re-add -h/--help so argparse still recognizes it for error messages
        parser.add_argument("-h", "--help", action="help", help=argparse.SUPPRESS)

        # Infer supported modes from config
        modes: set[OutputMode] = {OutputMode.STATIC}
        if self.fetch_stream is not None:
            modes.add(OutputMode.LIVE)
        if self.handlers and OutputMode.INTERACTIVE in self.handlers:
            modes.add(OutputMode.INTERACTIVE)

        add_cli_args(parser, modes=modes)

        if self.add_args is not None:
            self.add_args(parser)

        parsed = parser.parse_args(args)

        zoom = parse_zoom(parsed, self.default_zoom)
        mode = parse_mode(parsed)
        fmt = parse_format(parsed)

        # Non-animated formats and minimal zoom imply static mode
        if mode == OutputMode.AUTO and (fmt in (Format.JSON, Format.PLAIN) or zoom == Zoom.MINIMAL):
            mode = OutputMode.STATIC

        ctx = detect_context(zoom, mode, fmt, self.default_mode)

        return self._dispatch(ctx)

    def _handle_help(self, args: list[str]) -> int:
        """Render zoom-aware help and return 0."""
        zoom, fmt = scan_help_args(args)
        help_data = _build_help_data(self)

        if fmt == Format.JSON:
            print(json.dumps(asdict(help_data), default=str))
            return 0

        use_ansi = fmt != Format.PLAIN
        if fmt == Format.AUTO:
            use_ansi = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

        width = shutil.get_terminal_size().columns
        block = render_help(help_data, zoom, width, use_ansi)

        from .writer import print_block

        print_block(block, use_ansi=use_ansi)
        return 0

    def _dispatch(self, ctx: CliContext) -> int:
        """Dispatch to appropriate output mechanism."""
        setup_defaults(ctx)

        # Check for custom handler
        if self.handlers and ctx.mode in self.handlers:
            result = self.handlers[ctx.mode](ctx)
            return result if isinstance(result, int) else 0

        # JSON format special case
        if ctx.format == Format.JSON:
            try:
                state = self.fetch()
            except Exception as exc:
                message = self._exception_message(exc)
                print(json.dumps({"error": message}))
                return 1
            try:
                data = asdict(state)  # type: ignore[arg-type]  # T may be dataclass
            except TypeError:
                data = state
            print(json.dumps(data, default=str))
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

        try:
            state = self.fetch()
        except Exception as exc:
            block = self._fetch_error_block(ctx, exc)
            print_block(block, use_ansi=(ctx.format == Format.ANSI))
            return 1

        try:
            block = self.render(ctx, state)
        except Exception as exc:
            block = self._render_error_block(ctx, exc)
            print_block(block, use_ansi=(ctx.format == Format.ANSI))
            return 2

        print_block(block, use_ansi=(ctx.format == Format.ANSI))
        return 0

    def _run_live(self, ctx: CliContext) -> int:
        """Run with InPlaceRenderer."""
        import asyncio

        from .inplace import InPlaceRenderer
        from .writer import print_block

        if self.fetch_stream is not None:
            # Streaming mode: update as data arrives
            async def stream() -> int:
                with InPlaceRenderer() as renderer:
                    try:
                        async for state in self.fetch_stream():  # type: ignore[misc]
                            try:
                                block = self.render(ctx, state)
                            except Exception as exc:
                                renderer.render(self._render_error_block(ctx, exc))
                                renderer.finalize()
                                return 2
                            renderer.render(block)
                    except (KeyboardInterrupt, asyncio.CancelledError):
                        renderer.finalize()
                        return 0
                    except Exception as exc:
                        renderer.render(self._fetch_error_block(ctx, exc))
                        renderer.finalize()
                        return 1
                    # Keep final output visible
                    renderer.finalize()
                    return 0

            try:
                return asyncio.run(stream())
            except KeyboardInterrupt:
                return 0

        # No streaming: just fetch and render
        try:
            state = self.fetch()
        except Exception as exc:
            block = self._fetch_error_block(ctx, exc)
            print_block(block, use_ansi=(ctx.format == Format.ANSI))
            return 1

        try:
            block = self.render(ctx, state)
        except Exception as exc:
            block = self._render_error_block(ctx, exc)
            print_block(block, use_ansi=(ctx.format == Format.ANSI))
            return 2

        print_block(block, use_ansi=(ctx.format == Format.ANSI))
        return 0

    @staticmethod
    def _exception_message(exc: Exception) -> str:
        message = str(exc).strip()
        return message or type(exc).__name__

    @staticmethod
    def _fetch_error_block(ctx: CliContext, exc: Exception) -> Block:
        from .block import Block, Wrap
        from .cell import Style

        try:
            from .palette import current_palette

            style = current_palette().error
        except Exception:
            style = Style(fg="red")

        message = CliRunner._exception_message(exc)
        width = max(1, ctx.width)
        return Block.text(message.replace("\n", " "), style, width=width, wrap=Wrap.WORD)

    @staticmethod
    def _render_error_block(ctx: CliContext, exc: Exception) -> Block:
        from .block import Block, Wrap
        from .cell import Style

        message = str(exc).strip()
        if message:
            text = f"{type(exc).__name__}: {message}"
        else:
            text = type(exc).__name__

        width = max(1, ctx.width)
        return Block.text(text.replace("\n", " "), Style(), width=width, wrap=Wrap.WORD)


def run_cli(
    args: list[str],
    render: Callable[[CliContext, T], Block],
    fetch: Callable[[], T],
    *,
    fetch_stream: Callable[[], AsyncIterator[T]] | None = None,
    handlers: dict[OutputMode, Callable[[CliContext], R]] | None = None,
    default_zoom: Zoom = Zoom.SUMMARY,
    default_mode: OutputMode = OutputMode.LIVE,
    description: str | None = None,
    prog: str | None = None,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
    help_args: list[HelpArg] | None = None,
) -> int:
    """Run a CLI tool with zoom/mode/format handling.

    Args:
        args: Command-line arguments (sys.argv[1:])
        render: Function to render state to Block
        fetch: Function to fetch state (sync)
        fetch_stream: Optional async iterator for streaming updates
        handlers: Custom handlers for specific output modes
        default_zoom: Default zoom level (SUMMARY)
        default_mode: Default mode for TTY when AUTO (LIVE)
        description: Help text description
        prog: Program name
        add_args: Callback to add custom arguments
        help_args: Describe pre-parsed args for help rendering

    Returns:
        Exit code (0 for success)
    """
    return CliRunner(
        render=render,
        fetch=fetch,
        fetch_stream=fetch_stream,
        handlers=handlers,  # type: ignore[arg-type]
        default_zoom=default_zoom,
        default_mode=default_mode,
        description=description,
        prog=prog,
        add_args=add_args,
        help_args=help_args,
    ).run(args)
