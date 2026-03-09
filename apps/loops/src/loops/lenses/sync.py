"""Sync lens — render SyncResult showing ran, skipped, errors, and fact counts."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical

from .run import run_ticks_view, _format_ts


def _fact_label(count: int) -> str:
    return "1 fact" if count == 1 else f"{count} facts"


def sync_view(data: dict, zoom: Zoom, width: int) -> Block:
    """Render sync results.

    data keys: ticks, ran, skipped, errors, fact_counts, children (aggregation only)
    """
    ran = data.get("ran", [])
    skipped = data.get("skipped", [])
    errors = data.get("errors", [])
    ticks = data.get("ticks", [])
    fact_counts = data.get("fact_counts", {})
    children = data.get("children", [])

    dim = Style(dim=True)
    bold = Style(bold=True)
    rows: list[Block] = []
    total_facts = sum(fact_counts.values())

    if zoom == Zoom.MINIMAL:
        parts = []
        if total_facts:
            parts.append(_fact_label(total_facts))
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

    # SUMMARY and above: show ran/skipped/errors with fact counts

    if children:
        # Aggregation vertex: per-child breakdown
        for child in children:
            child_name = child["name"]
            child_ran = child.get("ran", [])
            child_skipped = child.get("skipped", [])
            child_counts = child.get("fact_counts", {})
            child_total = sum(child_counts.values())

            if child_ran:
                kinds_str = ", ".join(child_ran)
                rows.append(Block.text(
                    f"{child_name}: {_fact_label(child_total)} ({kinds_str})",
                    Style(), width=width,
                ))
            elif child_skipped:
                rows.append(Block.text(
                    f"{child_name}: skipped ({', '.join(child_skipped)})",
                    dim, width=width,
                ))

        if total_facts:
            rows.append(Block.text(f"Total: {_fact_label(total_facts)}", dim, width=width))
    else:
        # Instance vertex: per-source with counts
        if ran:
            parts = []
            for kind in ran:
                count = fact_counts.get(kind, 0)
                parts.append(f"{kind} ({count})")
            rows.append(Block.text(f"Ran: {', '.join(parts)}", Style(), width=width))
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
