#!/usr/bin/env python3
"""API health check at different fidelity levels.

Demonstrates the fidelity spectrum with service health monitoring:

    uv run python demos/patterns/fidelity_health.py -q        # Zoom 0: minimal one line
    uv run python demos/patterns/fidelity_health.py           # Zoom 1: service list
    uv run python demos/patterns/fidelity_health.py -v        # Zoom 2: styled table
    uv run python demos/patterns/fidelity_health.py -vv       # Zoom 3: full detail
    uv run python demos/patterns/fidelity_health.py -vv -i    # Interactive live TUI dashboard

The TUI mode simulates live updates with changing latencies and status.
"""

from __future__ import annotations

import asyncio
import random
import sys
from dataclasses import dataclass, replace
from enum import Enum

from painted import (
    Block,
    Cursor,
    Style,
    CliContext,
    Zoom,
    OutputMode,
    Format,
    border,
    join_vertical,
    join_horizontal,
    ROUNDED,
    print_block,
    run_cli,
)
from painted.tui import Surface
from painted.views import (
    ListState,
    SpinnerState,
    DOTS,
    spinner,
)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ServiceHealth:
    """Health status for a single service."""

    name: str
    status: HealthStatus
    latency_ms: int | None = None
    last_check: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class HealthData:
    """Complete health check results."""

    services: tuple[ServiceHealth, ...]
    checked_at: str = "2024-01-15 10:30:45"

    @property
    def healthy(self) -> int:
        return sum(1 for s in self.services if s.status == HealthStatus.HEALTHY)

    @property
    def degraded(self) -> int:
        return sum(1 for s in self.services if s.status == HealthStatus.DEGRADED)

    @property
    def unhealthy(self) -> int:
        return sum(1 for s in self.services if s.status == HealthStatus.UNHEALTHY)

    @property
    def avg_latency(self) -> float:
        latencies = [s.latency_ms for s in self.services if s.latency_ms is not None]
        return sum(latencies) / len(latencies) if latencies else 0


# Sample health data
SAMPLE_HEALTH = HealthData(
    services=(
        ServiceHealth("api-gateway", HealthStatus.HEALTHY, 23, "10:30:44"),
        ServiceHealth("auth-service", HealthStatus.HEALTHY, 45, "10:30:43"),
        ServiceHealth("user-service", HealthStatus.HEALTHY, 31, "10:30:45"),
        ServiceHealth("order-service", HealthStatus.DEGRADED, 892, "10:30:42", "High latency"),
        ServiceHealth("payment-service", HealthStatus.HEALTHY, 67, "10:30:44"),
        ServiceHealth("inventory-service", HealthStatus.UNHEALTHY, None, "10:30:40", "Connection refused"),
    ),
)


# ============================================================================
# Level 0: Quiet — one line summary
# ============================================================================


def render_minimal(data: HealthData) -> str:
    """Level 0: Minimal one-line output."""
    total = len(data.services)
    if data.unhealthy > 0:
        return f"{data.healthy}/{total} healthy, {data.unhealthy} down"
    if data.degraded > 0:
        return f"{data.healthy}/{total} healthy, {data.degraded} degraded"
    return f"{data.healthy}/{total} healthy"


# ============================================================================
# Level 1: Standard — multi-line text output
# ============================================================================


def render_standard(data: HealthData) -> str:
    """Level 1: Standard CLI output."""
    lines = [f"Health Check ({data.checked_at})", ""]

    for svc in data.services:
        if svc.status == HealthStatus.HEALTHY:
            mark = "●"
        elif svc.status == HealthStatus.DEGRADED:
            mark = "◐"
        elif svc.status == HealthStatus.UNHEALTHY:
            mark = "○"
        else:
            mark = "?"

        line = f"  {mark} {svc.name}"
        if svc.latency_ms is not None:
            line += f" ({svc.latency_ms}ms)"
        if svc.error:
            line += f" — {svc.error}"
        lines.append(line)

    lines.append("")
    lines.append(f"Status: {data.healthy}/{len(data.services)} healthy")
    if data.avg_latency > 0:
        lines.append(f"Avg latency: {data.avg_latency:.0f}ms")

    return "\n".join(lines)


# ============================================================================
# Level 2: Verbose — styled Block output
# ============================================================================


def render_styled(data: HealthData, width: int) -> Block:
    """Level 2: Styled table with colors."""
    rows: list[Block] = []

    # Header row
    header_style = Style(bold=True, dim=True)
    header = join_horizontal(
        Block.text("Status", header_style, width=8),
        Block.text("Service", header_style, width=20),
        Block.text("Latency", header_style, width=10),
        Block.text("Last Check", header_style, width=12),
        Block.text("Notes", header_style),
    )
    rows.append(header)
    rows.append(Block.text("─" * (width - 4), Style(dim=True)))

    for svc in data.services:
        # Status indicator
        if svc.status == HealthStatus.HEALTHY:
            status_text = "● OK"
            status_style = Style(fg="green", bold=True)
        elif svc.status == HealthStatus.DEGRADED:
            status_text = "◐ WARN"
            status_style = Style(fg="yellow", bold=True)
        elif svc.status == HealthStatus.UNHEALTHY:
            status_text = "○ DOWN"
            status_style = Style(fg="red", bold=True)
        else:
            status_text = "? ???"
            status_style = Style(dim=True)

        status = Block.text(status_text.ljust(8), status_style)

        # Service name
        name = Block.text(svc.name.ljust(20), Style())

        # Latency with color coding
        if svc.latency_ms is not None:
            lat_text = f"{svc.latency_ms}ms".rjust(8)
            if svc.latency_ms > 500:
                lat_style = Style(fg="red")
            elif svc.latency_ms > 200:
                lat_style = Style(fg="yellow")
            else:
                lat_style = Style(fg="green")
            latency = Block.text(lat_text.ljust(10), lat_style)
        else:
            latency = Block.text("—".ljust(10), Style(dim=True))

        # Last check
        last = Block.text((svc.last_check or "—").ljust(12), Style(dim=True))

        # Error/notes
        notes = Block.text(svc.error or "", Style(fg="red", dim=True) if svc.error else Style())

        row = join_horizontal(status, name, latency, last, notes)
        rows.append(row)

    table = join_vertical(*rows)
    table_box = border(table, title=f"Health Check — {data.checked_at}", chars=ROUNDED)

    # Summary
    if data.unhealthy > 0:
        summary_style = Style(fg="red", bold=True)
        summary_text = f"  {data.unhealthy} service(s) down  "
    elif data.degraded > 0:
        summary_style = Style(fg="yellow", bold=True)
        summary_text = f"  {data.degraded} service(s) degraded  "
    else:
        summary_style = Style(fg="green", bold=True)
        summary_text = f"  All {data.healthy} services healthy  "

    summary_text += f"| Avg: {data.avg_latency:.0f}ms"
    summary = Block.text(summary_text, summary_style)

    return join_vertical(table_box, summary, gap=1)


# ============================================================================
# Level 3: Interactive — live TUI dashboard
# ============================================================================


class HealthSurface(Surface):
    """Level 3: Interactive TUI with live updates."""

    def __init__(self, data: HealthData):
        super().__init__()
        self._data = data
        self._list_state = ListState(cursor=Cursor(count=len(data.services)))
        self._spinner = SpinnerState(frames=DOTS)
        self._width = 80
        self._height = 24
        self._tick = 0

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def update(self) -> None:
        self._tick += 1
        self._spinner = self._spinner.tick()

        # Simulate live updates every ~30 ticks
        if self._tick % 30 == 0:
            self._simulate_update()

        self.mark_dirty()

    def _simulate_update(self) -> None:
        """Simulate changing latencies and occasional status changes."""
        new_services = []
        for svc in self._data.services:
            if svc.status == HealthStatus.UNHEALTHY:
                # Unhealthy services stay unhealthy
                new_services.append(svc)
            elif svc.latency_ms is not None:
                # Vary latency randomly
                delta = random.randint(-20, 30)
                new_lat = max(10, svc.latency_ms + delta)

                # Occasionally degrade if latency spikes
                if new_lat > 800 and svc.status == HealthStatus.HEALTHY:
                    new_svc = replace(svc, latency_ms=new_lat, status=HealthStatus.DEGRADED, error="High latency")
                elif new_lat < 400 and svc.status == HealthStatus.DEGRADED:
                    new_svc = replace(svc, latency_ms=new_lat, status=HealthStatus.HEALTHY, error=None)
                else:
                    new_svc = replace(svc, latency_ms=new_lat)
                new_services.append(new_svc)
            else:
                new_services.append(svc)

        self._data = replace(self._data, services=tuple(new_services))

    def render(self) -> None:
        if self._buf is None:
            return

        self._buf.fill(0, 0, self._width, self._height, " ", Style())

        # Header with live indicator
        spin_char = spinner(self._spinner).row(0)[0].char
        header_style = Style(bold=True, fg="cyan", reverse=True)
        header_text = f" {spin_char} Health Dashboard — Live ".center(self._width)
        header = Block.text(header_text, header_style)
        header.paint(self._buf, 0, 0)

        # Service list (left side)
        list_width = 35
        detail_width = self._width - list_width - 3

        services_block = self._render_service_list(list_width - 2)
        services_box = border(services_block, title="Services", chars=ROUNDED)
        services_box.paint(self._buf, 0, 2)

        # Detail panel (right side)
        detail_block = self._render_detail(detail_width - 2)
        detail_box = border(detail_block, title="Details", chars=ROUNDED)
        detail_box.paint(self._buf, list_width + 2, 2)

        # Summary bar
        summary = self._render_summary()
        summary.paint(self._buf, 0, self._height - 3)

        # Footer
        footer_style = Style(dim=True)
        footer = Block.text(" j/k: navigate  r: refresh  q: quit ", footer_style)
        footer.paint(self._buf, 0, self._height - 1)

    def _render_service_list(self, width: int) -> Block:
        """Render the service list with status indicators."""
        rows: list[Block] = []

        for i, svc in enumerate(self._data.services):
            selected = i == self._list_state.selected

            # Status indicator
            if svc.status == HealthStatus.HEALTHY:
                mark = "●"
                mark_style = Style(fg="green", bold=True)
            elif svc.status == HealthStatus.DEGRADED:
                mark = "◐"
                mark_style = Style(fg="yellow", bold=True)
            elif svc.status == HealthStatus.UNHEALTHY:
                mark = "○"
                mark_style = Style(fg="red", bold=True)
            else:
                mark = "?"
                mark_style = Style(dim=True)

            if selected:
                row_style = Style(reverse=True)
                prefix = "▸ "
            else:
                row_style = Style()
                prefix = "  "

            # Latency suffix
            if svc.latency_ms is not None:
                lat_text = f" {svc.latency_ms}ms"
            else:
                lat_text = " —"

            name_width = width - 4 - len(lat_text)
            name_text = svc.name[:name_width].ljust(name_width)

            row = join_horizontal(
                Block.text(prefix, row_style),
                Block.text(mark, mark_style),
                Block.text(" " + name_text, row_style),
                Block.text(lat_text, Style(dim=True) if not selected else row_style),
            )
            rows.append(row)

        return join_vertical(*rows)

    def _render_detail(self, width: int) -> Block:
        """Render details for the selected service."""
        svc = self._data.services[self._list_state.selected]

        lines: list[Block] = []

        # Service name
        lines.append(Block.text(svc.name, Style(bold=True, fg="cyan")))
        lines.append(Block.empty(width, 1))

        # Status
        if svc.status == HealthStatus.HEALTHY:
            status_text = "Healthy"
            status_style = Style(fg="green", bold=True)
        elif svc.status == HealthStatus.DEGRADED:
            status_text = "Degraded"
            status_style = Style(fg="yellow", bold=True)
        elif svc.status == HealthStatus.UNHEALTHY:
            status_text = "Unhealthy"
            status_style = Style(fg="red", bold=True)
        else:
            status_text = "Unknown"
            status_style = Style(dim=True)

        lines.append(
            join_horizontal(
                Block.text("Status:   ", Style(bold=True)),
                Block.text(status_text, status_style),
            )
        )

        # Latency with visual bar
        if svc.latency_ms is not None:
            lat = svc.latency_ms
            if lat > 500:
                lat_style = Style(fg="red")
            elif lat > 200:
                lat_style = Style(fg="yellow")
            else:
                lat_style = Style(fg="green")

            lines.append(
                join_horizontal(
                    Block.text("Latency:  ", Style(bold=True)),
                    Block.text(f"{lat}ms", lat_style),
                )
            )

            # Visual latency bar
            bar_width = min(width - 2, 30)
            filled = min(bar_width, int(lat / 1000 * bar_width))
            bar = "█" * filled + "░" * (bar_width - filled)
            lines.append(Block.text(f"  {bar}", lat_style))
        else:
            lines.append(
                join_horizontal(
                    Block.text("Latency:  ", Style(bold=True)),
                    Block.text("—", Style(dim=True)),
                )
            )

        # Last check
        lines.append(Block.empty(width, 1))
        lines.append(
            join_horizontal(
                Block.text("Last:     ", Style(bold=True)),
                Block.text(svc.last_check or "—", Style(dim=True)),
            )
        )

        # Error message
        if svc.error:
            lines.append(Block.empty(width, 1))
            lines.append(Block.text("Error:", Style(bold=True, fg="red")))
            lines.append(Block.text(f"  {svc.error}", Style(fg="red")))

        return join_vertical(*lines)

    def _render_summary(self) -> Block:
        """Render the summary bar."""
        parts: list[Block] = []

        if self._data.healthy > 0:
            parts.append(Block.text(f" ● {self._data.healthy} healthy ", Style(fg="green")))
        if self._data.degraded > 0:
            parts.append(Block.text(f" ◐ {self._data.degraded} degraded ", Style(fg="yellow")))
        if self._data.unhealthy > 0:
            parts.append(Block.text(f" ○ {self._data.unhealthy} down ", Style(fg="red")))

        parts.append(Block.text(f" | Avg: {self._data.avg_latency:.0f}ms ", Style(bold=True)))

        return join_horizontal(*parts)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key in ("j", "down"):
            self._list_state = self._list_state.move_down()
            self.mark_dirty()
        elif key in ("k", "up"):
            self._list_state = self._list_state.move_up()
            self.mark_dirty()
        elif key == "r":
            self._simulate_update()
            self.mark_dirty()


def run_interactive(data: HealthData) -> None:
    """Level 3: Launch the interactive TUI."""
    surface = HealthSurface(data)
    asyncio.run(surface.run())


# ============================================================================
# Main entry point
# ============================================================================

def _text_block(text: str, *, width: int) -> Block:
    lines = text.splitlines() or [""]
    max_len = max(len(line) for line in lines)
    target_width = max(1, min(width, max_len)) if width > 0 else max(1, max_len)
    return join_vertical(*(Block.text(line, Style(), width=target_width) for line in lines))


def _exit_code(data: HealthData) -> int:
    return 1 if data.unhealthy > 0 else 0


def _fetch() -> HealthData:
    return SAMPLE_HEALTH


def _render(ctx: CliContext, data: HealthData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return Block.text(render_minimal(data), Style())
    if ctx.zoom == Zoom.SUMMARY:
        return _text_block(render_standard(data), width=ctx.width)
    # DETAILED/FULL: styled Blocks
    return render_styled(data, ctx.width)


def _handle_interactive(ctx: CliContext) -> int:
    data = _fetch()
    if not ctx.is_tty:
        block = _render(ctx, data)
        print_block(block, use_ansi=(ctx.format == Format.ANSI))
        return _exit_code(data)
    run_interactive(data)
    return _exit_code(data)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        handlers={OutputMode.INTERACTIVE: _handle_interactive},
        description=__doc__,
        prog="fidelity_health.py",
    )


if __name__ == "__main__":
    sys.exit(main())
