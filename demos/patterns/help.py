#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Zoom-aware help — help text adapts to the zoom level that requested it.

The help itself teaches the three-axis model (zoom, mode, format) by
demonstrating zoom: --help shows grouped flags, --help -v reveals
interaction rules and flag details.

    uv run demos/patterns/help.py -q           # one-line summary
    uv run demos/patterns/help.py              # sample help at SUMMARY
    uv run demos/patterns/help.py -v           # sample help at DETAILED
    uv run demos/patterns/help.py -vv          # SUMMARY and DETAILED side by side
    uv run demos/patterns/help.py --help       # this demo's own zoom-aware help
    uv run demos/patterns/help.py --help -v    # ...with more detail
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

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
    ROUNDED,
)
from painted.fidelity import (
    HelpData,
    HelpFlag,
    HelpGroup,
    _render_help,
)


# --- Sample help data (a hypothetical full-featured CLI) ---

SAMPLE_HELP = HelpData(
    prog="deploy",
    description="Ship services to production.",
    groups=(
        HelpGroup(
            name="Zoom",
            hint="(what to show)",
            detail="Controls how much detail is rendered. Stackable: -v for detailed, -vv for full.",
            flags=(
                HelpFlag("-q", "--quiet", "Minimal output"),
                HelpFlag("-v", "--verbose", "Detailed (-v) or full (-vv)"),
            ),
        ),
        HelpGroup(
            name="Mode",
            hint="(how to deliver)",
            detail="Delivery mechanism. AUTO selects LIVE for TTY, STATIC for pipes.",
            flags=(
                HelpFlag("-i", "--interactive", "Interactive TUI"),
                HelpFlag(None, "--static", "Static output, no animation"),
                HelpFlag(None, "--live", "Live output with in-place updates"),
            ),
        ),
        HelpGroup(
            name="Format",
            hint="(serialization)",
            detail="Output serialization. ANSI is default for TTY, PLAIN for pipes.",
            flags=(
                HelpFlag(None, "--json", "JSON output", detail="Implies --static."),
                HelpFlag(
                    None, "--plain", "Plain text, no ANSI codes",
                    detail="Implies --static when piped.",
                ),
            ),
        ),
        HelpGroup(
            name="Help",
            flags=(
                HelpFlag("-h", "--help", "Show this help", detail="Add -v for more detail."),
            ),
        ),
    ),
)


# --- Render functions ---


def render_minimal(data: HelpData) -> Block:
    """One-line: program name + flag count."""
    flag_count = sum(len(g.flags) for g in data.groups)
    group_names = ", ".join(g.name.lower() for g in data.groups if g.flags)
    desc = f" — {data.description}" if data.description else ""
    return Block.text(f"{data.prog}{desc} ({flag_count} flags: {group_names})", Style())


def render_summary(data: HelpData, width: int) -> Block:
    """Show sample help rendered at SUMMARY zoom."""
    rows: list[Block] = [
        Block.text("Help at default zoom:", Style(dim=True)),
        Block.text("", Style()),
    ]
    help_block = _render_help(data, Zoom.SUMMARY, width, use_ansi=False)
    rows.append(help_block)
    return join_vertical(*rows)


def render_detailed(data: HelpData, width: int) -> Block:
    """Show sample help rendered at DETAILED zoom."""
    rows: list[Block] = [
        Block.text("Help at --help -v:", Style(dim=True)),
        Block.text("", Style()),
    ]
    help_block = _render_help(data, Zoom.DETAILED, width, use_ansi=False)
    rows.append(help_block)
    return join_vertical(*rows)


def render_full(data: HelpData, width: int) -> Block:
    """Side-by-side: SUMMARY vs DETAILED."""
    col_width = max(30, (width - 3) // 2)

    summary_block = _render_help(data, Zoom.SUMMARY, col_width, use_ansi=False)
    detailed_block = _render_help(data, Zoom.DETAILED, col_width, use_ansi=False)

    summary_box = border(
        pad(summary_block, right=max(0, col_width - 2 - summary_block.width)),
        title="--help",
        chars=ROUNDED,
    )
    detailed_box = border(
        pad(detailed_block, right=max(0, col_width - 2 - detailed_block.width)),
        title="--help -v",
        chars=ROUNDED,
    )

    return join_vertical(
        Block.text("SUMMARY vs DETAILED:", Style(dim=True)),
        Block.text("", Style()),
        join_horizontal(summary_box, Block.text(" ", Style()), detailed_box),
    )


# --- run_cli integration ---


def _fetch() -> HelpData:
    return SAMPLE_HELP


def _render(ctx: CliContext, data: HelpData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:
        return render_summary(data, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return render_full(data, ctx.width)
    return render_detailed(data, ctx.width)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="help.py",
    )


if __name__ == "__main__":
    sys.exit(main())
