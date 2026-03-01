"""Log lens — zoom-aware rendering for log facts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_vertical


def log_view(facts: list[dict[str, Any]], zoom: Zoom, width: int) -> Block:
    """Render log facts at the given zoom level.

    facts: [{kind, ts, payload, observer, origin}, ...]

    Zoom levels:
    - MINIMAL: counts by kind
    - SUMMARY: time + kind + kind-aware summary (no key= prefixes)
    - DETAILED: summary + secondary fields on next line
    - FULL: all payload fields
    """
    if not facts:
        return Block.text("No facts in the given time range.", Style(dim=True), width=width)

    # MINIMAL: just counts
    if zoom == Zoom.MINIMAL:
        counts: dict[str, int] = {}
        for f in facts:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        parts = [f"{count} {kind}" for kind, count in counts.items()]
        return Block.text(", ".join(parts), Style(), width=width)

    rows: list[Block] = []
    dim_style = Style(dim=True)
    current_date = None

    for f in facts:
        ts = f["ts"]
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        date_str = dt.strftime("%Y-%m-%d")
        if date_str != current_date:
            if current_date is not None:
                rows.append(Block.text("", Style(), width=width))
            rows.append(Block.text(f"{date_str}:", Style(bold=True), width=width))
            current_date = date_str

        time_str = dt.strftime("%H:%M")
        kind_str = f["kind"]
        payload = f["payload"]

        summary = _log_summary(kind_str, payload)
        rows.append(Block.text(f"  {time_str} [{kind_str}] {summary}", Style(), width=width))

        # DETAILED+: show secondary fields on next line
        if zoom >= Zoom.DETAILED:
            extras = []
            if kind_str == "change" and payload.get("files"):
                extras.append(f"files: {payload['files']}")
            if kind_str == "task" and payload.get("summary"):
                extras.append(payload["summary"])
            if extras:
                for extra in extras:
                    rows.append(Block.text(f"           {extra}", dim_style, width=width))

        # FULL: dump all payload fields
        if zoom >= Zoom.FULL:
            for key, val in payload.items():
                if val:
                    rows.append(Block.text(f"           {key}: {val}", dim_style, width=width))

    return join_vertical(*rows)


def _log_summary(kind: str, payload: dict) -> str:
    """Kind-aware one-line summary for a log fact.

    Instead of dumping all key=value pairs, format based on the kind
    so the output reads naturally.
    """
    topic = payload.get("topic", "")
    name = payload.get("name", "")
    summary = payload.get("summary", "")
    message = payload.get("message", "")
    status = payload.get("status", "")

    if kind == "decision":
        return f"{topic}: {message}" if message else topic or str(payload)
    if kind == "thread":
        return f"{name} [{status}]" if status else name or str(payload)
    if kind == "task":
        parts = [name]
        if status:
            parts.append(f"[{status}]")
        if summary:
            parts.append(summary)
        return " ".join(parts) if parts else str(payload)
    if kind == "change":
        return summary or str(payload)
    if kind == "notes":
        return message or str(payload)

    # Fallback: first meaningful field
    for key in ("topic", "name", "summary", "message"):
        if key in payload and payload[key]:
            return payload[key]
    return str(payload)
