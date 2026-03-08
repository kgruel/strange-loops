"""Test lens — zoom-aware rendering for parse pipeline test results."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical


def _block(text: str, style: Style, width: int | None) -> Block:
    """Create a Block, respecting width=None (no truncation)."""
    if width is not None:
        return Block.text(text, style, width=width)
    return Block.text(text, style)


def test_view(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
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
        return _block(f"Warning: {data['warning']}", Style(dim=True), width)

    results = data.get("results", [])
    skipped = data.get("skipped", 0)
    total = len(results)

    if zoom == Zoom.MINIMAL:
        return _block(f"{total} parsed, {skipped} skipped", Style(), width)

    dim_style = Style(dim=True)
    rows: list[Block] = []

    for result in results:
        if zoom == Zoom.SUMMARY:
            # One-liner: first key=value pair
            if isinstance(result, dict) and result:
                first_key = next(iter(result))
                rows.append(_block(
                    f"  {first_key}: {result[first_key]}", Style(), width,
                ))
            else:
                rows.append(_block(f"  {result}", Style(), width))
        else:
            # DETAILED/FULL: full dict
            rows.append(_block(f"  {result}", Style(), width))

    # Summary footer
    rows.append(_block("", Style(), width))
    footer = f"--- {total} parsed, {skipped} skipped ---"
    rows.append(_block(footer, dim_style, width))

    return join_vertical(*rows)
