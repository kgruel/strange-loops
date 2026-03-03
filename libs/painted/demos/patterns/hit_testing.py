#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Hit testing — Block.id propagation through composition to Buffer.hit().

Builds a service dashboard with four named panels, composes them into a 2x2
grid, paints into a Buffer, then probes coordinates to show how ids survive
composition and enable mouse picking.

    uv run demos/patterns/hit_testing.py -q        # cell/id counts
    uv run demos/patterns/hit_testing.py           # dashboard + hit probes
    uv run demos/patterns/hit_testing.py -v        # + provenance map (id layer)
    uv run demos/patterns/hit_testing.py -vv       # + composition trace (build steps)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from painted import (
    Block,
    Cell,
    CliContext,
    Style,
    Wrap,
    Zoom,
    border,
    join_horizontal,
    join_vertical,
    pad,
    run_cli,
    truncate,
    ROUNDED,
)
from painted.palette import current_palette
from painted.tui import Buffer


def _header(text: str) -> Block:
    return Block.text(f"  {text}", Style(dim=True))


def _spacer() -> Block:
    return Block.text("", Style())


SERVICES: tuple[tuple[str, dict], ...] = (
    (
        "api-gateway",
        {"status": "healthy", "replicas": "3/3", "latency_ms": 12, "error_rate_pct": 0.2},
    ),
    (
        "auth-service",
        {"status": "degraded", "replicas": "2/3", "latency_ms": 2100, "error_rate_pct": 3.9},
    ),
    ("worker", {"status": "healthy", "replicas": "5/5", "latency_ms": 8, "error_rate_pct": 0.1}),
    (
        "scheduler",
        {"status": "failing", "replicas": "0/1", "latency_ms": 0, "error_rate_pct": 12.4},
    ),
)


@dataclass(frozen=True)
class ProbeResult:
    x: int
    y: int
    hit_id: str | None
    label: str


@dataclass(frozen=True)
class HitTestData:
    grid: Block
    panels: tuple[tuple[str, Block], ...]
    top_row: Block
    bottom_row: Block
    panel_width: int
    panel_height: int
    hgap: int
    vgap: int
    ids_allocated_before_paint: bool
    ids_allocated_after_paint: bool
    total_cells: int
    cells_with_id: int
    unique_ids: tuple[str, ...]
    probes: tuple[ProbeResult, ...]


def _status_style(status: str) -> Style:
    p = current_palette()
    return {
        "healthy": p.success,
        "degraded": p.warning,
        "failing": p.error,
    }.get(status, p.muted)


def _service_panel(name: str, info: dict, *, width: int, inner_height: int) -> Block:
    inner_width = max(8, width - 4)
    status = str(info.get("status", "unknown"))
    replicas = str(info.get("replicas", "?/?"))
    latency_ms = info.get("latency_ms", "?")
    error_rate_pct = info.get("error_rate_pct", "?")

    text = (
        f"status: {status} · replicas: {replicas} · p95: {latency_ms}ms · errors: {error_rate_pct}%"
    )

    content = Block.text(
        text,
        Style(),
        width=inner_width,
        wrap=Wrap.WORD,
        id=name,
    )
    if content.height < inner_height:
        content = pad(content, bottom=inner_height - content.height)
    content = pad(content, left=1, right=1)

    return border(
        content,
        title=f"{name}",
        chars=ROUNDED,
        style=_status_style(status),
    )


def _build_dashboard(
    *,
    panel_width: int = 30,
    inner_height: int = 5,
    hgap: int = 2,
    vgap: int = 1,
) -> HitTestData:
    panels: list[tuple[str, Block]] = [
        (name, _service_panel(name, info, width=panel_width, inner_height=inner_height))
        for name, info in SERVICES
    ]

    top_row = join_horizontal(panels[0][1], panels[1][1], gap=hgap)
    bottom_row = join_horizontal(panels[2][1], panels[3][1], gap=hgap)
    grid = join_vertical(top_row, bottom_row, gap=vgap)

    buf = Buffer(grid.width, grid.height)
    ids_before = buf._ids is not None
    grid.paint(buf, 0, 0)
    ids_after = buf._ids is not None

    total_cells = grid.width * grid.height
    cells_with_id = sum(
        1 for y in range(grid.height) for x in range(grid.width) if buf.hit(x, y) is not None
    )
    unique_ids = tuple(
        sorted(
            {
                cid
                for y in range(grid.height)
                for x in range(grid.width)
                if (cid := buf.hit(x, y)) is not None
            }
        )
    )

    panel_h = panels[0][1].height
    panel_w = panels[0][1].width

    probes: list[ProbeResult] = []
    probes.append(ProbeResult(0, 0, buf.hit(0, 0), "top-left panel border"))
    probes.append(ProbeResult(2, 2, buf.hit(2, 2), "top-left panel content"))
    probes.append(ProbeResult(panel_w, 0, buf.hit(panel_w, 0), "horizontal gap"))
    probes.append(
        ProbeResult(panel_w + hgap, 0, buf.hit(panel_w + hgap, 0), "top-right panel border")
    )
    probes.append(ProbeResult(0, panel_h, buf.hit(0, panel_h), "vertical gap"))
    probes.append(
        ProbeResult(0, panel_h + vgap, buf.hit(0, panel_h + vgap), "bottom-left panel border")
    )
    probes.append(ProbeResult(panel_w, panel_h, buf.hit(panel_w, panel_h), "cross-gap"))
    probes.append(
        ProbeResult(
            panel_w + hgap + 2,
            panel_h + vgap + 2,
            buf.hit(panel_w + hgap + 2, panel_h + vgap + 2),
            "bottom-right panel content",
        )
    )

    return HitTestData(
        grid=grid,
        panels=tuple(panels),
        top_row=top_row,
        bottom_row=bottom_row,
        panel_width=panel_w,
        panel_height=panel_h,
        hgap=hgap,
        vgap=vgap,
        ids_allocated_before_paint=ids_before,
        ids_allocated_after_paint=ids_after,
        total_cells=total_cells,
        cells_with_id=cells_with_id,
        unique_ids=unique_ids,
        probes=tuple(probes),
    )


def _probes_block(probes: tuple[ProbeResult, ...]) -> Block:
    p = current_palette()
    rows: list[Block] = []
    for pr in probes:
        cid = pr.hit_id
        id_text = cid if cid is not None else "∅"
        id_style = p.muted if cid is None else p.accent
        rows.append(
            join_horizontal(
                Block.text(f"  ({pr.x:>2},{pr.y:>2})", Style(dim=True)),
                Block.text(f"  {id_text:<14s}", id_style),
                Block.text(f" {pr.label}", Style(dim=True)),
            )
        )
    return join_vertical(*rows) if rows else Block.text("  (no probes)", Style(dim=True))


def _id_styles() -> dict[str, Style]:
    p = current_palette()
    return {
        "api-gateway": p.success,
        "auth-service": p.warning,
        "worker": p.accent,
        "scheduler": p.error,
    }


def _provenance_map(block: Block) -> Block:
    """Paint to Buffer then render the id layer as a colored grid."""
    p = current_palette()
    styles = _id_styles()

    buf = Buffer(block.width, block.height)
    block.paint(buf, 0, 0)

    rows: list[list[Cell]] = []
    for y in range(block.height):
        row: list[Cell] = []
        for x in range(block.width):
            cid = buf.hit(x, y)
            if cid is None:
                row.append(Cell("·", p.muted))
            else:
                row.append(Cell("█", styles.get(cid, p.accent)))
        rows.append(row)

    return Block(rows, block.width)


def _legend() -> Block:
    p = current_palette()
    styles = _id_styles()
    rows: list[Block] = []
    for name, _info in SERVICES:
        rows.append(
            join_horizontal(
                Block.text("  █", styles.get(name, p.accent)),
                Block.text(f" {name}", Style(dim=True)),
            )
        )
    rows.append(
        join_horizontal(
            Block.text("  ·", p.muted),
            Block.text(" gap / None", Style(dim=True)),
        )
    )
    return join_vertical(*rows)


def _composition_trace(data: HitTestData, *, width: int) -> Block:
    p = current_palette()
    target_inner_width = min(max(0, width - 4), 80)

    panel_maps = [
        border(_provenance_map(panel), title=name, chars=ROUNDED, style=p.muted)
        for name, panel in data.panels
    ]
    panels_grid = join_vertical(
        join_horizontal(panel_maps[0], panel_maps[1], gap=2),
        join_horizontal(panel_maps[2], panel_maps[3], gap=2),
        gap=1,
    )

    rows_step = join_vertical(
        border(
            _provenance_map(data.top_row),
            title="join_horizontal: top row",
            chars=ROUNDED,
            style=p.muted,
        ),
        _spacer(),
        border(
            _provenance_map(data.bottom_row),
            title="join_horizontal: bottom row",
            chars=ROUNDED,
            style=p.muted,
        ),
    )

    grid_step = border(
        _provenance_map(data.grid), title="join_vertical: full grid", chars=ROUNDED, style=p.muted
    )

    inner = join_vertical(
        Block.text(
            f"ids allocated on paint: {data.ids_allocated_before_paint} -> {data.ids_allocated_after_paint}",
            Style(dim=True),
        ),
        Block.text(
            f"cells with id: {data.cells_with_id}/{data.total_cells}  unique: {', '.join(data.unique_ids)}",
            Style(dim=True),
        ),
        _spacer(),
        border(
            pad(panels_grid, right=max(0, target_inner_width - panels_grid.width)),
            title="step 1: leaf panels",
            chars=ROUNDED,
            style=p.muted,
        ),
        _spacer(),
        border(
            pad(rows_step, right=max(0, target_inner_width - rows_step.width)),
            title="step 2: rows",
            chars=ROUNDED,
            style=p.muted,
        ),
        _spacer(),
        border(
            pad(grid_step, right=max(0, target_inner_width - grid_step.width)),
            title="step 3: grid",
            chars=ROUNDED,
            style=p.muted,
        ),
    )

    return inner


def _render_minimal(data: HitTestData, width: int) -> Block:
    p = current_palette()
    return truncate(
        Block.text(
            f"grid {data.grid.width}x{data.grid.height}  cells {data.total_cells}  ids {data.cells_with_id}  unique {len(data.unique_ids)}",
            p.accent,
        ),
        width,
    )


def _render_summary(data: HitTestData, width: int) -> Block:
    return truncate(
        join_vertical(
            _spacer(),
            _header("service dashboard (visual layer)"),
            _spacer(),
            data.grid,
            _spacer(),
            _header("hit probes: Buffer.hit(x, y)"),
            _spacer(),
            _probes_block(data.probes),
        ),
        width,
    )


def _render_detailed(data: HitTestData, width: int) -> Block:
    p = current_palette()
    return truncate(
        join_vertical(
            _render_summary(data, width),
            _spacer(),
            _header("provenance map (id layer)"),
            _spacer(),
            border(_provenance_map(data.grid), chars=ROUNDED, style=p.muted),
            _spacer(),
            _legend(),
        ),
        width,
    )


def _render_full(data: HitTestData, width: int) -> Block:
    p = current_palette()
    summary = _render_summary(data, width)
    detailed = _render_detailed(data, width)
    trace_inner = _composition_trace(data, width=width)

    dashboard = border(summary, title="zoom 1", chars=ROUNDED, style=p.muted)
    provenance = border(detailed, title="zoom 2", chars=ROUNDED, style=p.muted)
    trace = border(trace_inner, title="zoom 3", chars=ROUNDED, style=p.muted)
    return join_vertical(_spacer(), dashboard, _spacer(), provenance, _spacer(), trace)


def _render(ctx: CliContext, data: HitTestData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(data, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(data, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return _render_full(data, ctx.width)
    return _render_detailed(data, ctx.width)


def _fetch() -> HitTestData:
    return _build_dashboard()


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="hit_testing.py",
    )


if __name__ == "__main__":
    sys.exit(main())
