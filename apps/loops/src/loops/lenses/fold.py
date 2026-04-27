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
    ref_indicator: Style    # "←2" — structural importance (inbound)
    ref_outbound: Style     # "→2" — outbound refs (dimmer)
    observer: Style         # "(kyle/loops-claude)"
    body: Style             # message/body text
    collapse: Style         # "(83 more)"
    ref_edge_in: Style      # "← decision/auth" — inbound edge expansion
    ref_edge_out: Style     # "→ decision/auth" — outbound edge expansion
    meta: Style             # metadata fields at FULL zoom
    unfolded: Style         # "Unfolded: 26 observation"
    stale_indicator: Style  # "⊘" — open-but-untouched (>7d) work items


def _default_fold_palette() -> FoldPalette:
    """Build FoldPalette from the ambient painted palette."""
    p = current_palette()
    # Body: not white, not dim — a middle ground (256-color 252 = light gray)
    body_style = Style(fg=252)
    return FoldPalette(
        section_header=Style(bold=True),
        group_header=Style(bold=True),
        key=Style(),
        n_indicator=p.accent,             # cyan — revision density
        ref_indicator=Style(fg="yellow"), # yellow — inbound importance (badge ←N)
        ref_outbound=Style(fg=179),       # muted gold — outbound count (badge →N)
        observer=p.muted,
        body=body_style,
        collapse=p.muted,
        ref_edge_in=Style(fg="yellow"),   # yellow — inbound edges (← source)
        ref_edge_out=Style(fg=245),       # gray — outbound edges (→ target), dimmer
        meta=p.muted,
        unfolded=p.muted,
        stale_indicator=Style(fg=208),    # orange — stale-open work (peer to ✦/◦, not escalation)
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fold_view(
    data: FoldState, zoom: Zoom, width: int | None,
    *, vertex_name: str | None = None, vertex_path: str | None = None,
    visible: frozenset[str] = frozenset(),
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render fold data at the given zoom level.

    visible gates which concern layers are rendered:
      - "refs": show per-item edge expansion (← inbound, → outbound)

    Density budgets (0 = unlimited):
      lines: max items shown per section/group. Items beyond the budget
             collapse into "(N more)" footers. Salience ordering applies first.
      chars: max display width for body text. Caps the body budget that
             width-based truncation already enforces — useful for context-
             window economics where total tokens matter more than terminal fit.
    """
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
    inbound_edges = _compute_inbound_edges(data) if "refs" in visible else {}
    facts_by_key = data.source_facts if "facts" in visible else {}
    fp = _default_fold_palette()
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    refs_filter = "refs" in visible
    facts_filter = "facts" in visible
    blocks: list[Block] = []
    skipped_sections: list[tuple[str, int]] = []

    for s in populated:
        display_count = s.count

        # When --refs is active, count connected items and track disconnected
        if refs_filter:
            connected_count = sum(
                1 for i in s.items
                if i.refs or _item_full_key(i, s.key_field, s.kind) in inbound_edges
            )
            disconnected = s.count - connected_count
            if connected_count == 0:
                skipped_sections.append((s.kind, s.count))
                continue
            elif disconnected > 0:
                skipped_sections.append((s.kind, disconnected))
            display_count = connected_count

        # When --facts is active, minimize sections without compression history
        # Collect folds and by-folds where no item has n>1 have nothing to drill into
        if facts_filter:
            has_history = s.fold_type == "by" and any(i.n > 1 for i in s.items)
            if not has_history:
                skipped_sections.append((s.kind, s.count))
                continue

        if blocks:
            blocks.append(Block.text("", Style(), width=width))

        header = _section_header(s.kind, display_count, piped=width is None)
        blocks.append(Block.text(header, fp.section_header, width=width))

        observers = {item.observer for item in s.items if item.observer}
        show_observer = len(observers) > 1

        section_block = _render_section(
            s, zoom, fmt, width,
            inbound=inbound, inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            lines=lines, chars=chars,
        )
        blocks.append(section_block)

    # Footer: skipped sections + unfolded kinds
    footer_parts: list[str] = []
    if skipped_sections:
        parts = [f"{count} {kind}" for kind, count in skipped_sections]
        # skipped_sections only populates via refs_filter or facts_filter paths
        if refs_filter and facts_filter:
            label = "Filtered"
        elif refs_filter:
            label = "No refs"
        else:
            label = "No history"
        footer_parts.append(f"{label}: {', '.join(parts)}")
    if data.unfolded:
        loose = ", ".join(f"{c} {k}" for k, c in sorted(data.unfolded.items()))
        footer_parts.append(f"Unfolded: {loose}")
    if footer_parts:
        blocks.append(Block.text("", Style(), width=width))
        blocks.append(Block.text(
            "  ".join(footer_parts), fp.unfolded, width=width,
        ))

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
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render a section's items — grouped by namespace or flat."""
    is_by = section.fold_type == "by"

    if is_by and section.key_field and _has_namespaces(section.items, section.key_field):
        return _render_grouped(
            section.items, section.key_field, zoom, fmt, width,
            inbound=inbound, inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            section_kind=section.kind,
            lines=lines, chars=chars,
        )
    else:
        return _render_flat(
            section.items, section.key_field, section.fold_type,
            zoom, fmt, width,
            inbound=inbound, inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            section_kind=section.kind,
            lines=lines, chars=chars,
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
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    section_kind: str = "",
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render by-fold items grouped by namespace prefix."""
    # When --refs is active, filter to only connected items
    # (fold_view already skips fully-disconnected sections, so items is non-empty)
    if "refs" in visible:
        items = tuple(
            i for i in items
            if i.refs or _item_full_key(i, key_field, section_kind) in inbound_edges
        )

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

        # When --refs is active, show all connected items (refs filter already reduced the set).
        # Otherwise, apply salience windowing.
        if "refs" in visible:
            show_items = sorted_items
        elif len(sorted_items) <= _GROUP_SHOW_ALL_THRESHOLD:
            show_items = sorted_items
        else:
            show_items = [
                i for i in sorted_items
                if _salience(i, key_field, inbound) > 1
            ]
            if not show_items:
                show_items = sorted_items[:1]

        # Apply lines budget (highest-salience kept; rest collapse to "more")
        if lines > 0 and len(show_items) > lines:
            show_items = list(show_items)[:lines]

        for item in show_items:
            blocks.append(_render_item_line(
                item, key_field, zoom, fmt, width,
                inbound=inbound, inbound_edges=inbound_edges,
                facts_by_key=facts_by_key,
                fp=fp, show_observer=show_observer, visible=visible,
                indent=4, strip_namespace=True, section_kind=section_kind,
                chars=chars,
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
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    section_kind: str = "",
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render items as a flat list — sorted by salience for by-folds."""
    is_by = fold_type == "by"

    # When --refs is active, filter to only connected items
    # (fold_view already skips fully-disconnected sections, so items is non-empty)
    if "refs" in visible and is_by:
        items = tuple(
            i for i in items
            if i.refs or _item_full_key(i, key_field, section_kind) in inbound_edges
        )

    if is_by:
        sorted_items: tuple[FoldItem, ...] | list[FoldItem] = sorted(
            items,
            key=lambda i: _salience(i, key_field, inbound),
            reverse=True,
        )
    else:
        sorted_items = items

    # Apply lines budget (highest-salience first for by-folds; chronological
    # head for collect folds — both surface the most-relevant first)
    total = len(sorted_items)
    if lines > 0 and total > lines:
        sorted_items = list(sorted_items)[:lines]

    blocks: list[Block] = []
    for item in sorted_items:
        blocks.append(_render_item_line(
            item, key_field, zoom, fmt, width,
            inbound=inbound, inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            indent=2, strip_namespace=False, is_by=is_by, section_kind=section_kind,
            chars=chars,
        ))

    remaining = total - len(sorted_items)
    if remaining > 0:
        blocks.append(Block.text(
            f"  ({remaining} more)", fp.collapse, width=width,
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
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    indent: int = 2,
    strip_namespace: bool = False,
    is_by: bool = True,
    section_kind: str = "",
    chars: int = 0,
) -> Block:
    """Render a single fold item as a composed Block with multi-style.

    SUMMARY layout: key [×N ←N →N recency]: body… [+Nc]
    DETAILED adds:  observer, remaining payload fields
    +refs:          per-item edge expansion (← inbound sources, → outbound targets)
    +facts:         source facts that built this fold item
    FULL adds:      all metadata (_id, _ts, _observer, _origin, _n, _inbound_refs)
    """
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
    ref_in_text = f" ←{ref_count}" if ref_count > 0 else ""
    ref_out_text = f" →{len(item.refs)}" if item.refs else ""

    # Recency tag
    recency_text = ""
    if item.ts:
        recency_text = f" {_recency_tag(item.ts)}"

    # Body
    body_field, body = _find_body_entry(payload, used_label_field)

    # Truncation hint: show character count when body is truncated
    body_len = len(body) if body else 0
    separator = ": " if body else ""

    # Calculate available width for body (reserve space for badge + truncation hint)
    # Badge: " [" + indicators + "]" = 3 chars + content
    badge_content_len = (
        len(n_text.lstrip()) + len(ref_in_text.lstrip())
        + len(ref_out_text.lstrip()) + len(recency_text.lstrip())
    )
    # Add spaces between badge parts
    badge_part_count = sum(1 for x in [n_text, ref_in_text, ref_out_text, recency_text] if x)
    badge_len = (3 + badge_content_len + max(0, badge_part_count - 1)) if badge_part_count else 0
    fixed_len = len(pad) + len(label) + badge_len + len(separator)
    truncation_hint = ""

    if body:
        # Per-body chars budget: caps width-based budget, or stands alone when piped.
        # Width-based truncation already accounts for badge/label fixed length;
        # chars further constrains body text directly.
        if width is not None:
            # Reserve space for potential truncation hint " [+NNNc]"
            hint_reserve = 10
            body_budget = max(10, width - fixed_len - hint_reserve)
            if chars > 0:
                body_budget = min(body_budget, chars)
            if body_len > body_budget:
                body_text = _truncate(body, body_budget)
                truncation_hint = f" [+{body_len - body_budget}c]"
            else:
                body_text = body
        else:
            if chars > 0 and body_len > chars:
                body_text = _truncate(body, chars)
                truncation_hint = f" [+{body_len - chars}c]"
            else:
                body_text = body
    elif item.ts and not n_text and not ref_in_text:
        body_text = ""
    else:
        body_text = ""

    # Build composed line with distinct styles per segment
    # SUMMARY: key [×N ←N recency]: body… [+Nc]
    parts: list[Block] = [Block.text(f"{pad}{label}", fp.key)]

    # Metadata badge: [×N ←N →N recency] — always present (at minimum recency)
    badge_parts: list[Block] = []
    if n_text:
        badge_parts.append(Block.text(n_text.lstrip(), fp.n_indicator))
    if ref_in_text:
        if badge_parts:
            badge_parts.append(Block.text(" ", fp.collapse))
        badge_parts.append(Block.text(ref_in_text.lstrip(), fp.ref_indicator))
    if ref_out_text:
        if badge_parts:
            badge_parts.append(Block.text(" ", fp.collapse))
        badge_parts.append(Block.text(ref_out_text.lstrip(), fp.ref_outbound))
    if recency_text:
        if badge_parts:
            badge_parts.append(Block.text(" ", fp.collapse))
        badge_parts.append(Block.text(recency_text.lstrip(), fp.collapse))

    if badge_parts:
        parts.append(Block.text(" [", fp.collapse))
        parts.extend(badge_parts)
        parts.append(Block.text("]", fp.collapse))

    if separator and body_text:
        parts.append(Block.text(separator, fp.body))
        parts.append(Block.text(body_text, fp.body))
    if truncation_hint:
        parts.append(Block.text(truncation_hint, fp.collapse))

    main_line = join_horizontal(*parts)

    # If width is set, ensure line fits
    if width is not None:
        from painted import truncate as block_truncate
        main_line = block_truncate(main_line, width)

    lines: list[Block] = [main_line]

    # DETAILED: observer + remaining payload fields + outbound refs
    if zoom >= Zoom.DETAILED:
        detail_pad = " " * (indent + 2)
        if item.observer:
            lines.append(Block.text(
                f"{detail_pad}observer: {item.observer}", fp.observer, width=width
            ))
        if item.id:
            lines.append(Block.text(f"{detail_pad}id:{item.id[:8]}", fp.meta, width=width))
        skip = {used_label_field} if used_label_field else set()
        if body_field:
            skip.add(body_field)
        for k, v in payload.items():
            if k in skip or not v:
                continue
            lines.append(Block.text(f"{detail_pad}{k}: {v}", fp.meta, width=width))
        # Outbound refs gated on "refs" visibility — not shown at DETAILED by default

    # Edge expansion: gated on "refs" in visible, shown at any zoom >= SUMMARY
    if "refs" in visible and zoom >= Zoom.SUMMARY:
        edge_pad = " " * (indent + 2)
        # Inbound edges: who references this item?
        item_key = _item_full_key(item, key_field, section_kind)
        if item_key and item_key in inbound_edges:
            for source in inbound_edges[item_key]:
                lines.append(Block.text(f"{edge_pad}← {source}", fp.ref_edge_in, width=width))
        # Outbound edges
        for ref in item.refs:
            lines.append(Block.text(f"{edge_pad}→ {ref}", fp.ref_edge_out, width=width))

    # Source facts: gated on "facts" in visible, shown at any zoom >= SUMMARY
    if "facts" in visible and zoom >= Zoom.SUMMARY:
        fact_pad = " " * (indent + 2)
        item_key = _item_full_key(item, key_field, section_kind)
        item_facts = facts_by_key.get(item_key, [])
        if item_facts:
            # Show in reverse chronological order (most recent first)
            sorted_facts = sorted(item_facts, key=lambda f: f.get("_ts", 0), reverse=True)
            # At SUMMARY: show last 3. At DETAILED+: show all.
            limit = 3 if zoom <= Zoom.SUMMARY else len(sorted_facts)
            for sf in sorted_facts[:limit]:
                ts = sf.get("_ts")
                ts_str = _format_date(ts) if ts else "?"
                # Find the body: first non-key, non-metadata field
                sf_body = ""
                for fk, fv in sf.items():
                    if fk.startswith("_") or fk == (key_field or ""):
                        continue
                    if fv:
                        sf_body = str(fv)
                        break
                if sf_body and width is not None:
                    max_body = max(10, width - len(fact_pad) - len(ts_str) - 3)
                    if len(sf_body) > max_body:
                        sf_body = sf_body[:max_body - 1] + "…"
                lines.append(Block.text(
                    f"{fact_pad}▸ {ts_str} {sf_body}", fp.meta, width=width
                ))
            remaining_facts = len(sorted_facts) - limit
            if remaining_facts > 0:
                lines.append(Block.text(
                    f"{fact_pad}({remaining_facts} earlier)", fp.collapse, width=width
                ))

    # FULL: metadata
    if zoom >= Zoom.FULL:
        meta_pad = " " * (indent + 2)
        if item.id:
            lines.append(Block.text(f"{meta_pad}_id: {item.id}", fp.meta, width=width))
        if item.ts:
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


def _compute_inbound_edges(data: FoldState) -> dict[str, list[str]]:
    """Build adjacency map: target → [source, ...] for edge expansion."""
    edges: dict[str, list[str]] = {}
    for section in data.sections:
        kf = section.key_field
        for item in section.items:
            if not item.refs:
                continue
            source = _item_full_key(item, kf, section.kind)
            if not source:
                continue
            for ref in item.refs:
                edges.setdefault(ref, []).append(source)
    return edges


def _item_full_key(item: FoldItem, key_field: str | None, kind: str = "") -> str:
    """Build the full kind/key reference for an item (e.g. 'decision/atoms/n-on-fold-item')."""
    if not key_field:
        return ""
    key = item.payload.get(key_field, "")
    if not key:
        return ""
    return f"{kind}/{key}" if kind else str(key)


def _salience(item: FoldItem, key_field: str | None, inbound: Counter) -> int:
    """Salience = n + inbound ref count."""
    return item.n + _inbound_count(item, key_field, inbound)


def _inbound_count(item: FoldItem, key_field: str | None, inbound: Counter) -> int:
    """Look up inbound ref count for this item.

    Matches refs in two forms:
    * Kind-qualified — ``<fact-kind>/<key>`` (e.g. ``decision/design/foo``)
    * Bare — the key_field value itself (e.g. ``design/foo``)

    The bare form matters when the key contains a namespace slash:
    ``endswith("/foo")`` alone misses it. Both forms commonly appear in
    practice — refs emitted as ``ref=design/foo`` vs ``ref=decision/design/foo``
    should contribute equivalently to salience.
    """
    if not key_field:
        return 0
    key = item.payload.get(key_field, "")
    if not key:
        return 0
    count = 0
    suffix = f"/{key}"
    for ref_key, ref_count in inbound.items():
        if ref_key == key or ref_key.endswith(suffix):
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


def _recency_tag(ts) -> str:
    """Compact recency indicator from timestamp.

    Returns relative time like '2h', '3d', '2w' for recent items,
    month abbreviation for older ones.
    """
    import time

    if ts is None:
        return ""
    if isinstance(ts, str):
        try:
            epoch = datetime.fromisoformat(ts).timestamp()
        except ValueError:
            return ""
    elif isinstance(ts, (int, float)):
        epoch = ts
    else:
        return ""
    age = time.time() - epoch
    if age < 0:
        return "now"
    if age < 3600:
        return f"{int(age / 60)}m"
    if age < 86400:
        return f"{int(age / 3600)}h"
    if age < 604800:
        return f"{int(age / 86400)}d"
    if age < 2592000:
        return f"{int(age / 604800)}w"
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return f"{dt.strftime('%b')} {dt.day}"


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
