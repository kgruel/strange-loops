#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Live streaming — parallel health checks with animated spinners.

fetch_stream yields frozen snapshots as async results arrive.
Same render function works for live (spinners) and static (final).

    uv run demos/patterns/live.py                  # live on TTY, static in pipe
    uv run demos/patterns/live.py --static         # force static (final snapshot)
    uv run demos/patterns/live.py -q               # live, one-line counter
    uv run demos/patterns/live.py -v               # live, detailed view
    uv run demos/patterns/live.py -vv              # live, bordered dashboard
    uv run demos/patterns/live.py --json           # JSON (implies static)
    uv run demos/patterns/live.py | cat            # pipe detection -> static plain
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator

from painted import (
    Block,
    CliContext,
    Style,
    Zoom,
    border,
    join_horizontal,
    join_vertical,
    pad,
    run_cli,
    truncate,
    ROUNDED,
)
from painted.icon_set import current_icons
from painted.palette import current_palette
from painted._components.spinner import SpinnerState, spinner
from painted._components.progress import ProgressState, progress_bar


# --- Data model ---


class Status(Enum):
    PENDING = "pending"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ServiceCheck:
    name: str
    host: str
    port: int
    status: Status = Status.PENDING
    latency_ms: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class HealthReport:
    checks: tuple[ServiceCheck, ...]
    spinner_frame: int = 0
    elapsed_ms: float = 0.0


# --- Simulated services ---

SERVICES = (
    ServiceCheck("postgres", "db-1.internal", 5432),
    ServiceCheck("redis", "cache-1.internal", 6379),
    ServiceCheck("api-gateway", "gw-1.internal", 8443),
    ServiceCheck("worker", "worker-1.internal", 9090),
    ServiceCheck("scheduler", "cron-1.internal", 8080),
    ServiceCheck("metrics", "prom-1.internal", 9091),
)

# Simulated outcomes: (latency_seconds, status, detail)
OUTCOMES: dict[str, tuple[float, Status, str]] = {
    "postgres": (0.3, Status.HEALTHY, "accepting connections"),
    "redis": (0.2, Status.HEALTHY, "6 keys, 0 clients blocked"),
    "api-gateway": (1.4, Status.DEGRADED, "p99 latency 1200ms"),
    "worker": (0.5, Status.HEALTHY, "3 jobs queued"),
    "scheduler": (1.8, Status.DOWN, "connection refused"),
    "metrics": (0.7, Status.HEALTHY, "scrape OK, 142 series"),
}


# --- Async fan-out ---


async def _check_service(svc: ServiceCheck) -> ServiceCheck:
    """Simulate a health check with delay."""
    latency, status, detail = OUTCOMES[svc.name]
    await asyncio.sleep(latency)
    return ServiceCheck(
        name=svc.name,
        host=svc.host,
        port=svc.port,
        status=status,
        latency_ms=latency * 1000,
        detail=detail,
    )


async def _fetch_stream() -> AsyncIterator[HealthReport]:
    """Fan out health checks, yield snapshots as results arrive."""
    checks: dict[str, ServiceCheck] = {s.name: s for s in SERVICES}
    tasks: dict[asyncio.Task[ServiceCheck], str] = {}

    for svc in SERVICES:
        task = asyncio.create_task(_check_service(svc))
        tasks[task] = svc.name

    tick = 0
    start = asyncio.get_event_loop().time()

    # Initial all-pending snapshot
    yield HealthReport(
        checks=tuple(checks.values()),
        spinner_frame=tick,
        elapsed_ms=0.0,
    )

    pending = set(tasks.keys())
    while pending:
        done, pending = await asyncio.wait(pending, timeout=0.1)
        for task in done:
            result = task.result()
            checks[result.name] = result
        tick += 1
        elapsed = (asyncio.get_event_loop().time() - start) * 1000
        yield HealthReport(
            checks=tuple(checks.values()),
            spinner_frame=tick,
            elapsed_ms=elapsed,
        )


# --- Static fetch ---


def _fetch() -> HealthReport:
    """Return completed report (no spinners)."""
    checks: list[ServiceCheck] = []
    total_ms = 0.0
    for svc in SERVICES:
        latency, status, detail = OUTCOMES[svc.name]
        checks.append(ServiceCheck(
            name=svc.name, host=svc.host, port=svc.port,
            status=status, latency_ms=latency * 1000, detail=detail,
        ))
        total_ms = max(total_ms, latency * 1000)
    return HealthReport(checks=tuple(checks), elapsed_ms=total_ms)


# --- Render helpers ---


def _status_icon(status: Status, frame: int) -> Block:
    """Status indicator: spinner for pending, icon for resolved."""
    p = current_palette()
    icons = current_icons()
    if status == Status.PENDING:
        return spinner(SpinnerState(frame=frame), style=p.accent)
    if status == Status.HEALTHY:
        return Block.text(icons.check, p.success)
    if status == Status.DEGRADED:
        return Block.text("!", p.warning)
    return Block.text(icons.cross, p.error)


def _counts(checks: tuple[ServiceCheck, ...]) -> dict[Status, int]:
    """Count checks by status."""
    result: dict[Status, int] = {s: 0 for s in Status}
    for c in checks:
        result[c.status] += 1
    return result


# --- Zoom renderers ---


def _render_minimal(report: HealthReport, width: int) -> Block:
    """Zoom 0: one-line status counts."""
    ct = _counts(report.checks)
    p = current_palette()
    parts: list[Block] = []
    if ct[Status.PENDING]:
        parts.append(Block.text(f"{ct[Status.PENDING]} pending", p.accent))
    if ct[Status.HEALTHY]:
        parts.append(Block.text(f"{ct[Status.HEALTHY]}/{len(report.checks)} healthy", p.success))
    if ct[Status.DEGRADED]:
        parts.append(Block.text(f"  {ct[Status.DEGRADED]} degraded", p.warning))
    if ct[Status.DOWN]:
        parts.append(Block.text(f"  {ct[Status.DOWN]} down", p.error))
    result = join_horizontal(*parts) if parts else Block.text("no checks", Style())
    return truncate(result, width)


def _render_summary(report: HealthReport, width: int) -> Block:
    """Zoom 1: service list with status icons."""
    rows: list[Block] = []
    for check in report.checks:
        icon = _status_icon(check.status, report.spinner_frame)
        name = Block.text(f" {check.name:<14s}", Style())
        host = Block.text(f"{check.host}:{check.port}", Style(dim=True))
        if check.status != Status.PENDING:
            latency = Block.text(f"  {check.latency_ms:.0f}ms", Style(dim=True))
            rows.append(join_horizontal(icon, name, host, latency))
        else:
            rows.append(join_horizontal(icon, name, host))
    return truncate(join_vertical(*rows), width)


def _render_detailed(report: HealthReport, width: int) -> Block:
    """Zoom 2: service list + detail + footer."""
    rows: list[Block] = []
    for check in report.checks:
        icon = _status_icon(check.status, report.spinner_frame)
        name = Block.text(f" {check.name:<14s}", Style())
        host = Block.text(f"{check.host}:{check.port}", Style(dim=True))
        if check.status != Status.PENDING:
            latency = Block.text(f"  {check.latency_ms:.0f}ms", Style(dim=True))
            detail = Block.text(f"  {check.detail}", Style(dim=True))
            rows.append(join_horizontal(icon, name, host, latency, detail))
        else:
            rows.append(join_horizontal(icon, name, host))

    # Footer
    ct = _counts(report.checks)
    p = current_palette()
    footer_parts: list[str] = []
    if ct[Status.HEALTHY]:
        footer_parts.append(f"{ct[Status.HEALTHY]} healthy")
    if ct[Status.DEGRADED]:
        footer_parts.append(f"{ct[Status.DEGRADED]} degraded")
    if ct[Status.DOWN]:
        footer_parts.append(f"{ct[Status.DOWN]} down")
    if ct[Status.PENDING]:
        footer_parts.append(f"{ct[Status.PENDING]} pending")
    footer_text = "  ".join(footer_parts)
    elapsed = f"  [{report.elapsed_ms:.0f}ms]" if report.elapsed_ms else ""

    rows.append(Block.text("", Style()))
    rows.append(Block.text(f"{footer_text}{elapsed}", p.muted))
    return truncate(join_vertical(*rows), width)


def _render_full(report: HealthReport, width: int) -> Block:
    """Zoom 3: bordered box with progress bar and full details."""
    p = current_palette()

    # Progress bar: fraction of completed checks
    total = len(report.checks)
    ct = _counts(report.checks)
    done = total - ct[Status.PENDING]
    pbar = progress_bar(ProgressState(value=done / total if total else 0), width=min(40, width - 4))
    progress_label = Block.text(f" {done}/{total} complete", Style(dim=True))
    progress_row = join_horizontal(pbar, progress_label)

    # Service rows
    rows: list[Block] = []
    for check in report.checks:
        icon = _status_icon(check.status, report.spinner_frame)
        name = Block.text(f" {check.name:<14s}", Style(bold=True))
        host = Block.text(f"{check.host}:{check.port}", Style(dim=True))
        if check.status != Status.PENDING:
            latency = Block.text(f"  {check.latency_ms:.0f}ms", Style(dim=True))
            detail = Block.text(f"  {check.detail}", Style(dim=True))
            rows.append(join_horizontal(icon, name, host, latency, detail))
        else:
            rows.append(join_horizontal(icon, name, host))

    service_block = join_vertical(*rows) if rows else Block.text("(none)", Style())

    # Footer
    footer_parts: list[str] = []
    if ct[Status.HEALTHY]:
        footer_parts.append(f"{ct[Status.HEALTHY]} healthy")
    if ct[Status.DEGRADED]:
        footer_parts.append(f"{ct[Status.DEGRADED]} degraded")
    if ct[Status.DOWN]:
        footer_parts.append(f"{ct[Status.DOWN]} down")
    elapsed = f"  [{report.elapsed_ms:.0f}ms]" if report.elapsed_ms else ""
    footer = Block.text(f"{'  '.join(footer_parts)}{elapsed}", p.muted)

    inner = join_vertical(progress_row, Block.text("", Style()), service_block, Block.text("", Style()), footer)
    content_width = inner.width
    padded = pad(inner, right=max(0, min(60, width - 4) - content_width))

    return border(padded, title="Health Check", chars=ROUNDED)


# --- Main render dispatch ---


def _render(ctx: CliContext, report: HealthReport) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(report, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(report, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return _render_full(report, ctx.width)
    return _render_detailed(report, ctx.width)


# --- Entry point ---


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        fetch_stream=_fetch_stream,
        description=__doc__,
        prog="live.py",
    )


if __name__ == "__main__":
    sys.exit(main())
