"""Start lens — zoom-aware rendering for vertex results."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_vertical
from painted.views import shape_lens


def start_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render vertex tick results at the given zoom level.

    data: {tick_name: payload_dict, ...} from program.collect()

    Zoom levels:
    - MINIMAL: vertex_name: N ticks (caller provides name wrapper)
    - SUMMARY: per-tick name + payload key summary
    - DETAILED: per-tick with expanded payload values
    - FULL: all tick metadata + full payloads
    """
    if not data:
        return Block.text("No ticks produced.", Style(dim=True), width=width)

    if zoom == Zoom.MINIMAL:
        return Block.text(f"{len(data)} ticks", Style(), width=width)

    header_style = Style(bold=True)
    dim_style = Style(dim=True)
    rows: list[Block] = []

    for name, payload in data.items():
        if zoom == Zoom.SUMMARY:
            # Name + payload key summary
            if isinstance(payload, dict) and payload:
                keys = ", ".join(list(payload.keys())[:5])
                if len(payload) > 5:
                    keys += f" (+{len(payload) - 5})"
                rows.append(Block.text(f"  [{name}] {keys}", Style(), width=width))
            else:
                rows.append(Block.text(f"  [{name}]", Style(), width=width))

        elif zoom == Zoom.DETAILED:
            rows.append(Block.text(f"[{name}]", header_style, width=width))
            if payload:
                body = shape_lens(payload, zoom=1, width=width - 2)
                rows.append(body)
                rows.append(Block.empty(width, 1))

        else:  # FULL
            rows.append(Block.text(f"[{name}]", header_style, width=width))
            if payload:
                body = shape_lens(payload, zoom=2, width=width - 2)
                rows.append(body)
                rows.append(Block.empty(width, 1))

    # Remove trailing empty
    if rows and rows[-1].height == 1:
        text = "".join(c.char for c in rows[-1].row(0)).strip()
        if text == "":
            rows.pop()

    return join_vertical(*rows)
