"""Fold lens — zoom-aware rendering of collapsed vertex state."""
from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime, timezone

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


def _format_date(ts) -> str:
    """Format timestamp as short date (e.g. 'Feb 27')."""
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return ts[:10] if len(ts) >= 10 else ts
    elif isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        return "?"
    return f"{dt.strftime('%b')} {dt.day}"


def fold_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render fold data at the given zoom level.

    One generic renderer driven by section metadata (key_field, fold_type).
    No per-kind dispatch.

    width=None means unconstrained (no truncation, no padding) — used when
    piped, so ``loops identity fold --plain`` produces the exact text needed
    for system prompts and other consumers.

    Zoom levels:
    - MINIMAL: one-liner counts per kind
    - SUMMARY: key_field value as label + body snippet
    - DETAILED: + remaining non-key payload fields
    - FULL: + metadata (ts, observer, origin)
    """
    populated = [s for s in data.sections if s.items]
    if not populated:
        return Block.text("No data yet.", Style(dim=True), width=width)

    # MINIMAL: one-liner
    if zoom == Zoom.MINIMAL:
        parts = [f"{s.count} {s.kind}s" for s in populated]
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

        header = _section_header(s.kind, s.count, piped=piped)
        rows.append(Block.text(header, header_style, width=width))

        # Show observer attribution when items come from multiple observers
        observers = {item.observer for item in s.items if item.observer}
        show_observer = len(observers) > 1

        _render_items(rows, s.items, s.key_field, s.kind, zoom, fmt, dim_style, meta_style, width, show_observer=show_observer)

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
    items: tuple[FoldItem, ...],
    key_field: str | None,
    kind: str,
    zoom: Zoom,
    fmt,
    dim_style: Style,
    meta_style: Style,
    width: int | None,
    *,
    show_observer: bool = False,
) -> None:
    """Generic item renderer — key_field drives the label, everything else is detail.

    When key_field is set (from FoldBy declaration), use it as the primary label.
    Otherwise fall back to heuristic scan of common label fields.

    When show_observer is True, appends observer attribution to each item —
    activated when a section contains items from multiple observers (unscoped fold).
    """
    # Build ordered label-field priority list
    label_fields = _label_fields(key_field)

    for item in items:
        payload = item.payload
        label = _find_label(payload, label_fields, kind)
        used_label = _used_label_field(payload, label_fields)
        date = fmt(item.ts) if item.ts else ""

        # Observer suffix when multi-observer fold
        obs_suffix = f" ({item.observer})" if show_observer and item.observer else ""

        # SUMMARY: label + body snippet (first non-label payload field)
        # More useful than label + date — shows what the fold *contains*.
        body = _find_body(payload, used_label)
        if body:
            reserved = len(label) + len(obs_suffix) + 6  # "  label (obs): snippet"
            if width is not None:
                snippet = _truncate(body, width - reserved)
            else:
                snippet = body
            line = f"  {label}{obs_suffix}: {snippet}"
        elif date:
            line = f"  {label}{obs_suffix} ({date})"
        else:
            line = f"  {label}{obs_suffix}"
        rows.append(Block.text(line, Style(), width=width))

        # DETAILED: show remaining payload fields as continuation lines
        if zoom >= Zoom.DETAILED:
            skip = {used_label} if used_label else set()
            # Also skip the body field already shown in the summary line
            body_field = _find_body_field(payload, used_label)
            if body_field:
                skip = skip | {body_field}
            for k, v in payload.items():
                if k in skip or not v:
                    continue
                rows.append(Block.text(f"    {k}: {v}", dim_style, width=width))

        # FULL: show metadata fields (ts, observer, origin)
        if zoom >= Zoom.FULL:
            if date:
                rows.append(Block.text(f"    _ts: {fmt(item.ts)}", meta_style, width=width))
            if item.observer:
                rows.append(Block.text(f"    _observer: {item.observer}", meta_style, width=width))
            if item.origin:
                rows.append(Block.text(f"    _origin: {item.origin}", meta_style, width=width))


def _label_fields(key_field: str | None) -> tuple[str, ...]:
    """Build ordered label-field priority list from key_field."""
    base = ("topic", "name", "title", "summary", "message")
    if key_field is None:
        return base
    if key_field in base:
        # Promote key_field to front
        return (key_field,) + tuple(f for f in base if f != key_field)
    return (key_field,) + base


def _used_label_field(payload: dict, label_fields: tuple[str, ...]) -> str | None:
    """Return the field name actually used as the label, or None."""
    for lf in label_fields:
        if payload.get(lf):
            return lf
    return None


def _find_label(payload: dict, label_fields: tuple[str, ...], kind: str) -> str:
    """Extract the best label from a payload dict."""
    for lf in label_fields:
        val = payload.get(lf)
        if val:
            return str(val)
    # Fall back to first key with a value
    for k, v in payload.items():
        if v:
            return f"{k}: {v}"
    return kind


def _find_body(payload: dict, used_label: str | None) -> str | None:
    """Find the first non-label field value — the 'body' of the item."""
    skip = {used_label} if used_label else set()
    for k, v in payload.items():
        if k in skip or not v:
            continue
        return str(v)
    return None


def _find_body_field(payload: dict, used_label: str | None) -> str | None:
    """Return the field name of the body, or None."""
    skip = {used_label} if used_label else set()
    for k, v in payload.items():
        if k in skip or not v:
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
