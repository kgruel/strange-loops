"""Sync lens — render SyncResult showing ran, skipped, and errors."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical

from .run import run_ticks_view, _format_ts


def sync_view(data: dict, zoom: Zoom, width: int) -> Block:
    """Render sync results.

    data keys: ticks, ran, skipped, errors
    """
    ran = data.get("ran", [])
    skipped = data.get("skipped", [])
    errors = data.get("errors", [])
    ticks = data.get("ticks", [])

    dim = Style(dim=True)
    bold = Style(bold=True)
    rows: list[Block] = []

    if zoom == Zoom.MINIMAL:
        parts = []
        if ran:
            parts.append(f"{len(ran)} ran")
        if skipped:
            parts.append(f"{len(skipped)} skipped")
        if errors:
            parts.append(f"{len(errors)} errors")
        if not parts:
            parts.append("nothing to sync")
        rows.append(Block.text(", ".join(parts), Style(), width=width))
        return join_vertical(*rows) if rows else Block.text("", Style())

    # SUMMARY and above: show ran/skipped/errors with increasing detail

    if ran:
        rows.append(Block.text(f"Ran: {', '.join(ran)}", Style(), width=width))
    if skipped:
        rows.append(Block.text(f"Skipped: {', '.join(skipped)}", dim, width=width))
    if errors:
        rows.append(Block.text(f"Errors: {len(errors)}", Style(fg="red"), width=width))
        if zoom >= Zoom.DETAILED:
            for err in errors:
                payload = err.get("payload", {})
                msg = payload.get("error", str(payload))
                rows.append(Block.text(f"  {msg}", Style(fg="red"), width=width))

    if not ran and not skipped and not errors:
        rows.append(Block.text("No sources configured.", dim, width=width))
        return join_vertical(*rows)

    # Tick rendering for SUMMARY and above
    if ticks:
        rows.append(Block.text("", Style(), width=width))
        rows.append(run_ticks_view(ticks, zoom, width))
    elif ran:
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text("No ticks fired.", dim, width=width))

    return join_vertical(*rows)
