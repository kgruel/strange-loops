"""hlab — homelab monitoring.

Usage:
    uv run hlab                        # show help
    uv run hlab status                 # stack container status
    uv run hlab alerts                 # Prometheus alert status
    uv run hlab logs <stack>           # stream docker compose logs
    uv run hlab media audit            # scan for corrupt media files
    uv run hlab media fix              # fix corrupt media files
    uv run hlab sync uptime-kuma       # sync Uptime Kuma monitors

Common flags:
    -q, --quiet     Minimal output (one-liner)
    -v              Detailed output
    -vv             Full detail
    -i              Interactive TUI (where supported)
    --json          JSON output
    --plain         No ANSI codes
"""

from __future__ import annotations

import asyncio
import json as json_module
import sys
from argparse import ArgumentParser
from collections.abc import Callable
from typing import Any

from painted import Block
from painted.fidelity import (
    CliContext,
    OutputMode,
    Format,
    add_cli_args,
    parse_zoom,
    parse_mode,
    parse_format,
    detect_context,
)
from painted.core.writer import print_block

from .theme import DEFAULT_THEME


def _run_command(
    args,
    render_fn: Callable[[CliContext, Any], Block],
    fetch_fn: Callable[[], Any],
    *,
    to_json: Callable[[Any], Any] | None = None,
) -> int:
    """Generic command runner for fetch-then-render commands."""
    zoom = parse_zoom(args)
    mode = parse_mode(args)
    fmt = parse_format(args)

    # JSON short-circuits — data export, not rendering
    if fmt == Format.JSON:
        data = fetch_fn()
        output = to_json(data) if to_json else data
        print(json_module.dumps(output, default=str))
        return 0

    force_plain = fmt == Format.PLAIN
    if force_plain and mode == OutputMode.AUTO:
        mode = OutputMode.STATIC

    ctx = detect_context(zoom, mode, force_plain=force_plain)

    data = fetch_fn()
    block = render_fn(ctx, data)
    print_block(block, use_ansi=ctx.use_ansi)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for hlab CLI."""
    if argv is None:
        argv = sys.argv[1:]

    parser = ArgumentParser(
        prog="hlab",
        description="Homelab monitoring and management",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Status command (default)
    status_parser = subparsers.add_parser("status", help="Stack container status")
    status_parser.add_argument("stack", nargs="?", default=None, help="Filter to a single stack (e.g., media, infra)")
    status_parser.add_argument("--stats", "-s", action="store_true", help="Include container CPU/memory stats")
    status_parser.add_argument("--logs", "-l", action="store_true", help="Include recent logs for unhealthy containers")
    add_cli_args(status_parser)

    # Alerts command
    alerts_parser = subparsers.add_parser("alerts", help="Prometheus alert status")
    add_cli_args(alerts_parser)
    from .commands.alerts import add_args as alerts_add_args
    alerts_add_args(alerts_parser)

    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Stream docker compose logs")
    add_cli_args(logs_parser)
    from .commands.logs import add_args as logs_add_args
    logs_add_args(logs_parser)

    # Media commands (subparser group)
    media_parser = subparsers.add_parser("media", help="Media library commands")
    media_subparsers = media_parser.add_subparsers(dest="media_command", help="Media command")

    # media audit
    media_audit_parser = media_subparsers.add_parser("audit", help="Scan for corrupt media files")
    add_cli_args(media_audit_parser)
    from .commands.media_audit import add_args as media_audit_add_args
    media_audit_add_args(media_audit_parser)

    # media fix
    media_fix_parser = media_subparsers.add_parser("fix", help="Fix corrupt media files")
    add_cli_args(media_fix_parser)
    from .commands.media_fix import add_args as media_fix_add_args
    media_fix_add_args(media_fix_parser)

    # Sync commands (subparser group)
    sync_parser = subparsers.add_parser("sync", help="Synchronization commands")
    sync_subparsers = sync_parser.add_subparsers(dest="sync_command", help="Sync command")

    # sync uptime-kuma
    sync_uk_parser = sync_subparsers.add_parser("uptime-kuma", help="Sync Uptime Kuma monitors")
    add_cli_args(sync_uk_parser)
    from .commands.sync_uptime_kuma import add_args as sync_uk_add_args
    sync_uk_add_args(sync_uk_parser)

    # Parse args
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # Route to appropriate command
    try:
        if args.command == "status":
            from .commands.status import make_fetcher
            from .lenses.status import status_view

            mode = parse_mode(args)
            if mode == OutputMode.INTERACTIVE:
                from .tui import HlabApp
                asyncio.run(HlabApp().run())
                return 0

            fetch = make_fetcher(args)
            render = lambda ctx, data: status_view(data, ctx.zoom, ctx.width, DEFAULT_THEME)
            return _run_command(args, render, fetch)

        elif args.command == "alerts":
            from .commands.alerts import make_fetcher, to_json
            from .lenses.alerts import alerts_view

            fetch = make_fetcher(args)
            render = lambda ctx, data: alerts_view(data, ctx.zoom, ctx.width, DEFAULT_THEME)
            return _run_command(args, render, fetch, to_json=to_json)

        elif args.command == "logs":
            from .commands.logs import run_logs
            zoom = parse_zoom(args)
            mode = parse_mode(args)
            fmt = parse_format(args)
            ctx = detect_context(zoom, mode, force_plain=(fmt == Format.PLAIN))
            return run_logs(ctx, args)

        elif args.command == "media":
            if args.media_command == "audit":
                from .commands.media_audit import make_fetcher, to_json
                from .lenses.media import media_audit_view

                fetch = make_fetcher(args)
                render = lambda ctx, data: media_audit_view(data, ctx.zoom, ctx.width, DEFAULT_THEME)
                return _run_command(args, render, fetch, to_json=to_json)

            elif args.media_command == "fix":
                from .commands.media_fix import run_fix
                zoom = parse_zoom(args)
                mode = parse_mode(args)
                fmt = parse_format(args)
                ctx = detect_context(zoom, mode, force_plain=(fmt == Format.PLAIN))
                return run_fix(ctx, args)

            else:
                media_parser.print_help()
                return 1

        elif args.command == "sync":
            if args.sync_command == "uptime-kuma":
                from .commands.sync_uptime_kuma import run_sync
                zoom = parse_zoom(args)
                mode = parse_mode(args)
                fmt = parse_format(args)
                ctx = detect_context(zoom, mode, force_plain=(fmt == Format.PLAIN))
                return run_sync(ctx, args)

            else:
                sync_parser.print_help()
                return 1

        else:
            parser.print_help()
            return 1

    except KeyboardInterrupt:
        return 130
