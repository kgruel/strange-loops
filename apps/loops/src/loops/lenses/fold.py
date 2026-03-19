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

Palette maps information roles to styles:
- key: the primary identifier
- n_indicator: revision count (×N) — separate from ref for future scaling
- ref_indicator: inbound ref count (←N) — separate axis
- observer: secondary attribution
- body: subordinate content
- collapse/unfolded: background signals
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from datetime import datetime, timezone

from painted import Block, Style, Zoom, join_horizontal, join_vertical
from painted.palette import current_palette

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# ---------------------------------------------------------------------------
# Semantic palette — maps information roles to styles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FoldPalette:
    """Semantic styles for fold rendering.

    Each field maps an information role to a Style. Derived from the
    ambient painted palette by default. Separate entries for n and ref
    indicators allow independent scaling (e.g. heatmap intensity) in
    the future — they start similar but are conceptually different axes.
    """

    section_header: Style   # "Decisions (227):"
    group_header: Style     # "design/ (88)"
    key: Style              # "n-on-fold-item"
    n_indicator: Style      # "×4" — revision density
    ref_indicator: Style    # "←2" — structural importance
    observer: Style         # "(kyle/loops-claude)"
    body: Style             # message/body text
    collapse: Style         # "(83 more)"
    ref_arrow: Style        # "→ decision/auth"
    meta: Style             # metadata fields at FULL zoom
    unfolded: Style         # "Unfolded: 26 observation"


def _default_fold_palette() -> FoldPalette:
    """Build FoldPalette from the ambient painted palette."""
    p = current_palette()
    return FoldPalette(
        section_header=Style(bold=True),
        group_header=Style(bold=True),
        key=Style(),
        n_indicator=p.accent,
        ref_indicator=p.accent,
        observer=p.muted,
        body=p.muted,
        collapse=p.muted,
        ref_arrow=p.accent,
        meta=p.muted,
        unfolded=p.muted,
    )


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

    # Compute once for the whole render
    inbound = _compute_inbound_refs(data)
    fp = _default_fold_palette()
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    blocks: list[Block] = []
    for s in populated:
        if blocks:
            blocks.append(Block.text("", Style(), width=width))

        header = _section_header(s.kind, s.count, piped=width is None)
        blocks.append(Block.text(header, fp.section_header, width=width))

        observers = {item.observer for item in s.items if item.observer}
        show_observer = len(observers) > 1

        section_block = _render_section(
            s, zoom, fmt, width,
            inbound=inbound, fp=fp, show_observer=show_observer,
        )
        blocks.append(section_block)

    if data.unfolded:
        blocks.append(Block.text("", Style(), width=width))
        loose = ", ".join(f"{c} {k}" for k, c in sorted(data.unfolded.items()))
        blocks.append(Block.text(f"Unfolded: {loose}", fp.unfolded, width=width))

    return join_vertical(*blocks)


# ---------------------------------------------------------------------------
# Section rendering — dispatches to grouped or flat
# ---------------------------------------------------------------------------


def _render_section(
    section: FoldSection,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    fp: FoldPalette,
    show_observer: bool,
) -> Block:
    """Render a section's items — grouped by namespace or flat."""
    is_by = section.fold_type == "by"

    if is_by and section.key_field and _has_namespaces(section.items, section.key_field):
        return _render_grouped(
            section.items, section.key_field, zoom, fmt, width,
            inbound=inbound, fp=fp, show_observer=show_observer,
        )
    else:
        return _render_flat(
            section.items, section.key_field, section.fold_type,
            zoom, fmt, width,
            inbound=inbound, fp=fp, show_observer=show_observer,
        )


# ---------------------------------------------------------------------------
# Namespace-grouped rendering (Strategy C)
# ---------------------------------------------------------------------------

_GROUP_SHOW_ALL_THRESHOLD = 5


def _render_grouped(
    items: tuple[FoldItem, ...],
    key_field: str,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    fp: FoldPalette,
    show_observer: bool,
) -> Block:
    """Render by-fold items grouped by namespace prefix."""
    groups = _group_by_namespace(items, key_field)

    sorted_groups = sorted(
        groups.items(),
        key=lambda g: sum(_salience(i, key_field, inbound) for i in g[1]),
        reverse=True,
    )

    blocks: list[Block] = []
    for ns, group_items in sorted_groups:
        group_label = f"  {ns}/" if ns else "  (ungrouped)"
        blocks.append(Block.text(
            f"{group_label} ({len(group_items)})", fp.group_header, width=width
        ))

        sorted_items = sorted(
            group_items,
            key=lambda i: _salience(i, key_field, inbound),
            reverse=True,
        )

        if len(sorted_items) <= _GROUP_SHOW_ALL_THRESHOLD:
            show_items = sorted_items
        else:
            show_items = [
                i for i in sorted_items
                if _salience(i, key_field, inbound) > 1
            ]
            if not show_items:
                show_items = sorted_items[:1]

        for item in show_items:
            blocks.append(_render_item_line(
                item, key_field, zoom, fmt, width,
                inbound=inbound, fp=fp, show_observer=show_observer,
                indent=4, strip_namespace=True,
            ))

        remaining = len(sorted_items) - len(show_items)
        if remaining > 0:
            blocks.append(Block.text(
                f"    ({remaining} more)", fp.collapse, width=width
            ))

    return join_vertical(*blocks)


# ---------------------------------------------------------------------------
# Flat rendering (non-namespaced by-folds and collect folds)
# ---------------------------------------------------------------------------


def _render_flat(
    items: tuple[FoldItem, ...],
    key_field: str | None,
    fold_type: str,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    fp: FoldPalette,
    show_observer: bool,
) -> Block:
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

    blocks: list[Block] = []
    for item in sorted_items:
        blocks.append(_render_item_line(
            item, key_field, zoom, fmt, width,
            inbound=inbound, fp=fp, show_observer=show_observer,
            indent=2, strip_namespace=False, is_by=is_by,
        ))

    return join_vertical(*blocks) if blocks else Block.empty(0, 0)


# ---------------------------------------------------------------------------
# Single item rendering — Block composition for multi-style lines
# ---------------------------------------------------------------------------


def _render_item_line(
    item: FoldItem,
    key_field: str | None,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound: Counter,
    fp: FoldPalette,
    show_observer: bool,
    indent: int = 2,
    strip_namespace: bool = False,
    is_by: bool = True,
) -> Block:
    """Render a single fold item as a composed Block with multi-style."""
    payload = item.payload
    pad = " " * indent

    # Key
    if is_by and key_field:
        label = str(payload.get(key_field, ""))
        if strip_namespace and "/" in label:
            label = label.split("/", 1)[1]
        used_label_field = key_field
    else:
        label, used_label_field = _first_field(payload)

    # Indicators (before body, always visible)
    n_text = f" ×{item.n}" if is_by and item.n > 1 else ""
    ref_count = _inbound_count(item, key_field, inbound)
    ref_text = f" ←{ref_count}" if ref_count > 0 else ""

    # Observer
    obs_text = f" ({item.observer})" if show_observer and item.observer else ""

    # Body
    body_field, body = _find_body_entry(payload, used_label_field)
    date = fmt(item.ts) if item.ts else ""

    # Compose the line: pad + key + indicators + observer + separator + body
    # Layout: "    key ×4 ←2 (observer): body text…"
    prefix = f"{pad}{label}"
    separator = ": " if body else ""

    # Calculate available width for body
    fixed_len = len(prefix) + len(n_text) + len(ref_text) + len(obs_text) + len(separator)

    if body:
        if width is not None:
            body_budget = max(10, width - fixed_len)
            body_text = _truncate(body, body_budget)
        else:
            body_text = body
    elif date and not n_text and not ref_text:
        body_text = f"({date})"
        separator = " "
    else:
        body_text = ""

    # Build composed line with distinct styles per segment
    parts: list[Block] = [Block.text(f"{pad}{label}", fp.key)]

    if n_text:
        parts.append(Block.text(n_text, fp.n_indicator))
    if ref_text:
        parts.append(Block.text(ref_text, fp.ref_indicator))
    if obs_text:
        parts.append(Block.text(obs_text, fp.observer))
    if separator and body_text:
        parts.append(Block.text(separator, fp.body))
        parts.append(Block.text(body_text, fp.body))

    main_line = join_horizontal(*parts)

    # If width is set, ensure line fits
    if width is not None:
        from painted import truncate as block_truncate
        main_line = block_truncate(main_line, width)

    lines: list[Block] = [main_line]

    # DETAILED: remaining payload fields + outbound refs
    if zoom >= Zoom.DETAILED:
        detail_pad = " " * (indent + 2)
        if item.id:
            lines.append(Block.text(f"{detail_pad}id:{item.id[:8]}", fp.meta, width=width))
        skip = {used_label_field} if used_label_field else set()
        if body_field:
            skip.add(body_field)
        for k, v in payload.items():
            if k in skip or not v:
                continue
            lines.append(Block.text(f"{detail_pad}{k}: {v}", fp.meta, width=width))
        for ref in item.refs:
            lines.append(Block.text(f"{detail_pad}→ {ref}", fp.ref_arrow, width=width))

    # FULL: metadata
    if zoom >= Zoom.FULL:
        meta_pad = " " * (indent + 2)
        if item.id:
            lines.append(Block.text(f"{meta_pad}_id: {item.id}", fp.meta, width=width))
        if date:
            lines.append(Block.text(f"{meta_pad}_ts: {fmt(item.ts)}", fp.meta, width=width))
        if item.observer:
            lines.append(Block.text(f"{meta_pad}_observer: {item.observer}", fp.meta, width=width))
        if item.origin:
            lines.append(Block.text(f"{meta_pad}_origin: {item.origin}", fp.meta, width=width))
        if item.n > 1:
            lines.append(Block.text(f"{meta_pad}_n: {item.n}", fp.meta, width=width))
        if ref_count > 0:
            lines.append(Block.text(f"{meta_pad}_inbound_refs: {ref_count}", fp.meta, width=width))

    return join_vertical(*lines) if len(lines) > 1 else lines[0]


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
    count = 0
    for ref_key, ref_count in inbound.items():
        if ref_key.endswith(f"/{key}"):
            count += ref_count
    return count


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
