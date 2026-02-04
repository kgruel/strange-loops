"""Logs command — stream docker compose logs from homelab stacks.

Direct implementation (no DSL) since logs are streaming with no natural boundary.
Uses InPlaceRenderer for live output.
"""

from __future__ import annotations

import asyncio
import shlex
import sys
from argparse import ArgumentParser
from collections import deque
from pathlib import Path

from cells import Block, Style, Zoom, join_vertical
from cells.fidelity import CliContext, Format
from cells.inplace import InPlaceRenderer
from cells.writer import print_block

from ..infra import HostConfig, run_ssh_streaming, ssh_base_args
from ..inventory import (
    load_inventory,
    list_stacks,
    stack_name_from_metadata,
    host_config_from_inventory,
    InventoryError,
    DEFAULT_HOSTS_DIR,
    ANSIBLE_INVENTORY_CACHE,
)
from ..lenses.logs import (
    LogLine,
    LogLineConfig,
    RenderState,
    parse_compose_log_line,
    render_log_line,
    render_log_line_plain,
    build_filter,
    LogFilter,
)
from ..theme import DEFAULT_THEME


def add_args(parser: ArgumentParser) -> None:
    """Add logs-specific arguments."""
    parser.add_argument("stack", help="Stack name (e.g., infra, media, dev)")
    parser.add_argument("--service", "-s", default=None, help="Filter to a specific service")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow logs (stream continuously)")
    parser.add_argument("--tail", type=int, default=100, help="Number of lines to show (default 100)")
    parser.add_argument("--since", default=None, help="Show logs since (e.g., 5m, 1h)")
    parser.add_argument("--level", default=None, help="Filter by log levels (comma-separated: error,warn,info,debug,trace)")
    parser.add_argument("--source", default=None, help="Filter by source/service (substring)")
    parser.add_argument("--grep", default=None, help="Filter by message content (substring)")
    parser.add_argument("--buffer", type=int, default=200, help="Scroll buffer size for follow mode")
    parser.add_argument("--hosts-dir", type=Path, default=None, help="Override hosts directory")
    parser.add_argument("--inventory", type=Path, default=None, help="Override inventory.yml path")
    parser.add_argument("--connect-timeout", type=float, default=5.0, help="SSH connection timeout (seconds)")
    parser.add_argument("--timeout", type=float, default=30.0, help="Command timeout for non-follow mode (seconds)")


class LogBuffer:
    """Scrolling buffer of log blocks for live display."""

    def __init__(self, maxlen: int = 200) -> None:
        self._lines: deque[Block] = deque(maxlen=maxlen)
        self._width: int = 80

    def set_width(self, width: int) -> None:
        self._width = width

    def append(self, block: Block) -> None:
        self._lines.append(block)

    def to_block(self) -> Block:
        if not self._lines:
            return Block.text("Waiting for logs...", Style(dim=True), width=self._width)
        return join_vertical(*self._lines)


async def _stream_logs(
    host: HostConfig,
    stack_name: str,
    *,
    service: str | None,
    follow: bool,
    tail: int,
    since: str | None,
    connect_timeout: float,
    filter_: LogFilter | None,
    config: LogLineConfig,
    state: RenderState,
    buffer: LogBuffer,
    renderer: InPlaceRenderer,
    width: int,
) -> int:
    """Stream logs from a stack via SSH."""
    ssh_args = ssh_base_args(host, connect_timeout_s=connect_timeout)

    cmd = ["docker", "compose", "logs", "--no-color", "--tail", str(tail)]
    if follow:
        cmd.append("-f")
    if since:
        cmd.extend(["--since", since])
    if service:
        cmd.append(service)

    remote_cmd = f"cd {shlex.quote(f'/opt/{stack_name}')} && {shlex.join(cmd)}"
    full_cmd = [*ssh_args, f"{host.user}@{host.ip}", remote_cmd]

    line_count = 0
    try:
        async for line_text in run_ssh_streaming(full_cmd):
            if not line_text:
                continue

            log = parse_compose_log_line(line_text)
            if filter_ and not filter_.matches(log):
                continue

            block = render_log_line(log, DEFAULT_THEME, config, state, width)
            buffer.append(block)
            renderer.render(buffer.to_block())
            line_count += 1

    except asyncio.CancelledError:
        return line_count

    return line_count


async def _run_logs_async(ctx: CliContext, args) -> int:
    """Run logs command with live streaming."""
    stack = getattr(args, "stack", None)
    if not stack:
        print("Error: stack argument required", file=sys.stderr)
        return 1

    hosts_dir = getattr(args, "hosts_dir", None) or DEFAULT_HOSTS_DIR
    inventory_path = getattr(args, "inventory", None) or ANSIBLE_INVENTORY_CACHE

    try:
        inventory = load_inventory(inventory_path)
        stacks = list_stacks(hosts_dir)
    except InventoryError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        if e.suggestion:
            print(f"Suggestion: {e.suggestion}", file=sys.stderr)
        return 1

    if stack not in stacks:
        print(f"Error: Unknown stack '{stack}'", file=sys.stderr)
        print(f"Available: {', '.join(stacks)}", file=sys.stderr)
        return 1

    stack_name = stack_name_from_metadata(hosts_dir, stack)
    host = host_config_from_inventory(inventory, stack)
    if host.ip is None:
        print(f"Error: No host configured for stack '{stack}'", file=sys.stderr)
        return 1

    filter_ = build_filter(
        levels=getattr(args, "level", None),
        source=getattr(args, "source", None),
        grep=getattr(args, "grep", None),
    )

    config = LogLineConfig()
    state = RenderState()
    buffer_size = getattr(args, "buffer", 200)
    buffer = LogBuffer(maxlen=buffer_size)
    buffer.set_width(ctx.width)

    follow = getattr(args, "follow", False)
    service = getattr(args, "service", None)
    tail = getattr(args, "tail", 100)
    since = getattr(args, "since", None)
    connect_timeout = getattr(args, "connect_timeout", 5.0)
    timeout = getattr(args, "timeout", 30.0)

    # Header
    title_parts = [stack]
    if service:
        title_parts.append(f"-> {service}")
    if follow:
        title_parts.append("(Ctrl+C to stop)")
    header = " ".join(title_parts)

    if follow:
        # Live streaming mode with InPlaceRenderer
        with InPlaceRenderer() as renderer:
            # Show header
            header_block = Block.text(header, Style(bold=True), width=ctx.width)
            sep_block = Block.text("-" * min(ctx.width, len(header) + 10), Style(dim=True), width=ctx.width)
            renderer.render(join_vertical(header_block, sep_block, buffer.to_block()))

            try:
                line_count = await _stream_logs(
                    host,
                    stack_name,
                    service=service,
                    follow=True,
                    tail=tail,
                    since=since,
                    connect_timeout=connect_timeout,
                    filter_=filter_,
                    config=config,
                    state=state,
                    buffer=buffer,
                    renderer=renderer,
                    width=ctx.width,
                )
                renderer.finalize(join_vertical(header_block, sep_block, buffer.to_block()))
            except KeyboardInterrupt:
                renderer.finalize()
                print(f"\nStreamed {line_count if 'line_count' in dir() else 0} lines", file=sys.stderr)
                return 130

        return 0

    else:
        # Non-follow: fetch once and display
        from ..infra import run_ssh

        ssh_args = ssh_base_args(host, connect_timeout_s=connect_timeout)
        cmd = ["docker", "compose", "logs", "--no-color", "--tail", str(tail)]
        if since:
            cmd.extend(["--since", since])
        if service:
            cmd.append(service)

        remote_cmd = f"cd {shlex.quote(f'/opt/{stack_name}')} && {shlex.join(cmd)}"
        full_cmd = [*ssh_args, f"{host.user}@{host.ip}", remote_cmd]

        rc, stdout, stderr = await run_ssh(full_cmd, timeout_s=timeout)
        if rc != 0:
            print(f"Error: {stderr or stdout or f'exit {rc}'}", file=sys.stderr)
            return 1

        # Parse and display logs
        line_count = 0
        blocks: list[Block] = []

        for line_text in stdout.splitlines():
            if not line_text:
                continue

            log = parse_compose_log_line(line_text)
            if filter_ and not filter_.matches(log):
                continue

            if ctx.format == Format.PLAIN:
                print(render_log_line_plain(log, config))
            else:
                blocks.append(render_log_line(log, DEFAULT_THEME, config, state, ctx.width))
            line_count += 1

        if ctx.format != Format.PLAIN and blocks:
            print_block(join_vertical(*blocks), use_ansi=True)

        print(f"\n{line_count} lines", file=sys.stderr)
        return 0


def run_logs(ctx: CliContext, args) -> int:
    """Run logs command (sync wrapper)."""
    try:
        return asyncio.run(_run_logs_async(ctx, args))
    except KeyboardInterrupt:
        return 130
