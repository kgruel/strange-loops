"""Population lens — zoom-aware rendering for population tables."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical


def pop_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render population table at the given zoom level.

    data: {header: [str], rows: [{col: val}]}

    Zoom levels:
    - MINIMAL: key_col: N items
    - SUMMARY: column-aligned table with header
    - DETAILED: + store metadata if available
    - FULL: + all metadata
    """
    header = data.get("header", [])
    rows = data.get("rows", [])

    if not header:
        return Block.text(
            "No population header found", Style(dim=True), width=width,
        )

    if zoom == Zoom.MINIMAL:
        key_col = header[0] if header else "items"
        return Block.text(
            f"{key_col}: {len(rows)} entries", Style(), width=width,
        )

    dim_style = Style(dim=True)
    result_rows: list[Block] = []

    # Calculate column widths
    col_widths: dict[str, int] = {}
    for h in header:
        col_widths[h] = len(h)
    for row in rows:
        for h in header:
            val = str(row.get(h, ""))
            col_widths[h] = max(col_widths[h], len(val))

    # Cap total width
    total = sum(col_widths.values()) + (len(header) - 1) * 2
    if total > width:
        # Shrink last column
        last = header[-1]
        excess = total - width
        col_widths[last] = max(col_widths[last] - excess, len(last))

    def _format_row(values: dict[str, str]) -> str:
        parts = []
        for h in header:
            val = str(values.get(h, ""))
            parts.append(val.ljust(col_widths[h])[:col_widths[h]])
        return "  ".join(parts)

    # Header line
    header_vals = {h: h for h in header}
    result_rows.append(Block.text(_format_row(header_vals), Style(bold=True), width=width))

    # Data rows
    for row in rows:
        result_rows.append(Block.text(_format_row(row), Style(), width=width))

    if not rows:
        result_rows.append(Block.text("  (empty)", dim_style, width=width))

    return join_vertical(*result_rows)
