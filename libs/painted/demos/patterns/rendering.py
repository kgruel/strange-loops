#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Rendering patterns — three ways to control how data becomes output.

    uv run demos/patterns/rendering.py               # show available patterns
    uv run demos/patterns/rendering.py --explicit     # lens API with zoom
    uv run demos/patterns/rendering.py --custom       # custom render function
    uv run demos/patterns/rendering.py --palette      # palette switching
"""

from __future__ import annotations

import sys

from painted import (
    Block,
    DEFAULT_PALETTE,
    MONO_PALETTE,
    NORD_PALETTE,
    Style,
    Zoom,
    border,
    current_palette,
    join_horizontal,
    join_vertical,
    pad,
    print_block,
    show,
    use_palette,
    ROUNDED,
)


def header(text: str) -> Block:
    """Dim section header."""
    return Block.text(f"  {text}", Style(dim=True))


def spacer() -> Block:
    return Block.text("", Style())


# --- Sample data ---

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

METRICS = {
    "cpu": 67,
    "memory": 82,
    "disk": 45,
    "network": 23,
    "gpu": 91,
}


# --- --explicit: lens API with zoom control ---


def demo_explicit():
    """Call tree_lens / chart_lens directly instead of auto-dispatch."""
    from painted.views import tree_lens, chart_lens

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 0 → stats only"),
    ))
    show(chart_lens(METRICS, zoom=0, width=60))

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 1 → sparkline"),
    ))
    show(chart_lens(METRICS, zoom=1, width=60))

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 2 → bar chart"),
    ))
    show(chart_lens(METRICS, zoom=2, width=60))

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 0 → summary"),
    ))
    show(tree_lens(SERVICE, zoom=0, width=60))

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 3 → full expansion"),
    ))
    show(tree_lens(SERVICE, zoom=3, width=60))


# --- --custom: write your own render function ---


def demo_custom():
    """Custom (data, zoom, width) -> Block plugs into show()."""

    def status_card(data: dict, zoom: int, width: int) -> Block:
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
        header("custom lens: zoom 2 → card with endpoint details"),
    ))
    show(SERVICE, lens=status_card, zoom=Zoom.DETAILED)


# --- --palette: semantic colors change everywhere ---


def _sample_card() -> Block:
    """A card using palette roles — looks different per palette."""
    p = current_palette()
    rows = join_vertical(
        Block.text("  api-gateway  2/3 ready", p.warning),
        Block.text("  worker       5/5 ready", p.success),
        Block.text("  scheduler    0/1 ready", p.error),
        Block.text("  queue: 142 pending", p.muted),
    )
    return border(
        pad(rows, left=1, right=1),
        title="Services",
        chars=ROUNDED,
        style=p.accent,
    )


def demo_palette():
    """Same card rendered with three different palettes."""
    palettes = [
        ("DEFAULT", DEFAULT_PALETTE),
        ("NORD", NORD_PALETTE),
        ("MONO", MONO_PALETTE),
    ]

    cards = []
    for name, palette in palettes:
        use_palette(palette)
        label = Block.text(f"  {name}", Style(dim=True))
        cards.append(join_vertical(label, spacer(), _sample_card()))

    use_palette(DEFAULT_PALETTE)

    print_block(join_vertical(
        spacer(),
        header("same card, three palettes"),
        spacer(),
        join_horizontal(*cards, gap=2),
    ))


# --- default: show available patterns ---


def demo_help():
    """Show what's available."""
    rows = join_vertical(
        spacer(),
        Block.text("  rendering patterns", Style(bold=True)),
        spacer(),
        Block.text("  --explicit    lens API: call tree_lens / chart_lens directly", Style()),
        Block.text("  --custom      custom render: write your own (data, zoom, width) -> Block", Style()),
        Block.text("  --palette     palette switching: change all semantic colors at once", Style()),
        spacer(),
        Block.text("  Run with a flag to see the pattern.", Style(dim=True)),
    )
    print_block(rows)


def main():
    args = set(sys.argv[1:])

    if "--explicit" in args:
        demo_explicit()
    elif "--custom" in args:
        demo_custom()
    elif "--palette" in args:
        demo_palette()
    else:
        demo_help()


if __name__ == "__main__":
    main()
