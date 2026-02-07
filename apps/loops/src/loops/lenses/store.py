"""Store lens — zoom-based rendering for store inspection."""
from __future__ import annotations

from cells import Block, Style, Zoom
from cells.lens import shape_lens


def store_view(data: dict, zoom: Zoom, width: int) -> Block:
    """Render store summary at the given zoom level."""
    if zoom == Zoom.MINIMAL:
        facts = data["facts"]["total"]
        ticks = data["ticks"]["total"]
        return Block.text(f"{facts} facts, {ticks} ticks", Style(), width=width)

    return shape_lens(data, zoom=zoom.value, width=width)
