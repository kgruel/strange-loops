"""Test lens — zoom-aware rendering for parse pipeline test results."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical


def test_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render test results at the given zoom level.

    data: {results: [dict], skipped: int, total: int}

    Zoom levels:
    - MINIMAL: N parsed, M skipped
    - SUMMARY: per-result one-liner (first key-value pair)
    - DETAILED: full result dicts
    - FULL: + skip count, total
    """
    # Warning state (e.g. no parse pipeline defined)
    if data.get("warning"):
        return Block.text(
            f"Warning: {data['warning']}", Style(dim=True), width=width,
        )

    results = data.get("results", [])
    skipped = data.get("skipped", 0)
    total = len(results)

    if zoom == Zoom.MINIMAL:
        return Block.text(
            f"{total} parsed, {skipped} skipped", Style(), width=width,
        )

    dim_style = Style(dim=True)
    rows: list[Block] = []

    for result in results:
        if zoom == Zoom.SUMMARY:
            # One-liner: first key=value pair
            if isinstance(result, dict) and result:
                first_key = next(iter(result))
                rows.append(Block.text(
                    f"  {first_key}: {result[first_key]}", Style(), width=width,
                ))
            else:
                rows.append(Block.text(f"  {result}", Style(), width=width))
        else:
            # DETAILED/FULL: full dict
            rows.append(Block.text(f"  {result}", Style(), width=width))

    # Summary footer
    rows.append(Block.text("", Style(), width=width))
    footer = f"--- {total} parsed, {skipped} skipped ---"
    rows.append(Block.text(footer, dim_style, width=width))

    return join_vertical(*rows)
