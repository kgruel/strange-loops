"""Run lens — zoom-aware rendering for streaming facts and ticks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_vertical


def _block(text: str, style: Style, width: int | None) -> Block:
    """Create a Block, respecting width=None (no truncation)."""
    if width is not None:
        return Block.text(text, style, width=width)
    return Block.text(text, style)


def run_facts_view(data: list[dict], zoom: Zoom, width: int | None) -> Block:
    """Render a list of facts at the given zoom level.

    Each item: {kind, ts, payload, observer, origin}

    Zoom levels:
    - MINIMAL: [kind] per line
    - SUMMARY: [kind] {key_summary}
    - DETAILED: [kind] {full_payload}
    - FULL: all fields including observer, origin, ts
    """
    if not data:
        return _block("No facts.", Style(dim=True), width)

    rows: list[Block] = []
    dim_style = Style(dim=True)

    for fact in data:
        kind = fact.get("kind", "?")
        payload = fact.get("payload", {})

        if zoom == Zoom.MINIMAL:
            rows.append(_block(f"  [{kind}]", Style(), width))

        elif zoom == Zoom.SUMMARY:
            if isinstance(payload, dict) and payload:
                keys = ", ".join(f"{k}={v}" for k, v in list(payload.items())[:3])
                if len(payload) > 3:
                    keys += " ..."
                rows.append(_block(f"  [{kind}] {keys}", Style(), width))
            else:
                rows.append(_block(f"  [{kind}]", Style(), width))

        elif zoom == Zoom.DETAILED:
            rows.append(_block(f"  [{kind}] {payload}", Style(), width))

        else:  # FULL
            ts = fact.get("ts", "")
            observer = fact.get("observer", "")
            origin = fact.get("origin", "")
            rows.append(_block(f"  [{kind}] {payload}", Style(), width))
            meta = f"    ts={ts} observer={observer} origin={origin}"
            rows.append(_block(meta, dim_style, width))

    # Footer
    rows.append(_block("", Style(), width))
    rows.append(_block(f"--- {len(data)} facts ---", dim_style, width))

    return join_vertical(*rows)


def run_ticks_view(data: list[dict], zoom: Zoom, width: int | None) -> Block:
    """Render a list of ticks at the given zoom level.

    Each item: {name, ts, payload, origin}

    Zoom levels:
    - MINIMAL: tick: name per line
    - SUMMARY: [ts] tick: name (N keys)
    - DETAILED: tick with payload expansion
    - FULL: all fields
    """
    if not data:
        return _block("No ticks.", Style(dim=True), width)

    rows: list[Block] = []
    dim_style = Style(dim=True)

    for tick in data:
        name = tick.get("name", "?")
        payload = tick.get("payload", {})
        ts = tick.get("ts", "")

        if zoom == Zoom.MINIMAL:
            rows.append(_block(f"  tick: {name}", Style(), width))

        elif zoom == Zoom.SUMMARY:
            ts_str = _format_ts(ts)
            n_keys = len(payload) if isinstance(payload, dict) else 0
            rows.append(_block(
                f"  [{ts_str}] tick: {name} ({n_keys} keys)", Style(), width,
            ))

        elif zoom == Zoom.DETAILED:
            ts_str = _format_ts(ts)
            rows.append(_block(
                f"  [{ts_str}] tick: {name}", Style(bold=True), width,
            ))
            if isinstance(payload, dict):
                for k, v in payload.items():
                    rows.append(_block(f"    {k}: {v}", Style(), width))

        else:  # FULL
            ts_str = _format_ts(ts)
            origin = tick.get("origin", "")
            rows.append(_block(
                f"  [{ts_str}] tick: {name}", Style(bold=True), width,
            ))
            if isinstance(payload, dict):
                for k, v in payload.items():
                    rows.append(_block(f"    {k}: {v}", Style(), width))
            rows.append(_block(f"    origin={origin}", dim_style, width))

    # Footer
    rows.append(_block("", Style(), width))
    rows.append(_block(f"--- {len(data)} ticks ---", dim_style, width))

    return join_vertical(*rows)


def _format_ts(ts: Any) -> str:
    """Format a timestamp for display."""
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat(timespec="seconds")
    if isinstance(ts, datetime):
        return ts.isoformat(timespec="seconds")
    return str(ts) if ts else "?"
