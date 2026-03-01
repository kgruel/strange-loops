"""Project lenses — (data, zoom, width) -> Block."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted import Zoom
    from painted.block import Block


def project_status_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render project status data as a Block.

    data is {"total": N, "decisions": {...}, "threads": {...}, "plans": {...}, "completions": {...}}.
    Values are dicts of {group_key: fact_dict}.

    MINIMAL: `N facts, M decisions, K threads, J plans, L completions`
    SUMMARY: section headers + per-item topic/name + message + short date
    DETAILED: + observer attribution, + full message bodies
    FULL: + ISO timestamps, + all payload fields individually
    """
    from painted import Zoom
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    total = data["total"]
    decisions = data["decisions"]
    threads = data["threads"]
    plans = data["plans"]
    completions = data.get("completions", {})

    if zoom == Zoom.MINIMAL:
        parts = [f"{total} facts"]
        if decisions:
            parts.append(f"{len(decisions)} decisions")
        if threads:
            parts.append(f"{len(threads)} threads")
        if plans:
            parts.append(f"{len(plans)} plans")
        if completions:
            parts.append(f"{len(completions)} completions")
        return Block.text(", ".join(parts), p.muted)

    lines: list[Block] = [Block.text(f"Project — {total} facts", p.accent)]

    if decisions:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Decisions ({len(decisions)}):", p.accent))
        for topic, f in sorted(decisions.items()):
            lines.extend(_render_project_item(f, topic, "message", zoom, p))

    if threads:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Open Threads ({len(threads)}):", p.accent))
        for name, f in sorted(threads.items()):
            payload = f["payload"]
            msg = payload.get("message", "")
            status = payload.get("status", "")
            detail = msg or status
            lines.extend(_render_project_item(f, name, detail, zoom, p, is_detail_field=True))

    if plans:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Plans ({len(plans)}):", p.accent))
        for name, f in sorted(plans.items()):
            status = f["payload"].get("status", "")
            lines.extend(_render_project_item(f, name, status, zoom, p, is_detail_field=True))

    if completions:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Completions ({len(completions)}):", p.accent))
        for task_name, f in sorted(completions.items()):
            status = f["payload"].get("status", "")
            exit_code = f["payload"].get("exit_code", "")
            detail = f"{status} exit={exit_code}" if exit_code != "" else status
            lines.extend(_render_project_item(f, task_name, detail, zoom, p, is_detail_field=True))

    return join_vertical(*lines)


def _render_project_item(
    f: dict,
    label_name: str,
    display_value,
    zoom,
    p,
    *,
    is_detail_field: bool = False,
) -> "list[Block]":
    """Render a single project item at the given zoom level.

    Returns a list of Block lines.
    """
    from painted import Zoom
    from painted.block import Block

    dt = (
        f["ts"]
        if isinstance(f["ts"], datetime)
        else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
    )
    payload = f["payload"]
    obs = f.get("observer", "")

    # Build display value from payload if it's a message-type field
    if not is_detail_field:
        display_value = payload.get(display_value, "") if isinstance(display_value, str) else ""
        # For decisions, display_value key is "message"
        display_value = payload.get("message", "")

    if zoom >= Zoom.FULL:
        date_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        date_str = dt.strftime("%b %d")

    label = f"  {label_name}: {display_value}" if display_value else f"  {label_name}"

    lines: list[Block] = []

    if zoom >= Zoom.DETAILED and obs:
        lines.append(Block.text(f"{label} ({date_str}) [{obs}]", p.muted))
    else:
        lines.append(Block.text(f"{label} ({date_str})", p.muted))

    if zoom >= Zoom.FULL:
        # Show all payload fields individually
        for k, v in payload.items():
            if v is not None and v != "":
                lines.append(Block.text(f"      {k}={v}", p.muted))

    return lines


def project_log_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render project log data as a Block.

    data is {"facts": [...]}.
    Zoom handled by log_block_zoom.
    """
    from strange_loops.store import log_block_zoom

    return log_block_zoom(data["facts"], None, zoom)
