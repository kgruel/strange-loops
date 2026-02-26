#!/usr/bin/env python3
"""show(data) — zero-config display, progressive by default.

Same data, one function, the stack figures out the rest:

    uv run python demos/patterns/show.py              # shape_lens, auto-detect
    uv run python demos/patterns/show.py | cat         # piped → plain text
    uv run python demos/patterns/show.py --json        # JSON serialization
    uv run python demos/patterns/show.py --zoom        # all zoom levels side by side
    uv run python demos/patterns/show.py --lens        # custom lens override
    uv run python demos/patterns/show.py --block       # pre-built Block passthrough
"""

from __future__ import annotations

import sys

from fidelis import (
    Block,
    Format,
    Style,
    Zoom,
    border,
    join_horizontal,
    join_vertical,
    pad,
    show,
    ROUNDED,
)

# Sample data — the kind of thing a script might have lying around
DEPLOY = {
    "service": "api-gateway",
    "version": "2.4.1",
    "replicas": {"desired": 3, "ready": 2, "failed": 1},
    "endpoints": [
        {"path": "/health", "status": 200, "latency_ms": 12},
        {"path": "/api/v1/users", "status": 200, "latency_ms": 45},
        {"path": "/api/v1/auth", "status": 503, "latency_ms": 2100},
    ],
    "tags": ["production", "us-east-1"],
}


def demo_default():
    """The simplest case: show(data). That's it."""
    print("── show(data) ──\n")
    show(DEPLOY)


def demo_json():
    """Force JSON output — what you'd pipe to jq."""
    print("── show(data, format=Format.JSON) ──\n")
    show(DEPLOY, format=Format.JSON)


def demo_zoom():
    """All four zoom levels, side by side."""
    print("── Zoom levels ──\n")
    for level in Zoom:
        label = Block.text(f"zoom={level.value} ({level.name}):", Style(bold=True))
        show(label)
        show(DEPLOY, zoom=level)
        print()


def demo_lens():
    """Custom lens override — show the same data differently."""
    from fidelis.views import tree_lens

    print("── show(data, lens=tree_lens) ──\n")
    show(DEPLOY, lens=tree_lens)


def demo_block():
    """Pre-built Block passthrough — show() just prints it."""
    print("── show(block) ──\n")
    header = Block.text(" api-gateway ", Style(bold=True, reverse=True))
    status = join_vertical(
        Block.text("  replicas: 2/3 ready", Style(fg="yellow")),
        Block.text("  /health:      200  12ms", Style(fg="green")),
        Block.text("  /api/v1/auth: 503  2.1s", Style(fg="red", bold=True)),
    )
    card = border(join_vertical(header, pad(status, top=1)), chars=ROUNDED)
    show(card)


def main():
    args = set(sys.argv[1:])

    if "--json" in args:
        demo_json()
    elif "--zoom" in args:
        demo_zoom()
    elif "--lens" in args:
        demo_lens()
    elif "--block" in args:
        demo_block()
    else:
        demo_default()


if __name__ == "__main__":
    main()
