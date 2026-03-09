"""Siftd fold lens — domain-aware rendering of conversation fold state.

Reads FoldState directly. Raw records are folded by sessionId —
each fold item is the latest record for a conversation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from painted import Block, Style, Zoom, join_vertical


def _extract_content(payload: dict) -> str:
    """Extract text content from a raw record payload.

    Handles polymorphic message.content: string or list of content blocks.
    """
    message = payload.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return " ".join(parts)
    return ""


def fold_view(data, zoom, width):
    """Render siftd fold state with domain awareness."""
    sections = {s.kind: s for s in data.sections}
    record_section = sections.get("record")
    tag_section = sections.get("tag")

    session_count = record_section.count if record_section else 0
    record_count = record_section.scalars.get("count", session_count) if record_section else 0
    tag_count = tag_section.count if tag_section else 0

    if session_count == 0 and tag_count == 0:
        return Block.text("No siftd data yet.", Style(dim=True), width=width)

    # MINIMAL
    if zoom == Zoom.MINIMAL:
        parts = [f"{session_count} conversations ({record_count} records)"]
        if tag_count:
            parts.append(f"{tag_count} tags")
        return Block.text(" · ".join(parts), Style(), width=width)

    rows: list[Block] = []
    bold = Style(bold=True)

    # Conversations header
    rows.append(Block.text(
        f"Conversations ({session_count}, {record_count} records):", bold, width=width,
    ))

    # Tags
    if tag_count and tag_section:
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text(f"Tags ({tag_count})", bold, width=width))
        if zoom >= Zoom.SUMMARY:
            for item in tag_section.items[:10]:
                name = item.payload.get("name", "?")
                rows.append(Block.text(f"  #{name}", Style(), width=width))

    # Recent conversations (latest record per session)
    if record_section and zoom >= Zoom.SUMMARY:
        items_by_ts = sorted(
            record_section.items,
            key=lambda i: i.ts or 0,
            reverse=True,
        )
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text("Recent:", bold, width=width))

        for item in items_by_ts[:5]:
            session_id = item.payload.get("sessionId", "?")[:8]
            date = _format_date(item.ts) if item.ts else ""
            workspace = item.payload.get("cwd", "")
            if workspace:
                workspace = workspace.rsplit("/", 1)[-1]

            if zoom >= Zoom.DETAILED:
                content = _extract_content(item.payload)
                if content:
                    line = f"  {session_id} ({date}) {content}"
                else:
                    line = f"  {session_id} ({date}) ({workspace})" if workspace else f"  {session_id} ({date})"
                if width and len(line) > width:
                    line = line[: width - 1] + "…"
                rows.append(Block.text(line, Style(), width=width))
            else:
                suffix = f" ({workspace})" if workspace else ""
                rows.append(Block.text(
                    f"  {session_id} ({date}){suffix}", Style(), width=width,
                ))

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
