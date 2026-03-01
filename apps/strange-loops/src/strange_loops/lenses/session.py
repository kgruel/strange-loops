"""Session lenses — (data, zoom, width) -> Block."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted import Zoom
    from painted.block import Block


def session_status_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render session status data as a Block.

    data is the dict from StoreReader.summary():
        {"facts": {"total": N, "kinds": {kind: {"count": N, "latest": dt}}}, "ticks": {...}}
    """
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    facts_info = data.get("facts", {})
    total = facts_info.get("total", 0)
    kinds = facts_info.get("kinds", {})

    header = Block.text(f"Session — {total} facts", p.accent)

    if not kinds:
        return join_vertical(header, Block.text("  (empty)", p.muted))

    lines: list[Block] = [header]
    for kind, info in sorted(kinds.items()):
        count = info["count"]
        latest = info.get("latest")
        age = f"latest {latest.strftime('%b %d %H:%M')}" if latest else ""
        lines.append(Block.text(f"  {kind}: {count}  {age}", p.muted))

    return join_vertical(*lines)


def session_log_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render session log data as a Block.

    data is {"facts": [...], "ticks": [...]}.
    """
    from strange_loops.store import log_block

    return log_block(data["facts"], data.get("ticks", []))
