"""AppRunner: app-level command routing through painted.

Mirrors the CliRunner + run_cli pattern one level up. CliRunner handles
a single command with zoom/mode/format; AppRunner routes between multiple
commands and renders top-level help through painted.

Usage:
    from painted.app_runner import run_app, AppCommand

    commands = [
        AppCommand("status", "Show store status", _run_status),
        AppCommand("log", "Show recent facts", _run_log),
    ]
    run_app(sys.argv[1:], commands, prog="myapp")
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass

from .fidelity import (
    Format,
    HelpData,
    HelpFlag,
    HelpGroup,
    Zoom,
    render_help,
    scan_help_args,
)


@dataclass(frozen=True)
class AppCommand:
    """A routable command with name, description, and handler.

    The handler receives argv (remaining args after command name) and
    returns an exit code.
    """

    name: str  # "status"
    description: str  # "Show store status"
    handler: Callable[[list[str]], int]  # receives argv[1:], returns exit code
    detail: str | None = None  # shown at DETAILED+ zoom, e.g. usage hint


@dataclass(frozen=True)
class AppRunner:
    """App-level command router with painted help rendering.

    Routes argv[0] to the matching AppCommand handler. When no args
    or --help/-h is given, renders help through painted (zoom-aware).
    """

    commands: tuple[AppCommand, ...]
    prog: str | None = None
    description: str | None = None

    def run(self, argv: list[str]) -> int:
        """Route argv to command handler, or show help."""
        # No args → painted help
        if not argv:
            return self._handle_help([])

        name = argv[0]

        # Command name first → dispatch (command handles its own --help)
        for cmd in self.commands:
            if cmd.name == name:
                return cmd.handler(argv[1:])

        # No command matched — check for --help/-h (top-level help)
        if "-h" in argv or "--help" in argv:
            return self._handle_help(argv)

        # Unknown command → error + help to stderr
        from .block import Block
        from .cell import Style
        from .writer import print_block

        try:
            from .palette import current_palette

            error_style = current_palette().error
        except Exception:
            error_style = Style(fg="red")

        error_block = Block.text(f"Unknown command: {name}", error_style)
        print_block(error_block, sys.stderr, use_ansi=True)

        # Show help to stderr
        help_data = self._build_help_data()
        width = shutil.get_terminal_size().columns
        help_block = render_help(help_data, Zoom.SUMMARY, width, use_ansi=True, show_rules=False)
        print_block(help_block, sys.stderr, use_ansi=True)

        return 1

    def _handle_help(self, args: list[str]) -> int:
        """Render zoom-aware help and return 0."""
        from .writer import print_block

        zoom, fmt = scan_help_args(args)
        help_data = self._build_help_data()

        if fmt == Format.JSON:
            from dataclasses import asdict

            print(json.dumps(asdict(help_data), default=str))
            return 0

        use_ansi = fmt != Format.PLAIN
        if fmt == Format.AUTO:
            use_ansi = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

        width = shutil.get_terminal_size().columns
        block = render_help(help_data, zoom, width, use_ansi, show_rules=False)
        print_block(block, use_ansi=use_ansi)
        return 0

    def _build_help_data(self) -> HelpData:
        """Build HelpData from commands."""
        # Commands as primary group
        command_flags = tuple(
            HelpFlag(short=None, long=cmd.name, description=cmd.description, detail=cmd.detail)
            for cmd in self.commands
        )
        commands_group = HelpGroup(name="Commands", flags=command_flags)

        # Common flags as secondary groups — these work on display commands
        zoom_group = HelpGroup(
            name="Zoom",
            hint="(what to show)",
            detail="Controls how much detail is rendered. Stackable: -v for detailed, -vv for full.",
            flags=(
                HelpFlag("-q", "--quiet", "Minimal output"),
                HelpFlag("-v", "--verbose", "Detailed (-v) or full (-vv)"),
            ),
            secondary=True,
        )

        format_group = HelpGroup(
            name="Format",
            hint="(serialization)",
            detail="Output serialization. ANSI is default for TTY, PLAIN for pipes.",
            flags=(
                HelpFlag(None, "--json", "JSON output", detail="Implies --static."),
                HelpFlag(None, "--plain", "Plain text, no ANSI codes"),
            ),
            secondary=True,
        )

        help_group = HelpGroup(
            name="Help",
            flags=(HelpFlag("-h", "--help", "Show this help", detail="Add -v for more detail."),),
            secondary=True,
        )

        return HelpData(
            prog=self.prog,
            description=self.description,
            groups=(commands_group, zoom_group, format_group, help_group),
        )


def run_app(
    argv: list[str],
    commands: list[AppCommand] | tuple[AppCommand, ...],
    *,
    prog: str | None = None,
    description: str | None = None,
) -> int:
    """Run an app with command routing and painted help.

    Convenience function that creates an AppRunner and runs it.

    Args:
        argv: Command-line arguments (sys.argv[1:])
        commands: Available commands
        prog: Program name for help
        description: Program description for help

    Returns:
        Exit code (0 for success)
    """
    return AppRunner(
        commands=tuple(commands),
        prog=prog,
        description=description,
    ).run(argv)
