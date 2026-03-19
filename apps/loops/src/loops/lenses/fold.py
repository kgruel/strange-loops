"""Fold lens — zoom-aware rendering of collapsed vertex state.

Metadata-driven rendering with namespace grouping, salience-based
windowing, and semantic palette. No per-kind dispatch.

Rendering strategy:
- "by" folds with namespaced keys: group by prefix, window by salience
- "by" folds without namespaces: flat list sorted by salience
- "collect" folds: chronological list

Salience = n (revision count) + inbound_refs (how many other items
reference this one). Items with salience > 1 surface at SUMMARY.
Small groups (≤ 5 items) always show all items.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from datetime import datetime, timezone

from painted import Block, Style, Zoom, join_vertical
from painted.palette import current_palette

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fold_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render fold data at the given zoom level."""
    populated = [s for s in data.sections if s.items]
    if not populated:
        return Block.text("No data yet.", Style(dim=True), width=width)

    # MINIMAL: one-liner
    if zoom == Zoom.MINIMAL:
        parts = [f"{s.count} {s.kind}s" for s in populated]
        if data.unfolded:
            loose = ", ".join(f"{c} {k}" for k, c in sorted(data.unfolded.items()))
            parts.append(f"unfolded: {loose}")
        return Block.text(", ".join(parts), Style(), width=width)

    # Compute inbound ref counts once across all sections
    inbound = _compute_inbound_refs(data)

    p = current_palette()
    header_style = Style(bold=True)
    dim_style = p.muted
    accent_style = p.accent
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date
    piped = width is None

    text_rows: list[tuple[str, Style]] = []
    for s in populated:
        if text_rows:
            text_rows.append(("", Style()))

        header = _section_header(s.kind, s.count, piped=piped)
        text_rows.append((header, header_style))

        observers = {item.observer for item in s.items if item.observer}
        show_observer = len(observers) > 1

        _render_section(
            text_rows,
            s,
            zoom,
            fmt,
            width,
            inbound=inbound,
            dim_style=dim_style,
            accent_style=accent_style,
            show_observer=show_observer,
        )

    if data.unfolded:
        text_rows.append(("", Style()))
        loose = ", ".join(f"{c} {k}" for k, c in sorted(data.unfolded.items()))
        text_rows.append((f"Unfolded: {loose}", dim_style))

    if piped:
        return Block.column(text_rows)
    return Block.column(text_rows, width=width)


# ---------------------------------------------------------------------------
# Section rendering — dispatches to grouped or flat
# ---------------------------------------------------------------------------


def _render_section(
    rows: list[tuple[str, Style]],
    section: FoldSection,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    dim_style: Style,
    accent_style: Style,
    show_observer: bool,
) -> None:
    """Render a section's items — grouped by namespace or flat."""
    is_by = section.fold_type == "by"

    if is_by and section.key_field and _has_namespaces(section.items, section.key_field):
        _render_grouped(
            rows, section.items, section.key_field, zoom, fmt, width,
            inbound=inbound, dim_style=dim_style, accent_style=accent_style,
            show_observer=show_observer,
        )
    else:
        _render_flat(
            rows, section.items, section.key_field, section.fold_type,
            zoom, fmt, width,
            inbound=inbound, dim_style=dim_style, accent_style=accent_style,
            show_observer=show_observer,
        )


# ---------------------------------------------------------------------------
# Namespace-grouped rendering (Strategy C)
# ---------------------------------------------------------------------------

_GROUP_SHOW_ALL_THRESHOLD = 5


def _render_grouped(
    rows: list[tuple[str, Style]],
    items: tuple[FoldItem, ...],
    key_field: str,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    dim_style: Style,
    accent_style: Style,
    show_observer: bool,
) -> None:
    """Render by-fold items grouped by namespace prefix."""
    groups = _group_by_namespace(items, key_field)

    # Sort groups by total salience (most-attended first)
    sorted_groups = sorted(
        groups.items(),
        key=lambda g: sum(_salience(i, key_field, inbound) for i in g[1]),
        reverse=True,
    )

    for ns, group_items in sorted_groups:
        # Group header
        group_label = f"{ns}/" if ns else "(ungrouped)"
        rows.append((f"  {group_label} ({len(group_items)})", Style(bold=True)))

        # Sort within group by salience
        sorted_items = sorted(
            group_items,
            key=lambda i: _salience(i, key_field, inbound),
            reverse=True,
        )

        # Window: show all if small group, else show salient items
        if len(sorted_items) <= _GROUP_SHOW_ALL_THRESHOLD:
            show_items = sorted_items
        else:
            show_items = [
                i for i in sorted_items
                if _salience(i, key_field, inbound) > 1
            ]
            # Always show at least one item per group
            if not show_items:
                show_items = sorted_items[:1]

        for item in show_items:
            _render_item(
                rows, item, key_field, zoom, fmt, width,
                inbound=inbound, dim_style=dim_style, accent_style=accent_style,
                show_observer=show_observer, indent=4, strip_namespace=True,
            )

        remaining = len(sorted_items) - len(show_items)
        if remaining > 0:
            rows.append((f"    ({remaining} more)", dim_style))


# ---------------------------------------------------------------------------
# Flat rendering (non-namespaced by-folds and collect folds)
# ---------------------------------------------------------------------------


def _render_flat(
    rows: list[tuple[str, Style]],
    items: tuple[FoldItem, ...],
    key_field: str | None,
    fold_type: str,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    dim_style: Style,
    accent_style: Style,
    show_observer: bool,
) -> None:
    """Render items as a flat list — sorted by salience for by-folds."""
    is_by = fold_type == "by"

    if is_by:
        sorted_items: tuple[FoldItem, ...] | list[FoldItem] = sorted(
            items,
            key=lambda i: _salience(i, key_field, inbound),
            reverse=True,
        )
    else:
        sorted_items = items

    for item in sorted_items:
        _render_item(
            rows, item, key_field, zoom, fmt, width,
            inbound=inbound, dim_style=dim_style, accent_style=accent_style,
            show_observer=show_observer, indent=2, strip_namespace=False,
            is_by=is_by,
        )


# ---------------------------------------------------------------------------
# Single item rendering
# ---------------------------------------------------------------------------


def _render_item(
    rows: list[tuple[str, Style]],
    item: FoldItem,
    key_field: str | None,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    dim_style: Style,
    accent_style: Style,
    show_observer: bool,
    indent: int = 2,
    strip_namespace: bool = False,
    is_by: bool = True,
) -> None:
    """Render a single fold item with salience indicators."""
    payload = item.payload
    pad = " " * indent

    if is_by and key_field:
        label = str(payload.get(key_field, ""))
        if strip_namespace and "/" in label:
            label = label.split("/", 1)[1]
        used_label_field = key_field
    else:
        label, used_label_field = _first_field(payload)

    date = fmt(item.ts) if item.ts else ""

    # Observer suffix
    obs_suffix = f" ({item.observer})" if show_observer and item.observer else ""

    # Salience indicators
    indicators = _format_indicators(item, key_field, inbound, is_by)

    # SUMMARY: label + body snippet
    body_field, body = _find_body_entry(payload, used_label_field)
    if body:
        reserved = len(pad) + len(label) + len(obs_suffix) + len(indicators) + 2
        if width is not None:
            snippet = _truncate(body, width - reserved)
        else:
            snippet = body
        line = f"{pad}{label}{obs_suffix}: {snippet}"
    elif date:
        line = f"{pad}{label}{obs_suffix} ({date})"
    else:
        line = f"{pad}{label}{obs_suffix}"

    if indicators:
        rows.append((line + " " + indicators, accent_style))
    else:
        rows.append((line, Style()))

    # DETAILED: remaining payload fields + outbound refs
    if zoom >= Zoom.DETAILED:
        detail_pad = pad + "  "
        if item.id:
            rows.append((f"{detail_pad}id:{item.id[:8]}", dim_style))
        skip = {used_label_field} if used_label_field else set()
        if body_field:
            skip.add(body_field)
        for k, v in payload.items():
            if k in skip or not v:
                continue
            rows.append((f"{detail_pad}{k}: {v}", dim_style))
        # Show outbound refs
        for ref in item.refs:
            rows.append((f"{detail_pad}→ {ref}", accent_style))

    # FULL: metadata fields
    if zoom >= Zoom.FULL:
        meta_pad = pad + "  "
        if item.id:
            rows.append((f"{meta_pad}_id: {item.id}", dim_style))
        if date:
            rows.append((f"{meta_pad}_ts: {fmt(item.ts)}", dim_style))
        if item.observer:
            rows.append((f"{meta_pad}_observer: {item.observer}", dim_style))
        if item.origin:
            rows.append((f"{meta_pad}_origin: {item.origin}", dim_style))
        if item.n > 1:
            rows.append((f"{meta_pad}_n: {item.n}", dim_style))
        ref_count = _inbound_count(item, key_field, inbound)
        if ref_count > 0:
            rows.append((f"{meta_pad}_inbound_refs: {ref_count}", dim_style))


# ---------------------------------------------------------------------------
# Salience computation
# ---------------------------------------------------------------------------


def _compute_inbound_refs(data: FoldState) -> Counter:
    """Count inbound references across all sections."""
    inbound: Counter = Counter()
    for section in data.sections:
        for item in section.items:
            for ref in item.refs:
                inbound[ref] += 1
    return inbound


def _salience(item: FoldItem, key_field: str | None, inbound: Counter) -> int:
    """Salience = n + inbound ref count."""
    return item.n + _inbound_count(item, key_field, inbound)


def _inbound_count(item: FoldItem, key_field: str | None, inbound: Counter) -> int:
    """Look up inbound ref count for this item."""
    if not key_field:
        return 0
    key = item.payload.get(key_field, "")
    if not key:
        return 0
    # Try both with and without section kind prefix
    # Refs use kind/key format, but we don't know our kind here
    # Check all possible ref forms
    count = 0
    for ref_key, ref_count in inbound.items():
        if ref_key.endswith(f"/{key}"):
            count += ref_count
    return count


def _format_indicators(
    item: FoldItem,
    key_field: str | None,
    inbound: Counter,
    is_by: bool,
) -> str:
    """Format salience indicators: ×N for revisions, ←N for inbound refs."""
    parts = []
    if is_by and item.n > 1:
        parts.append(f"×{item.n}")
    ref_count = _inbound_count(item, key_field, inbound)
    if ref_count > 0:
        parts.append(f"←{ref_count}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Namespace grouping
# ---------------------------------------------------------------------------


def _has_namespaces(items: tuple[FoldItem, ...], key_field: str) -> bool:
    """Check if items use namespaced keys (contain '/')."""
    for item in items:
        key = item.payload.get(key_field, "")
        if "/" in str(key):
            return True
    return False


def _group_by_namespace(
    items: tuple[FoldItem, ...], key_field: str
) -> dict[str, list[FoldItem]]:
    """Group items by namespace prefix (before first '/')."""
    groups: dict[str, list[FoldItem]] = defaultdict(list)
    for item in items:
        key = str(item.payload.get(key_field, ""))
        if "/" in key:
            ns = key.split("/", 1)[0]
        else:
            ns = ""
        groups[ns].append(item)
    return dict(groups)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _section_header(kind: str, count: int, *, piped: bool = False) -> str:
    if piped:
        return f"## {kind.upper()}"
    label = kind.title()
    if not kind.endswith("s"):
        label += "s"
    return f"{label} ({count}):"


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


def _format_ts_full(ts) -> str:
    """ISO timestamp for FULL zoom."""
    if isinstance(ts, str):
        return ts
    if isinstance(ts, datetime):
        return ts.isoformat(timespec="seconds")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    return "?"
