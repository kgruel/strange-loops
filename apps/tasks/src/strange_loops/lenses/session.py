"""Session lenses — (data, zoom, width) -> Block."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted import Zoom
    from painted.core.block import Block


def session_status_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render session status data as a Block.

    data is the dict from StoreReader.summary():
        {"facts": {"total": N, "kinds": {kind: {"count": N, "latest": dt}}}, "ticks": {...}}

    MINIMAL: `Session: N facts, M ticks`
    SUMMARY: header + per-kind count + latest timestamp
    DETAILED: + ticks section, earliest..latest range per kind
    FULL: + ISO timestamps instead of short dates
    """
    from painted import Zoom
    from painted.core.block import Block
    from painted.core.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    facts_info = data.get("facts", {})
    total = facts_info.get("total", 0)
    kinds = facts_info.get("kinds", {})
    ticks_info = data.get("ticks", {})
    tick_total = ticks_info.get("total", 0)

    if zoom == Zoom.MINIMAL:
        return Block.text(f"Session: {total} facts, {tick_total} ticks", p.muted)

    header = Block.text(f"Session — {total} facts", p.accent)

    if not kinds:
        return join_vertical(header, Block.text("  (empty)", p.muted))

    lines: list[Block] = [header]
    for kind, info in sorted(kinds.items()):
        count = info["count"]
        latest = info.get("latest")
        if zoom >= Zoom.FULL and latest:
            age = f"latest {latest.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        elif latest:
            age = f"latest {latest.strftime('%b %d %H:%M')}"
        else:
            age = ""

        line = f"  {kind}: {count}  {age}"

        if zoom >= Zoom.DETAILED:
            earliest = info.get("earliest")
            if earliest and latest and earliest != latest:
                if zoom >= Zoom.FULL:
                    line += f"  earliest {earliest.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                else:
                    line += f"  earliest {earliest.strftime('%b %d %H:%M')}"

        lines.append(Block.text(line, p.muted))

    if zoom >= Zoom.DETAILED and tick_total > 0:
        # Build ticks section as a separate group, join with gap
        facts_section = join_vertical(*lines)
        tick_lines: list[Block] = [Block.text(f"Ticks — {tick_total}", p.accent)]
        tick_kinds = ticks_info.get("names", {})
        for kind, info in sorted(tick_kinds.items()):
            count = info["count"]
            latest = info.get("latest")
            if zoom >= Zoom.FULL and latest:
                age = f"latest {latest.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            elif latest:
                age = f"latest {latest.strftime('%b %d %H:%M')}"
            else:
                age = ""
            tick_lines.append(Block.text(f"  {kind}: {count}  {age}", p.muted))
        return join_vertical(facts_section, join_vertical(*tick_lines), gap=1)

    return join_vertical(*lines)


def session_log_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render session log data as a Block.

    data is {"facts": [...], "ticks": [...]}.
    Zoom handled by log_block_zoom.
    """
    from strange_loops.store import log_block_zoom

    return log_block_zoom(data["facts"], data.get("ticks", []), zoom)
