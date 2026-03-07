"""Siftd fold lens — domain-aware rendering of conversation fold state.

Reads FoldState directly. No adapter chain — FoldState sections give us
exchange items (by conversation_id), tag items (by name), counts, timestamps.
"""

from __future__ import annotations

from datetime import datetime, timezone

from painted import Block, Style, Zoom, join_vertical


def fold_view(data, zoom, width):
    """Render siftd fold state with domain awareness."""
    sections = {s.kind: s for s in data.sections}
    exchange_section = sections.get("exchange")
    tag_section = sections.get("tag")

    exchange_count = exchange_section.count if exchange_section else 0
    tag_count = tag_section.count if tag_section else 0

    if exchange_count == 0 and tag_count == 0:
        return Block.text("No siftd data yet.", Style(dim=True), width=width)

    # MINIMAL
    if zoom == Zoom.MINIMAL:
        parts = [f"{exchange_count} conversations"]
        if tag_count:
            parts.append(f"{tag_count} tags")
        return Block.text(" · ".join(parts), Style(), width=width)

    rows: list[Block] = []
    bold = Style(bold=True)
    dim = Style(dim=True)

    # Conversations header with observer breakdown
    rows.append(Block.text(f"Conversations ({exchange_count}):", bold, width=width))

    if exchange_section:
        observers: dict[str, int] = {}
        for item in exchange_section.items:
            obs = item.payload.get("model", "") or item.observer or "unknown"
            observers[obs] = observers.get(obs, 0) + 1
        for obs, count in sorted(observers.items(), key=lambda kv: -kv[1]):
            rows.append(Block.text(f"  {obs}: {count}", Style(), width=width))

    # Tags
    if tag_count and tag_section:
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text(f"Tags ({tag_count})", bold, width=width))
        if zoom >= Zoom.SUMMARY:
            for item in tag_section.items[:10]:
                name = item.payload.get("name", "?")
                rows.append(Block.text(f"  #{name}", Style(), width=width))

    # Recent conversations
    if exchange_section and zoom >= Zoom.SUMMARY:
        items_by_ts = sorted(
            exchange_section.items,
            key=lambda i: i.ts or 0,
            reverse=True,
        )
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text("Recent:", bold, width=width))

        for item in items_by_ts[:5]:
            conv_id = item.payload.get("conversation_id", "?")[:8]
            date = _format_date(item.ts) if item.ts else ""

            if zoom >= Zoom.DETAILED:
                prompt = item.payload.get("prompt", "")
                line = f"  {conv_id} ({date}) → {prompt}"
                if width and len(line) > width:
                    line = line[: width - 1] + "…"
                rows.append(Block.text(line, Style(), width=width))
            else:
                model = item.payload.get("model", "")
                suffix = f" ({model})" if model else ""
                rows.append(Block.text(f"  {conv_id} ({date}){suffix}", Style(), width=width))

    return join_vertical(*rows)


def _format_date(ts) -> str:
    """Format timestamp as short date (e.g. 'Feb 27')."""
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return ts[:10] if len(ts) >= 10 else ts
    else:
        return "?"
    return f"{dt.strftime('%b')} {dt.day}"
