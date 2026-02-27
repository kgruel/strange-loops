#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Auto-dispatch — shape_lens picks the right strategy for your data.

Three levels of control over how data becomes Blocks:

  1. show(data)              — auto-dispatch, zero config
  2. Explicit lens           — tree_lens / chart_lens directly
  3. Custom render function  — full control, same signature

Run:
    uv run demos/patterns/auto_dispatch.py
    uv run demos/patterns/auto_dispatch.py --explicit
    uv run demos/patterns/auto_dispatch.py --custom
"""

from __future__ import annotations

import sys

from painted import (
    Block,
    Style,
    Zoom,
    border,
    join_vertical,
    pad,
    print_block,
    show,
    ROUNDED,
)


def header(text: str) -> Block:
    """Dim section header — same pattern as primitives demos."""
    return Block.text(f"  {text}", Style(dim=True))


def spacer() -> Block:
    return Block.text("", Style())


# ---------------------------------------------------------------------------
# Sample data — different shapes trigger different strategies
# ---------------------------------------------------------------------------

# Flat key-value (string values) → dict renderer
CONFIG = {
    "host": "api.example.com",
    "port": "8443",
    "env": "production",
    "region": "us-east-1",
}

# All-numeric values → chart_lens (bar chart)
METRICS = {
    "cpu": 67,
    "memory": 82,
    "disk": 45,
    "network": 23,
    "gpu": 91,
}

# Numeric sequence → chart_lens (sparkline)
TRAFFIC = [12, 15, 23, 45, 67, 89, 95, 87, 76, 65, 54, 48, 52, 61, 73, 82]

# Hierarchical (nested dicts/lists) → tree_lens
SERVICE = {
    "api-gateway": {
        "replicas": {"desired": 3, "ready": 2},
        "endpoints": {
            "/health": {"status": 200, "latency_ms": 12},
            "/api/v1/auth": {"status": 503, "latency_ms": 2100},
        },
    },
    "worker": {
        "replicas": {"desired": 5, "ready": 5},
        "queue_depth": 142,
    },
}


# ---------------------------------------------------------------------------
# Level 1: show(data) — shape_lens auto-dispatches
# ---------------------------------------------------------------------------


def demo_auto():
    """Same function, different data → different rendering."""
    print_block(join_vertical(
        spacer(),
        header("flat dict → key-value"),
    ))
    show(CONFIG, zoom=Zoom.DETAILED)

    print_block(join_vertical(
        spacer(),
        header("numeric dict → bar chart"),
    ))
    show(METRICS, zoom=Zoom.DETAILED)

    print_block(join_vertical(
        spacer(),
        header("numeric list → sparkline"),
    ))
    show(TRAFFIC)

    print_block(join_vertical(
        spacer(),
        header("hierarchical dict → tree"),
    ))
    show(SERVICE, zoom=Zoom.DETAILED)


# ---------------------------------------------------------------------------
# Level 2: Explicit lens — bypass auto-dispatch
# ---------------------------------------------------------------------------


def demo_explicit():
    """Call tree_lens / chart_lens directly for full control."""
    from painted.views import tree_lens, chart_lens

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 0 → stats"),
    ))
    block = chart_lens(METRICS, zoom=0, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 1 → sparkline"),
    ))
    block = chart_lens(METRICS, zoom=1, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 2 → bars"),
    ))
    block = chart_lens(METRICS, zoom=2, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 0 → root + count"),
    ))
    block = tree_lens(SERVICE, zoom=0, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 1 → immediate children"),
    ))
    block = tree_lens(SERVICE, zoom=1, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 3 → full expansion"),
    ))
    block = tree_lens(SERVICE, zoom=3, width=60)
    show(block)


# ---------------------------------------------------------------------------
# Level 3: Custom render function — same (data, zoom, width) -> Block
# ---------------------------------------------------------------------------


def demo_custom():
    """Write your own render function. Same signature, full control."""

    def status_card(data: dict, zoom: int, width: int) -> Block:
        """Custom renderer — builds a styled status card."""
        rows = []
        for name, info in data.items():
            replicas = info.get("replicas", {})
            ready = replicas.get("ready", 0)
            desired = replicas.get("desired", 0)
            ok = ready == desired

            color = "green" if ok else "red"
            icon = "+" if ok else "!"
            row = Block.text(
                f" {icon} {name} ({ready}/{desired} ready)",
                Style(fg=color, bold=True),
            )

            if zoom >= 2:
                details = []
                if "endpoints" in info:
                    for path, ep in info["endpoints"].items():
                        status = ep.get("status", "?")
                        latency = ep.get("latency_ms", "?")
                        ep_color = "green" if status == 200 else "red"
                        details.append(Block.text(
                            f"   {path}: {status} ({latency}ms)",
                            Style(fg=ep_color),
                        ))
                if "queue_depth" in info:
                    details.append(Block.text(
                        f"   queue: {info['queue_depth']}",
                        Style(dim=True),
                    ))
                if details:
                    row = join_vertical(row, *details)

            rows.append(row)

        content = join_vertical(*rows)
        if zoom >= 1:
            content = pad(content, left=1, right=1)
            content = border(content, chars=ROUNDED, style=Style(dim=True))
        return content

    print_block(join_vertical(
        spacer(),
        header("custom lens: zoom 1 → bordered card"),
    ))
    show(SERVICE, lens=status_card, zoom=Zoom.SUMMARY)

    print_block(join_vertical(
        spacer(),
        header("custom lens: zoom 2 → card with details"),
    ))
    show(SERVICE, lens=status_card, zoom=Zoom.DETAILED)


def main():
    args = set(sys.argv[1:])

    if "--explicit" in args:
        demo_explicit()
    elif "--custom" in args:
        demo_custom()
    else:
        demo_auto()


if __name__ == "__main__":
    main()
