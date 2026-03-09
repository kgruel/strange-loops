"""siftd lenses — PayloadLens + status/log/search views."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_vertical
from painted.compose import join_horizontal
from painted.palette import current_palette


def siftd_lens(kind: str, payload: dict, zoom: Zoom) -> str | Block:
    """Interpret siftd fact payloads for record_line rendering.

    Follows the PayloadLens protocol: (kind, payload, zoom) -> str | Block.
    Returns str for simple cases, Block when styled output is needed.
    """
    if kind == "record":
        return _record_lens(payload, zoom)
    if kind == "exchange":
        return _record_lens(payload, zoom)  # backwards compat
    if kind == "tag":
        return _tag_lens(payload, zoom)
    return ""


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
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return " ".join(parts)
    return ""


def _record_lens(payload: dict, zoom: Zoom) -> str | Block:
    """Render raw record payload — user/assistant turns from a coding session."""
    content = _extract_content(payload)
    record_type = payload.get("type", "")
    workspace = payload.get("cwd", "")

    if zoom <= Zoom.MINIMAL:
        return content[:120] if content else f"[{record_type}]"

    p = current_palette()
    parts: list[Block] = []

    # Show record type as role indicator
    marker = "→" if record_type == "user" else "←"
    parts.append(Block.text(f"{marker} ", p.accent))
    parts.append(Block.text(content[:200] if content else "(empty)", Style()))

    if workspace and zoom >= Zoom.DETAILED:
        short_ws = workspace.rsplit("/", 1)[-1] if "/" in workspace else workspace
        parts.append(Block.text(f"  [{short_ws}]", p.muted))

    return join_horizontal(*parts)


def _tag_lens(payload: dict, zoom: Zoom) -> str | Block:
    """Render tag payload — label on a conversation."""
    name = payload.get("name", "")
    conv = payload.get("conversation_id", "")
    note = payload.get("note", "")

    if zoom <= Zoom.MINIMAL:
        return f"#{name}"

    p = current_palette()
    parts: list[Block] = [Block.text(f"#{name}", p.accent)]

    if conv:
        short = conv[:8]
        parts.append(Block.text(f" {short}", p.muted))

    if note and zoom >= Zoom.SUMMARY:
        parts.append(Block.text(f" — {note}", Style()))

    return join_horizontal(*parts)


# ---------------------------------------------------------------------------
# Status view — renders vertex_read fold state for siftd
# ---------------------------------------------------------------------------


def _format_date(ts: Any) -> str:
    """Format a timestamp as a short date (e.g. 'Feb 27')."""
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return ts[:10] if len(ts) >= 10 else ts
    else:
        return "?"
    return f"{dt.strftime('%b')} {dt.day}"


def status_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render siftd status from vertex_read fold state.

    data: {conversations: int, tags: int, observers: {name: count},
           recent: [{conversation_id, ts, model, prompt}]}

    Zoom levels:
    - MINIMAL: one-liner counts
    - SUMMARY: counts + observer breakdown + recent conversations
    - DETAILED: + recent prompts
    - FULL: + all metadata
    """
    conversations = data.get("conversations", 0)
    tags = data.get("tags", 0)
    observers = data.get("observers", {})
    recent = data.get("recent", [])

    if conversations == 0 and tags == 0:
        return Block.text("No siftd data yet.", Style(dim=True), width=width)

    # MINIMAL
    if zoom == Zoom.MINIMAL:
        parts = [f"{conversations} conversations"]
        if tags:
            parts.append(f"{tags} tags")
        return Block.text(" · ".join(parts), Style(), width=width)

    rows: list[Block] = []
    bold = Style(bold=True)
    dim = Style(dim=True)

    # Summary header
    rows.append(Block.text(f"Conversations ({conversations}):", bold, width=width))
    if observers:
        for obs, count in sorted(observers.items(), key=lambda kv: -kv[1]):
            rows.append(Block.text(f"  {obs}: {count}", Style(), width=width))

    # Tags
    if tags:
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text(f"Tags ({tags})", bold, width=width))

    # Recent conversations
    if recent and zoom >= Zoom.SUMMARY:
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text("Recent:", bold, width=width))
        for r in recent[:5]:
            date = _format_date(r.get("ts", ""))
            cid = r.get("conversation_id", "")[:8]
            if zoom >= Zoom.DETAILED:
                prompt = r.get("prompt", "")
                line = f"  {cid} ({date}) → {prompt}"
                if len(line) > width:
                    line = line[: width - 1] + "…"
                rows.append(Block.text(line, Style(), width=width))
            else:
                model = r.get("model", "")
                suffix = f" ({model})" if model else ""
                rows.append(Block.text(f"  {cid} ({date}){suffix}", Style(), width=width))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Log view — renders vertex_facts for siftd with domain-aware summaries
# ---------------------------------------------------------------------------


def log_view(facts: list[dict[str, Any]], zoom: Zoom, width: int) -> Block:
    """Render siftd log facts with domain-aware summaries.

    Uses siftd_lens for one-line summaries instead of generic key=value.
    """
    if not facts:
        return Block.text("No facts in the given time range.", Style(dim=True), width=width)

    if zoom == Zoom.MINIMAL:
        counts: dict[str, int] = {}
        for f in facts:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        parts = [f"{count} {kind}" for kind, count in counts.items()]
        return Block.text(", ".join(parts), Style(), width=width)

    rows: list[Block] = []
    dim = Style(dim=True)
    current_date = None

    for f in facts:
        ts = f["ts"]
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif isinstance(ts, datetime):
            dt = ts
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        else:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        if date_str != current_date:
            if current_date is not None:
                rows.append(Block.text("", Style(), width=width))
            rows.append(Block.text(f"{date_str}:", Style(bold=True), width=width))
            current_date = date_str

        time_str = dt.strftime("%H:%M")
        kind = f["kind"]
        payload = f.get("payload", {})
        summary = siftd_lens(kind, payload, zoom)

        # siftd_lens returns str or Block
        if isinstance(summary, Block):
            label = Block.text(f"  {time_str} [{kind}] ", Style(), width=0)
            row = join_horizontal(label, summary)
            rows.append(row)
        else:
            line = f"  {time_str} [{kind}] {summary}"
            if len(line) > width:
                line = line[: width - 1] + "…"
            rows.append(Block.text(line, Style(), width=width))

        # DETAILED+: show secondary fields
        if zoom >= Zoom.DETAILED and kind == "record":
            session_id = payload.get("sessionId", "")
            if session_id:
                rows.append(Block.text(f"           session: {session_id[:12]}", dim, width=width))

        if zoom >= Zoom.FULL:
            for key, val in payload.items():
                if val and key not in ("message", "type"):
                    val_str = str(val)
                    if len(val_str) > 80:
                        val_str = val_str[:77] + "..."
                    rows.append(Block.text(f"           {key}: {val_str}", dim, width=width))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Search view — renders vertex_search results
# ---------------------------------------------------------------------------


def search_view(results: list[dict[str, Any]], zoom: Zoom, width: int) -> Block:
    """Render search results — same shape as log but with match context."""
    if not results:
        return Block.text("No matches.", Style(dim=True), width=width)

    if zoom == Zoom.MINIMAL:
        return Block.text(f"{len(results)} matches", Style(), width=width)

    # Search results are facts — reuse log rendering
    return log_view(results, zoom, width)
