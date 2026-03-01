"""Run lens — zoom-aware rendering for streaming facts and ticks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_vertical


def run_facts_view(data: list[dict], zoom: Zoom, width: int) -> Block:
    """Render a list of facts at the given zoom level.

    Each item: {kind, ts, payload, observer, origin}

    Zoom levels:
    - MINIMAL: [kind] per line
    - SUMMARY: [kind] {key_summary}
    - DETAILED: [kind] {full_payload}
    - FULL: all fields including observer, origin, ts
    """
    if not data:
        return Block.text("No facts.", Style(dim=True), width=width)

    rows: list[Block] = []
    dim_style = Style(dim=True)

    for fact in data:
        kind = fact.get("kind", "?")
        payload = fact.get("payload", {})

        if zoom == Zoom.MINIMAL:
            rows.append(Block.text(f"  [{kind}]", Style(), width=width))

        elif zoom == Zoom.SUMMARY:
            if isinstance(payload, dict) and payload:
                keys = ", ".join(f"{k}={v}" for k, v in list(payload.items())[:3])
                if len(payload) > 3:
                    keys += " ..."
                rows.append(Block.text(f"  [{kind}] {keys}", Style(), width=width))
            else:
                rows.append(Block.text(f"  [{kind}]", Style(), width=width))

        elif zoom == Zoom.DETAILED:
            rows.append(Block.text(f"  [{kind}] {payload}", Style(), width=width))

        else:  # FULL
            ts = fact.get("ts", "")
            observer = fact.get("observer", "")
            origin = fact.get("origin", "")
            rows.append(Block.text(f"  [{kind}] {payload}", Style(), width=width))
            meta = f"    ts={ts} observer={observer} origin={origin}"
            rows.append(Block.text(meta, dim_style, width=width))

    # Footer
    rows.append(Block.text("", Style(), width=width))
    rows.append(Block.text(
        f"--- {len(data)} facts ---", dim_style, width=width,
    ))

    return join_vertical(*rows)


def run_ticks_view(data: list[dict], zoom: Zoom, width: int) -> Block:
    """Render a list of ticks at the given zoom level.

    Each item: {name, ts, payload, origin}

    Zoom levels:
    - MINIMAL: tick: name per line
    - SUMMARY: [ts] tick: name (N keys)
    - DETAILED: tick with payload expansion
    - FULL: all fields
    """
    if not data:
        return Block.text("No ticks.", Style(dim=True), width=width)

    rows: list[Block] = []
    dim_style = Style(dim=True)

    for tick in data:
        name = tick.get("name", "?")
        payload = tick.get("payload", {})
        ts = tick.get("ts", "")

        if zoom == Zoom.MINIMAL:
            rows.append(Block.text(f"  tick: {name}", Style(), width=width))

        elif zoom == Zoom.SUMMARY:
            ts_str = _format_ts(ts)
            n_keys = len(payload) if isinstance(payload, dict) else 0
            rows.append(Block.text(
                f"  [{ts_str}] tick: {name} ({n_keys} keys)",
                Style(), width=width,
            ))

        elif zoom == Zoom.DETAILED:
            ts_str = _format_ts(ts)
            rows.append(Block.text(
                f"  [{ts_str}] tick: {name}", Style(bold=True), width=width,
            ))
            if isinstance(payload, dict):
                for k, v in payload.items():
                    rows.append(Block.text(f"    {k}: {v}", Style(), width=width))

        else:  # FULL
            ts_str = _format_ts(ts)
            origin = tick.get("origin", "")
            rows.append(Block.text(
                f"  [{ts_str}] tick: {name}", Style(bold=True), width=width,
            ))
            if isinstance(payload, dict):
                for k, v in payload.items():
                    rows.append(Block.text(f"    {k}: {v}", Style(), width=width))
            rows.append(Block.text(
                f"    origin={origin}", dim_style, width=width,
            ))

    # Footer
    rows.append(Block.text("", Style(), width=width))
    rows.append(Block.text(
        f"--- {len(data)} ticks ---", dim_style, width=width,
    ))

    return join_vertical(*rows)


def _format_ts(ts: Any) -> str:
    """Format a timestamp for display."""
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat(timespec="seconds")
    if isinstance(ts, datetime):
        return ts.isoformat(timespec="seconds")
    return str(ts) if ts else "?"
