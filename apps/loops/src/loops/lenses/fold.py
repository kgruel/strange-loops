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
    header_style = Style(bold=True)
    dim_style = Style(dim=True)
    meta_style = Style(dim=True)
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    if piped:
        text_rows: list[tuple[str, Style]] = []
        for s in populated:
            if text_rows:
                text_rows.append(("", Style()))

            header = _section_header(s.kind, s.count, piped=True)
            text_rows.append((header, header_style))

            observers = {item.observer for item in s.items if item.observer}
            show_observer = len(observers) > 1
            _render_item_rows(
                text_rows,
                s.items,
                s.key_field,
                s.fold_type,
                zoom,
                fmt,
                dim_style,
                meta_style,
                None,
                show_observer=show_observer,
            )

        return Block.column(text_rows)

    rows: list[Block] = []
    for s in populated:
        if rows:
            rows.append(Block.text("", Style(), width=width))

        header = _section_header(s.kind, s.count, piped=False)
        rows.append(Block.text(header, header_style, width=width))

        # Show observer attribution when items come from multiple observers
        observers = {item.observer for item in s.items if item.observer}
        show_observer = len(observers) > 1

        item_rows: list[tuple[str, Style]] = []
        _render_item_rows(
            item_rows,
            s.items,
            s.key_field,
            s.fold_type,
            zoom,
            fmt,
            dim_style,
            meta_style,
            width,
            show_observer=show_observer,
        )
        rows.append(Block.column(item_rows, width=width))

    return join_vertical(*rows)


def _section_header(kind: str, count: int, *, piped: bool = False) -> str:
    if piped:
        return f"## {kind.upper()}"
    label = kind.title()
    if not kind.endswith("s"):
        label += "s"
    return f"{label} ({count}):"


def _render_item_rows(
    rows: list[tuple[str, Style]],
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

    # Sort by-fold items by observation count — most-touched first
    if is_by:
        sorted_items: tuple[FoldItem, ...] | list[FoldItem] = sorted(
            items, key=lambda i: i.n, reverse=True
        )
    else:
        sorted_items = items

    for item in sorted_items:
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

        # Observation count for items touched more than once
        n_suffix = f" ×{item.n}" if is_by and item.n > 1 else ""

        # SUMMARY: label + body snippet (first non-label payload field)
        body_field, body = _find_body_entry(payload, used_label_field)
        if body:
            reserved = len(label) + len(obs_suffix) + len(n_suffix) + 6
            if width is not None:
                snippet = _truncate(body, width - reserved)
            else:
                snippet = body
            line = f"  {label}{obs_suffix}: {snippet}"
        elif date:
            line = f"  {label}{obs_suffix} ({date})"
        else:
            line = f"  {label}{obs_suffix}"

        rows.append((line + n_suffix, Style()))

        # DETAILED: show remaining payload fields as continuation lines
        if zoom >= Zoom.DETAILED:
            # Show short ID for reference
            if item.id:
                rows.append((f"    id:{item.id[:8]}", meta_style))
            skip = {used_label_field} if used_label_field else set()
            # Also skip the body field already shown in the summary line
            if body_field:
                skip.add(body_field)
            for k, v in payload.items():
                if k in skip or not v:
                    continue
                rows.append((f"    {k}: {v}", dim_style))

        # FULL: show metadata fields (ts, observer, origin, n, full id)
        if zoom >= Zoom.FULL:
            if item.id:
                rows.append((f"    _id: {item.id}", meta_style))
            if date:
                rows.append((f"    _ts: {fmt(item.ts)}", meta_style))
            if item.observer:
                rows.append((f"    _observer: {item.observer}", meta_style))
            if item.origin:
                rows.append((f"    _origin: {item.origin}", meta_style))
            if item.n > 1:
                rows.append((f"    _n: {item.n}", meta_style))


def _first_field(payload: dict) -> tuple[str, str | None]:
    """Return (value, field_name) for the first non-empty payload field."""
    for k, v in payload.items():
        if v:
            return str(v), k
    return "?", None


def _find_body_entry(payload: dict, used_label_field: str | None) -> tuple[str | None, str | None]:
    """Return the first non-label payload field as (field_name, value)."""
    skip = {used_label_field} if used_label_field else set()
    for k, v in payload.items():
        if k in skip or not v:
            continue
        return k, str(v)
    return None, None


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
