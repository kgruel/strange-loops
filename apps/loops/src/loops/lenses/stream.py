"""Stream lens — zoom-aware rendering of event history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_vertical


def _block(text: str, style: Style, width: int | None) -> Block:
    """Create a Block, respecting width=None (no truncation)."""
    if width is not None:
        return Block.text(text, style, width=width)
    return Block.text(text, style)


def stream_view(data: dict[str, Any] | list[dict[str, Any]], zoom: Zoom, width: int | None) -> Block:
    """Render event stream at the given zoom level.

    Accepts either:
    - New format: {"facts": [...], "fold_meta": {...}, "vertex": str}
    - Legacy format: list of fact dicts (backwards compat)

    Uses fold_meta key_field for summary labels when available,
    falls back to heuristic scan. No per-kind if-elif branches.

    Zoom levels:
    - MINIMAL: counts by kind
    - SUMMARY: time + kind + summary (key_field driven)
    - DETAILED: + secondary fields on next line
    - FULL: all payload fields
    """
    # Normalize input format
    if isinstance(data, dict):
        facts = data.get("facts", [])
        fold_meta = data.get("fold_meta", {})
    else:
        facts = data
        fold_meta = {}

    if not facts:
        return _block("No facts in the given time range.", Style(dim=True), width)

    # MINIMAL: just counts
    if zoom == Zoom.MINIMAL:
        counts: dict[str, int] = {}
        for f in facts:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        parts = [f"{count} {kind}" for kind, count in counts.items()]
        return _block(", ".join(parts), Style(), width)

    rows: list[Block] = []
    dim_style = Style(dim=True)
    id_style = Style(dim=True)
    current_date = None

    # Detect single-fact lookup (--id mode) — show full detail
    is_id_lookup = isinstance(data, dict) and "_id_lookup" in data

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
                rows.append(_block("", Style(), width))
            rows.append(_block(f"{date_str}:", Style(bold=True), width))
            current_date = date_str

        time_str = dt.strftime("%H:%M")
        kind_str = f["kind"]
        payload = f["payload"]
        fact_id = f.get("id", "")

        # Short ID suffix for DETAILED+, full for FULL or --id lookup
        id_suffix = ""
        if fact_id:
            if is_id_lookup or zoom >= Zoom.FULL:
                id_suffix = f" {fact_id}"
            elif zoom >= Zoom.DETAILED:
                id_suffix = f" {fact_id[:8]}"

        # Use fold_meta key_field for summary, fall back to heuristic
        key_field = fold_meta.get(kind_str, {}).get("key_field")
        summary = _stream_summary(payload, key_field)
        rows.append(_block(f"  {time_str} [{kind_str}] {summary}", Style(), width))

        # Show ID on a detail line when present
        if id_suffix:
            rows.append(_block(f"           id:{id_suffix.strip()}", id_style, width))

        if is_id_lookup or zoom >= Zoom.FULL:
            # --id lookup or FULL: show all fields — no truncation
            if f.get("observer"):
                rows.append(Block.text(f"           observer: {f['observer']}", dim_style))
            if f.get("origin"):
                rows.append(Block.text(f"           origin: {f['origin']}", dim_style))
            for key, val in payload.items():
                if val:
                    rows.append(Block.text(f"           {key}: {val}", dim_style))
        elif zoom >= Zoom.DETAILED:
            # DETAILED: show non-summary fields on next line
            summary_fields = _summary_fields(payload, key_field)
            for key, val in payload.items():
                if key in summary_fields or not val:
                    continue
                rows.append(_block(f"           {key}: {val}", dim_style, width))

    return join_vertical(*rows)


# --- Heuristic label fields (same priority as fold lens) ---
_LABEL_FIELDS = ("topic", "name", "title", "summary", "message")


def _stream_summary(payload: dict, key_field: str | None = None) -> str:
    """Build a one-line summary from a fact payload.

    Uses key_field from fold declaration when available, then heuristic
    scan of common label fields. Joins the primary label with the first
    secondary value for context (e.g. "topic: message").
    """
    # Build priority order
    if key_field and key_field not in _LABEL_FIELDS:
        fields = (key_field,) + _LABEL_FIELDS
    elif key_field:
        fields = (key_field,) + tuple(f for f in _LABEL_FIELDS if f != key_field)
    else:
        fields = _LABEL_FIELDS

    primary = None
    secondary = None
    for f in fields:
        val = payload.get(f, "")
        if val:
            if primary is None:
                primary = str(val)
            elif secondary is None:
                secondary = str(val)
                break

    if primary and secondary:
        return f"{primary}: {secondary}"
    if primary:
        return primary

    # Last resort: first non-empty field
    for key in ("topic", "name", "summary", "message"):
        if key in payload and payload[key]:
            return payload[key]
    return str(payload)


def _summary_fields(payload: dict, key_field: str | None = None) -> set[str]:
    """Return the set of field names used in the summary line."""
    if key_field and key_field not in _LABEL_FIELDS:
        fields = (key_field,) + _LABEL_FIELDS
    elif key_field:
        fields = (key_field,) + tuple(f for f in _LABEL_FIELDS if f != key_field)
    else:
        fields = _LABEL_FIELDS

    used = set()
    count = 0
    for f in fields:
        if payload.get(f):
            used.add(f)
            count += 1
            if count >= 2:
                break
    return used
