"""Fold lens — zoom-aware rendering of collapsed vertex state."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical

from ..commands.observer import _format_date


def fold_view(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
    """Render fold data at the given zoom level.

    One generic renderer driven by section metadata (key_field, fold_type).
    No per-kind dispatch.

    width=None means unconstrained (no truncation, no padding) — used when
    piped, so ``loops identity fold --plain`` produces the exact text needed
    for system prompts and other consumers.

    Zoom levels:
    - MINIMAL: one-liner counts per kind
    - SUMMARY: key_field value as label + body snippet
    - DETAILED: + remaining non-key, non-underscore payload fields
    - FULL: + metadata fields (_ts, _observer, _origin)
    """
    sections: list[dict] = data.get("sections", [])

    populated = [s for s in sections if s["items"]]
    if not populated:
        return Block.text("No data yet.", Style(dim=True), width=width)

    # MINIMAL: one-liner
    if zoom == Zoom.MINIMAL:
        parts = [f"{len(s['items'])} {s['kind']}s" for s in populated]
        return Block.text(", ".join(parts), Style(), width=width)

    piped = width is None
    rows: list[Block] = []
    header_style = Style(bold=True)
    dim_style = Style(dim=True)
    meta_style = Style(dim=True)
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    for s in populated:
        if rows:
            rows.append(Block.text("", Style(), width=width))

        kind = s["kind"]
        items = s["items"]
        key_field = s.get("key_field")
        header = _section_header(kind, len(items), piped=piped)
        rows.append(Block.text(header, header_style, width=width))

        _render_items(rows, items, key_field, kind, zoom, fmt, dim_style, meta_style, width)

    return join_vertical(*rows)


# --- Legacy alias ---
status_view = fold_view


_KNOWN_HEADERS: dict[str, str] = {
    "decision": "Decisions",
    "thread": "Threads",
    "task": "Tasks",
    "change": "Changes",
    "self": "Self",
    "principle": "Principles",
    "observation": "Observations",
    "intention": "Intentions",
}


def _section_header(kind: str, count: int, *, piped: bool = False) -> str:
    if piped:
        # Markdown-style headers for piped output — directly usable
        # as system prompts, notes, piped to other tools.
        return f"## {kind.upper()}"
    label = _KNOWN_HEADERS.get(kind, kind.title() + ("s" if kind[-1] != "s" else ""))
    return f"{label} ({count}):"


def _render_items(
    rows: list[Block],
    items: list,
    key_field: str | None,
    kind: str,
    zoom: Zoom,
    fmt,
    dim_style: Style,
    meta_style: Style,
    width: int | None,
) -> None:
    """Generic item renderer — key_field drives the label, everything else is detail.

    When key_field is set (from FoldBy declaration), use it as the primary label.
    Otherwise fall back to heuristic scan of common label fields.
    """
    # Build ordered label-field priority list
    label_fields = _label_fields(key_field)

    for item in items:
        label = _find_label(item, label_fields, kind)
        used_label = _used_label_field(item, label_fields)
        ts = item.get("_ts", item.get("ts", ""))
        date = fmt(ts) if ts else ""

        # SUMMARY: label + body snippet (first non-label payload field)
        # More useful than label + date — shows what the fold *contains*.
        body = _find_body(item, used_label)
        if body:
            if width is not None:
                snippet = _truncate(body, width - len(label) - 6)  # "  label: snippet"
            else:
                snippet = body
            line = f"  {label}: {snippet}"
        elif date:
            line = f"  {label} ({date})"
        else:
            line = f"  {label}"
        rows.append(Block.text(line, Style(), width=width))

        # DETAILED: show remaining payload fields as continuation lines
        if zoom >= Zoom.DETAILED:
            skip = {used_label, "_ts", "ts"} if used_label else {"_ts", "ts"}
            # Also skip the body field already shown in the summary line
            body_field = _find_body_field(item, used_label)
            if body_field:
                skip = skip | {body_field}
            for k, v in item.items():
                if k.startswith("_") or k in skip or not v:
                    continue
                rows.append(Block.text(f"    {k}: {v}", dim_style, width=width))

        # FULL: show metadata fields
        if zoom >= Zoom.FULL:
            if date:
                rows.append(Block.text(f"    _ts: {fmt(ts)}", meta_style, width=width))
            for k, v in item.items():
                if k.startswith("_") and k != "_ts" and v:
                    rows.append(Block.text(f"    {k}: {v}", meta_style, width=width))


def _label_fields(key_field: str | None) -> tuple[str, ...]:
    """Build ordered label-field priority list from key_field."""
    base = ("topic", "name", "title", "summary", "message")
    if key_field is None:
        return base
    if key_field in base:
        # Promote key_field to front
        return (key_field,) + tuple(f for f in base if f != key_field)
    return (key_field,) + base


def _used_label_field(item: dict, label_fields: tuple[str, ...]) -> str | None:
    """Return the field name actually used as the label, or None."""
    for lf in label_fields:
        if item.get(lf):
            return lf
    return None


def _find_label(item: dict, label_fields: tuple[str, ...], kind: str) -> str:
    """Extract the best label from an item dict."""
    for lf in label_fields:
        val = item.get(lf)
        if val:
            return str(val)
    # Fall back to first non-underscore key with a value
    for k, v in item.items():
        if not k.startswith("_") and v:
            return f"{k}: {v}"
    return kind


def _find_body(item: dict, used_label: str | None) -> str | None:
    """Find the first non-label, non-underscore field value — the 'body' of the item."""
    skip = {used_label, "_ts", "ts"} if used_label else {"_ts", "ts"}
    for k, v in item.items():
        if k.startswith("_") or k in skip or not v:
            continue
        return str(v)
    return None


def _find_body_field(item: dict, used_label: str | None) -> str | None:
    """Return the field name of the body, or None."""
    skip = {used_label, "_ts", "ts"} if used_label else {"_ts", "ts"}
    for k, v in item.items():
        if k.startswith("_") or k in skip or not v:
            continue
        return k
    return None


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if max_len < 10:
        max_len = 10
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


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
