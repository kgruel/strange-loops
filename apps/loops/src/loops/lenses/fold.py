"""Fold lens — zoom-aware rendering of collapsed vertex state.

Generic defaults: simple, not smart. Driven by section metadata
(key_field, fold_type). Counts, labels, bodies, progressive zoom.
If a domain needs more, write a custom lens.
"""
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

        _render_items(rows, s.items, s.key_field, s.fold_type, zoom, fmt, dim_style, meta_style, width, show_observer=show_observer)

    return join_vertical(*rows)


# --- Legacy alias ---
status_view = fold_view


def _section_header(kind: str, count: int, *, piped: bool = False) -> str:
    if piped:
        return f"## {kind.upper()}"
    label = kind.title()
    if not kind.endswith("s"):
        label += "s"
    return f"{label} ({count}):"


def _render_items(
    rows: list[Block],
    items: tuple[FoldItem, ...],
    key_field: str | None,
    fold_type: str,
    zoom: Zoom,
    fmt,
    dim_style: Style,
    meta_style: Style,
    width: int | None,
    *,
    show_observer: bool = False,
) -> None:
    """Generic item renderer — metadata-driven.

    "by" folds: key_field drives the label, remaining fields are body/detail.
    "collect" folds: no key promotion, render content from first payload field.

    When show_observer is True, appends observer attribution to each item —
    activated when a section contains items from multiple observers.
    """
    is_by = fold_type == "by"

    for item in items:
        payload = item.payload
        if is_by and key_field:
            label = str(payload.get(key_field, ""))
            used_label_field = key_field
        else:
            # collect folds or missing key_field: first non-empty field
            label, used_label_field = _first_field(payload)

        date = fmt(item.ts) if item.ts else ""

        # Observer suffix when multi-observer fold
        obs_suffix = f" ({item.observer})" if show_observer and item.observer else ""

        # SUMMARY: label + body snippet (first non-label payload field)
        body = _find_body(payload, used_label_field)
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
            # Show short ID for reference
            if item.id:
                rows.append(Block.text(f"    id:{item.id[:8]}", meta_style, width=width))
            skip = {used_label_field} if used_label_field else set()
            # Also skip the body field already shown in the summary line
            body_field = _find_body_field(payload, used_label_field)
            if body_field:
                skip = skip | {body_field}
            for k, v in payload.items():
                if k in skip or not v:
                    continue
                rows.append(Block.text(f"    {k}: {v}", dim_style, width=width))

        # FULL: show metadata fields (ts, observer, origin, full id)
        if zoom >= Zoom.FULL:
            if item.id:
                rows.append(Block.text(f"    _id: {item.id}", meta_style, width=width))
            if date:
                rows.append(Block.text(f"    _ts: {fmt(item.ts)}", meta_style, width=width))
            if item.observer:
                rows.append(Block.text(f"    _observer: {item.observer}", meta_style, width=width))
            if item.origin:
                rows.append(Block.text(f"    _origin: {item.origin}", meta_style, width=width))


def _first_field(payload: dict) -> tuple[str, str | None]:
    """Return (value, field_name) for the first non-empty payload field."""
    for k, v in payload.items():
        if v:
            return str(v), k
    return "?", None


def _find_body(payload: dict, used_label_field: str | None) -> str | None:
    """Find the first non-label field value — the 'body' of the item."""
    skip = {used_label_field} if used_label_field else set()
    for k, v in payload.items():
        if k in skip or not v:
            continue
        return str(v)
    return None


def _find_body_field(payload: dict, used_label_field: str | None) -> str | None:
    """Return the field name of the body, or None."""
    skip = {used_label_field} if used_label_field else set()
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
    return text[: max_len - 1] + "\u2026"


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
