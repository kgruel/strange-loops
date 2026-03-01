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
    """
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    total = data["total"]
    decisions = data["decisions"]
    threads = data["threads"]
    plans = data["plans"]
    completions = data.get("completions", {})

    lines: list[Block] = [Block.text(f"Project — {total} facts", p.accent)]

    if decisions:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Decisions ({len(decisions)}):", p.accent))
        for topic, f in sorted(decisions.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            msg = f["payload"].get("message", "")
            label = f"  {topic}: {msg}" if msg else f"  {topic}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    if threads:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Open Threads ({len(threads)}):", p.accent))
        for name, f in sorted(threads.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            msg = f["payload"].get("message", "")
            status = f["payload"].get("status", "")
            detail = msg or status
            label = f"  {name}: {detail}" if detail else f"  {name}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    if plans:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Plans ({len(plans)}):", p.accent))
        for name, f in sorted(plans.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            status = f["payload"].get("status", "")
            label = f"  {name}: {status}" if status else f"  {name}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    if completions:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Completions ({len(completions)}):", p.accent))
        for task_name, f in sorted(completions.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            status = f["payload"].get("status", "")
            exit_code = f["payload"].get("exit_code", "")
            detail = f"{status} exit={exit_code}" if exit_code != "" else status
            label = f"  {task_name}: {detail}" if detail else f"  {task_name}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    return join_vertical(*lines)


def project_log_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render project log data as a Block.

    data is {"facts": [...]}.
    """
    from strange_loops.store import log_block

    return log_block(data["facts"])
