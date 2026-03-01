"""Status lens — zoom-aware rendering for session status."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical

from ..commands.session import _format_date


def status_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render status data at the given zoom level.

    data: {decisions: [{topic, message, ts}], threads: [{name, status, ts}],
           tasks: [{name, status, summary, ts}], changes: [{summary, files, ts}]}

    Zoom levels:
    - MINIMAL: one-liner counts
    - SUMMARY: topic/name lists with dates, no message bodies
    - DETAILED: topics with message bodies
    - FULL: + ISO timestamps instead of short dates
    """
    decisions = data["decisions"]
    threads = data["threads"]
    tasks = data["tasks"]
    changes = data["changes"]

    if not any([decisions, threads, tasks, changes]):
        return Block.text("No session data yet.", Style(dim=True), width=width)

    # MINIMAL: one-liner
    if zoom == Zoom.MINIMAL:
        parts = []
        if decisions:
            parts.append(f"{len(decisions)} decisions")
        if threads:
            parts.append(f"{len(threads)} threads")
        if tasks:
            parts.append(f"{len(tasks)} tasks")
        if changes:
            parts.append(f"{len(changes)} changes")
        return Block.text(", ".join(parts), Style(), width=width)

    rows: list[Block] = []
    header_style = Style(bold=True)
    dim_style = Style(dim=True)

    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    if decisions:
        rows.append(Block.text(f"Decisions ({len(decisions)}):", header_style, width=width))
        for d in decisions:
            date = fmt(d["ts"])
            if zoom >= Zoom.DETAILED:
                rows.append(Block.text(f"  {d['topic']} ({date})", Style(), width=width))
                if d["message"]:
                    rows.append(Block.text(f"    {d['message']}", dim_style, width=width))
            else:
                rows.append(Block.text(f"  {d['topic']} ({date})", Style(), width=width))

    if threads:
        if rows:
            rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text(f"Open Threads ({len(threads)}):", header_style, width=width))
        for t in threads:
            date = fmt(t["ts"])
            status = t.get("status", "")
            line = f"  {t['name']}: {status} ({date})" if status else f"  {t['name']} ({date})"
            rows.append(Block.text(line, Style(), width=width))

    if tasks:
        if rows:
            rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text(f"Active Tasks ({len(tasks)}):", header_style, width=width))
        for t in tasks:
            date = fmt(t["ts"])
            if zoom >= Zoom.DETAILED and t.get("summary"):
                rows.append(Block.text(f"  {t['name']}: {t['status']} ({date})", Style(), width=width))
                rows.append(Block.text(f"    {t['summary']}", dim_style, width=width))
            else:
                rows.append(Block.text(f"  {t['name']}: {t['status']} ({date})", Style(), width=width))

    if changes:
        if rows:
            rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text(f"Recent Changes ({len(changes)}):", header_style, width=width))
        for c in changes:
            date = fmt(c["ts"])
            rows.append(Block.text(f"  {c['summary']} ({date})", Style(), width=width))
            if zoom >= Zoom.DETAILED and c.get("files"):
                rows.append(Block.text(f"    files: {c['files']}", dim_style, width=width))

    return join_vertical(*rows)


def _format_ts_full(ts) -> str:
    """ISO timestamp for FULL zoom."""
    from datetime import datetime, timezone

    if isinstance(ts, str):
        return ts
    if isinstance(ts, datetime):
        return ts.isoformat(timespec="seconds")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    return "?"
