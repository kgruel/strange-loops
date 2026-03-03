#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Palette + IconSet — ambient configuration via ContextVar switching.

The lesson: same render function, different aesthetics. Components and lenses
read from ambient Palette/IconSet; you switch the look by switching the context.

    uv run demos/patterns/palette_icons.py -q      # palette roles only
    uv run demos/patterns/palette_icons.py         # one dashboard (ambient)
    uv run demos/patterns/palette_icons.py -v      # 3 palettes, same dashboard
    uv run demos/patterns/palette_icons.py -vv     # palette × icons matrix
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from painted import (
    ASCII_ICONS,
    Block,
    CliContext,
    DEFAULT_PALETTE,
    IconSet,
    MONO_PALETTE,
    NORD_PALETTE,
    Style,
    Wrap,
    Zoom,
    border,
    current_icons,
    current_palette,
    join_horizontal,
    join_responsive,
    join_vertical,
    run_cli,
    use_icons,
    use_palette,
    ROUNDED,
)
from painted.views import ProgressState, SpinnerState, chart_lens, progress_bar, spinner, tree_lens


@dataclass(frozen=True)
class Service:
    name: str
    ready: int
    desired: int
    latency_ms: int | None = None


@dataclass(frozen=True)
class Dashboard:
    deploy_phase: str
    progress: float
    services: tuple[Service, ...]
    metrics: dict[str, int]
    tree: dict[str, object]


CUSTOM_ICONS = IconSet(
    spinner=(".", "o", "O", "o"),
    progress_fill="=",
    progress_empty=".",
    tree_branch=">- ",
    tree_last="`- ",
    tree_indent="|  ",
    tree_space="   ",
    check="OK",
    cross="XX",
    sparkline=("0", "1", "2", "3", "4", "5", "6", "7"),
    bar_fill="=",
    bar_empty=".",
)


def _header(text: str, *, width: int) -> Block:
    return Block.text(f"  {text}", Style(dim=True), width=width, wrap=Wrap.ELLIPSIS)


def _spacer(width: int, height: int = 1) -> Block:
    return Block.text("", Style(), width=width) if height == 1 else Block.empty(width, height)


def _palette_legend(*, width: int) -> Block:
    p = current_palette()
    tags = (
        Block.text(" success ", p.success),
        Block.text(" warning ", p.warning),
        Block.text(" error ", p.error),
        Block.text(" accent ", p.accent),
        Block.text(" muted ", p.muted),
    )
    return join_responsive(*tags, available_width=width, gap=1)


def _service_line(svc: Service, *, width: int) -> Block:
    p = current_palette()
    ic = current_icons()

    ok = svc.ready == svc.desired
    warn = ok and (svc.latency_ms is not None and svc.latency_ms >= 800)

    if ok and not warn:
        style = p.success
        icon = ic.check
    elif warn:
        style = p.warning
        icon = "!" if ic is ASCII_ICONS else "⚠"
    else:
        style = p.error
        icon = ic.cross

    latency = f"{svc.latency_ms}ms" if svc.latency_ms is not None else "—"
    text = f"  {icon} {svc.name:<12} {svc.ready}/{svc.desired} ready  {latency}"
    return Block.text(text, style, width=width, wrap=Wrap.ELLIPSIS)


def _dashboard(data: Dashboard, *, width: int) -> Block:
    """Same renderer, different aesthetics (via ambient palette/icons)."""
    p = current_palette()

    # Phase + spinner
    spin = spinner(SpinnerState(frame=0), style=p.accent)
    phase = Block.text(f" {data.deploy_phase}", p.muted, width=width - 1, wrap=Wrap.ELLIPSIS)
    phase_row = join_horizontal(spin, phase, gap=0)

    # Progress bar
    pct = max(0, min(100, int(round(data.progress * 100))))
    bar_width = max(10, width - 7)
    bar = progress_bar(ProgressState(value=data.progress), width=bar_width)
    pct_block = Block.text(f" {pct:3d}%", p.muted, width=width - bar_width, wrap=Wrap.NONE)
    progress_row = join_horizontal(bar, pct_block, gap=0)

    # Service rows
    services = join_vertical(*(_service_line(s, width=width) for s in data.services), gap=0)

    # IconSet consumers that aren't "status icons"
    metrics_title = Block.text("  metrics", p.muted, width=width, wrap=Wrap.NONE)
    metrics = chart_lens(data.metrics, zoom=1, width=width)

    tree_title = Block.text("  tree", p.muted, width=width, wrap=Wrap.NONE)
    tree = tree_lens(data.tree, zoom=1, width=width)

    return join_vertical(
        phase_row,
        progress_row,
        _spacer(width),
        services,
        _spacer(width),
        metrics_title,
        metrics,
        _spacer(width),
        tree_title,
        tree,
        gap=0,
    )


def _panel(title: str, *, palette, icons, data: Dashboard, inner_width: int) -> Block:
    with use_palette(palette), use_icons(icons):
        p = current_palette()
        content = _dashboard(data, width=inner_width)
        return border(
            content,
            chars=ROUNDED,
            style=p.accent,
            title=title,
            title_style=p.muted,
        )


def _wrap_rows(
    blocks: list[Block], *, available_width: int, gap: int = 2, row_gap: int = 1
) -> Block:
    if not blocks:
        return Block.empty(0, 0)

    cell_w = max(b.width for b in blocks)
    cols = max(1, min(len(blocks), (available_width + gap) // (cell_w + gap)))

    rows: list[Block] = []
    for i in range(0, len(blocks), cols):
        rows.append(join_horizontal(*blocks[i : i + cols], gap=gap))
    return join_vertical(*rows, gap=row_gap)


def _fetch() -> Dashboard:
    return Dashboard(
        deploy_phase="rolling update",
        progress=0.62,
        services=(
            Service("api-gateway", 3, 3, latency_ms=1200),
            Service("worker", 5, 5, latency_ms=90),
            Service("scheduler", 0, 1),
            Service("metrics", 1, 1, latency_ms=140),
        ),
        metrics={"cpu": 67, "mem": 82, "disk": 45, "net": 23, "gpu": 91},
        tree={
            "cluster": {
                "region": "us-east-1",
                "nodes": {"node-a": "ready", "node-b": "draining"},
            },
            "build": {"sha": "8c1f3a2", "artifact": "api-gateway"},
        },
    )


def _render_minimal(ctx: CliContext) -> Block:
    width = max(1, ctx.width)
    return join_vertical(
        _header("palette roles", width=width),
        _spacer(width),
        _palette_legend(width=width),
        gap=0,
    )


def _render_summary(ctx: CliContext, data: Dashboard) -> Block:
    p = current_palette()
    width = max(1, ctx.width)
    inner_width = max(10, width - 2)
    content = _dashboard(data, width=inner_width)
    panel = border(content, chars=ROUNDED, style=p.accent, title="AMBIENT", title_style=p.muted)
    return join_vertical(_spacer(width), panel, gap=0)


def _render_detailed(ctx: CliContext, data: Dashboard) -> Block:
    width = max(1, ctx.width)
    gap = 2
    cols = max(1, min(3, (width + gap) // (26 + gap)))
    panel_w = max(12, min(width, (width - gap * (cols - 1)) // cols))
    inner_w = max(10, panel_w - 2)

    icons = current_icons()
    panels = [
        _panel("DEFAULT", palette=DEFAULT_PALETTE, icons=icons, data=data, inner_width=inner_w),
        _panel("NORD", palette=NORD_PALETTE, icons=icons, data=data, inner_width=inner_w),
        _panel("MONO", palette=MONO_PALETTE, icons=icons, data=data, inner_width=inner_w),
    ]

    return join_vertical(
        _header("same dashboard, three palettes", width=width),
        _spacer(width),
        _wrap_rows(panels, available_width=width, gap=gap, row_gap=1),
        gap=0,
    )


def _render_full(ctx: CliContext, data: Dashboard) -> Block:
    width = max(1, ctx.width)
    gap = 2
    cols = max(1, min(3, (width + gap) // (26 + gap)))
    panel_w = max(12, min(width, (width - gap * (cols - 1)) // cols))
    inner_w = max(10, panel_w - 2)

    palette = DEFAULT_PALETTE
    icon_panels = [
        _panel("UNICODE", palette=palette, icons=IconSet(), data=data, inner_width=inner_w),
        _panel("ASCII", palette=palette, icons=ASCII_ICONS, data=data, inner_width=inner_w),
        _panel("CUSTOM", palette=palette, icons=CUSTOM_ICONS, data=data, inner_width=inner_w),
    ]

    matrix: list[Block] = []
    for pname, pal in (
        ("DEFAULT", DEFAULT_PALETTE),
        ("NORD", NORD_PALETTE),
        ("MONO", MONO_PALETTE),
    ):
        for iname, icons in (
            ("UNICODE", IconSet()),
            ("ASCII", ASCII_ICONS),
            ("CUSTOM", CUSTOM_ICONS),
        ):
            matrix.append(
                _panel(f"{pname}/{iname}", palette=pal, icons=icons, data=data, inner_width=inner_w)
            )

    return join_vertical(
        _header("same dashboard, three icon sets", width=width),
        _spacer(width),
        _wrap_rows(icon_panels, available_width=width, gap=gap, row_gap=1),
        _spacer(width, 2),
        _header("palette × icons", width=width),
        _spacer(width),
        _wrap_rows(matrix, available_width=width, gap=gap, row_gap=1),
        gap=0,
    )


def _render(ctx: CliContext, data: Dashboard) -> Block:
    with use_palette(DEFAULT_PALETTE):
        if ctx.zoom == Zoom.MINIMAL:
            return _render_minimal(ctx)
        if ctx.zoom == Zoom.SUMMARY:
            return _render_summary(ctx, data)
        if ctx.zoom == Zoom.DETAILED:
            return _render_detailed(ctx, data)
        return _render_full(ctx, data)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="palette_icons.py",
    )


if __name__ == "__main__":
    sys.exit(main())
