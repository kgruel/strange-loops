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

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from datetime import datetime, timezone

from painted import Block, Style, Zoom, budget_fields, join_horizontal, join_vertical

from ._helpers import elide
from painted.palette import current_palette

from atoms import FoldState  # runtime: the polymorphic fold_view front door
from loops.surface import project  # runtime: FoldState → Surface (idempotent)

if TYPE_CHECKING:
    from atoms import FoldItem  # grouping-helper hints (duck-typed on .payload)
    from loops.surface import Row, Surface


# ---------------------------------------------------------------------------
# Preview render constants
# ---------------------------------------------------------------------------

# Separator between preview fields in the SUMMARY trailing slot.
# Middot + spaces reads as "and also" (typographic convention).
PREVIEW_SEPARATOR = " · "

# Below this remaining budget, a later preview field is dropped rather than
# truncated to an unreadable nub. The dropped tail is reflected in the
# `[+Nc]` truncation hint.
MIN_FIELD_BUDGET = 12


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
    data: "Surface | FoldState", zoom: Zoom, width: int | None,
    *, vertex_name: str | None = None, vertex_path: str | None = None,
    visible: frozenset[str] = frozenset(),
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render fold data at the given zoom level.

    Accepts a ``Surface`` (the dispatch path, post-S2) or a ``FoldState`` (any
    caller still handing raw fold data — the autoresearch re-export, the
    vertex-decl/override gate-fail path, out-of-repo lenses, direct test
    calls). A FoldState is projected through ``surface.project`` first; the
    projection is idempotent on a Surface, so this is a safe polymorphic front
    door and lets the salience math live in ONE place (surface.py).

    The lens reads the materialized ``Row.salience/inbound`` and the
    ``Surface.inbound_edges`` adjacency instead of recomputing them.

    visible gates which concern layers are rendered:
      - "refs": show per-item edge expansion (← inbound, → outbound)

    Density budgets (0 = unlimited):
      lines: max items shown per section/group. Items beyond the budget
             collapse into "(N more)" footers. Salience ordering applies first.
      chars: max display width for body text. Caps the body budget that
             width-based truncation already enforces — useful for context-
             window economics where total tokens matter more than terminal fit.
    """
    if isinstance(data, FoldState):
        data = project(data)

    # Content-search (--match) switches the lens to the event axis: a flat
    # ts-desc list of matching facts, with the (K not indexed) coverage footer.
    if data.window.query is not None:
        return _render_search(data, zoom, width)

    # Primary rows group by kind in fold (== declaration) order; walked rows
    # (depth>0) render after. Salience/inbound are already materialized.
    primary = [r for r in data.rows if r.depth == 0]
    walked_rows = [r for r in data.rows if r.depth > 0]
    populated = _group_rows_by_kind(primary)
    if not populated:
        return Block.text("No data yet.", Style(dim=True), width=width)

    # MINIMAL: one-liner
    if zoom == Zoom.MINIMAL:
        parts = [f"{len(rows)} {kind}s" for kind, rows in populated]
        if data.unfolded:
            loose = ", ".join(f"{c} {k}" for k, c in sorted(data.unfolded.items()))
            parts.append(f"unfolded: {loose}")
        return Block.text(", ".join(parts), Style(), width=width)

    # Edge adjacency + source facts come materialized off the Surface.
    inbound_edges = data.inbound_edges if "refs" in visible else {}
    facts_by_key = data.source_facts if "facts" in visible else {}
    fp = _default_fold_palette()
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    blocks: list[Block] = []

    for kind, rows in populated:
        kv = data.schema.get(kind)
        fold_type = kv.fold_type if kv is not None else "collect"
        key_field = kv.key_field if kv is not None else None
        preview_fields = kv.preview_fields if kv is not None else ()
        display_count = len(rows)

        # --facts shows the raw fact stream. For a collect-fold the folded rows
        # ARE that stream (n=1 each, no compression to expand); for a by-fold
        # the source facts expand inline where present. Either way the rows
        # render — skipping them inverted the flag's contract
        # (friction:facts-empty-for-collect-fold-kinds).
        if blocks:
            blocks.append(Block.text("", Style(), width=width))

        header = _section_header(kind, display_count, piped=width is None)
        blocks.append(Block.text(header, fp.section_header, width=width))

        observers = {r.observer for r in rows if r.observer}
        show_observer = len(observers) > 1

        section_block = _render_section(
            kind, rows, fold_type, key_field, preview_fields,
            zoom, fmt, width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            lines=lines, chars=chars,
        )
        blocks.append(section_block)

    # Walked items (when --refs N walked the graph). Renders after primary
    # sections so the anchor context is established before the walk reveals
    # what's connected to it.
    if walked_rows:
        walked_block = _render_walked(
            walked_rows, zoom=zoom, fmt=fmt, width=width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key, fp=fp, visible=visible,
            chars=chars,
        )
        if walked_block is not None:
            blocks.append(Block.text("", Style(), width=width))
            blocks.append(walked_block)

    # Footer: unfolded kinds
    footer_parts: list[str] = []
    if data.unfolded:
        loose = ", ".join(f"{c} {k}" for k, c in sorted(data.unfolded.items()))
        footer_parts.append(f"Unfolded: {loose}")
    if footer_parts:
        blocks.append(Block.text("", Style(), width=width))
        blocks.append(Block.text(
            "  ".join(footer_parts), fp.unfolded, width=width,
        ))

    return join_vertical(*blocks)


def _render_search(data: "Surface", zoom: Zoom, width: int | None) -> Block:
    """Event-axis render for ``--match`` — a flat ts-desc list of matching facts.

    Each row is one matching FACT (event axis), not a folded item, so there is
    no kind-grouping; the read is chronological. The footer names the kinds that
    lacked FTS coverage (``window.unindexed``) — the honesty signal that those
    were substring-scanned, not FTS-searched.
    """
    from loops.lenses.gist import content_gist

    fp = _default_fold_palette()
    q = data.window.query
    rows = list(data.rows)
    n = len(rows)

    if zoom == Zoom.MINIMAL:
        line = f"{n} match{'es' if n != 1 else ''} for {q!r}"
        if data.window.unindexed:
            line += f" ({len(data.window.unindexed)} not indexed)"
        return Block.text(line, Style(), width=width)

    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date
    blocks: list[Block] = [
        Block.text(
            f"MATCH {q!r} — {n} result{'s' if n != 1 else ''}",
            fp.section_header, width=width,
        )
    ]
    if not rows:
        blocks.append(Block.text("  (no matches)", Style(dim=True), width=width))
    for r in rows:
        date = fmt(r.ts) if r.ts is not None else ""
        gist = content_gist(r.kind, r.payload)
        line = f"  {date}  {r.kind}: {gist}".rstrip()
        blocks.append(Block.text(line, Style(), width=width))

    if data.window.unindexed:
        footer = (
            f"({len(data.window.unindexed)} not indexed: "
            f"{', '.join(data.window.unindexed)})"
        )
        blocks.append(Block.text("", Style(), width=width))
        blocks.append(Block.text(footer, fp.unfolded, width=width))

    return join_vertical(*blocks)


def _group_rows_by_kind(rows: list["Row"]) -> list[tuple[str, list["Row"]]]:
    """Group rows by kind, preserving first-appearance (== fold/declaration)
    order. Mirrors the old ``populated = [s for s in data.sections if s.items]``
    — only kinds with rows appear, in declaration order."""
    groups: dict[str, list[Row]] = {}
    order: list[str] = []
    for r in rows:
        if r.kind not in groups:
            groups[r.kind] = []
            order.append(r.kind)
        groups[r.kind].append(r)
    return [(k, groups[k]) for k in order]


def _render_walked(
    walked: list["Row"],  # ref-walk rows (depth>0)
    *,
    zoom: Zoom,
    fmt,
    width: int | None,
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    visible: frozenset[str] = frozenset(),
    chars: int = 0,
) -> Block | None:
    """Render walked entities grouped by their immediate via_anchor.

    Walked rows are produced by --refs N on read; they carry depth>0 and a
    via_anchor lineage. Render shape:

        ## REFS (N)
          ┄ via → kind/anchor-key
            decision/design/foo [...]: body...
              → outbound refs
          ┄ via → kind/another-anchor-key
            ↳ depth-2 items render with ↳ prefix when their via_anchor is
              itself a walked item (depth-1)

    The ``┄ via → X`` marker addresses the trace-refs-no-visual-marker
    friction — every walked row carries clear attribution back to its
    parent in the chain. depth>1 items are visually distinguished by ``↳``
    prefix and additional indent so the lineage chain reads cleanly.
    """
    if not walked:
        return None

    blocks: list[Block] = []
    blocks.append(Block.text(
        f"## REFS ({len(walked)})", fp.section_header, width=width,
    ))

    last_anchor: str | None = None
    for w in walked:
        if w.via_anchor != last_anchor:
            # Marker for a new via-anchor group. The ┄...┄ frames it
            # as ambient context, not as primary content.
            blocks.append(Block.text(
                f"  ┄ via → {w.via_anchor}", fp.collapse, width=width,
            ))
            last_anchor = w.via_anchor

        # depth=1: render at 4-space indent. depth>1: 6+ with ↳ prefix.
        # _render_item_line takes indent as the leading-pad width — we add
        # the ↳ marker via a custom prefix when depth > 1 by rendering the
        # marker as a separate block and following with the standard line.
        item_indent = 4 if w.depth == 1 else 4 + (w.depth - 1) * 2
        line = _render_item_line(
            w, w.key_field, zoom, fmt, width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=False, visible=visible,
            indent=item_indent, strip_namespace=False,
            section_kind=w.kind, chars=chars,
        )
        if w.depth > 1:
            # Prepend depth marker as overlay — render a single composed
            # line with ↳ then the rest. Simpler: emit a tiny marker line
            # ahead of the item.
            marker_pad = " " * (item_indent - 2)
            blocks.append(Block.text(
                f"{marker_pad}↳ (d{w.depth})", fp.collapse, width=width,
            ))
        blocks.append(line)

    return join_vertical(*blocks)


# ---------------------------------------------------------------------------
# Section rendering — dispatches to grouped or flat
# ---------------------------------------------------------------------------


def _render_section(
    kind: str,
    rows: list["Row"],
    fold_type: str,
    key_field: str | None,
    preview_fields: tuple[str, ...],
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render a section's rows — grouped by namespace or flat."""
    is_by = fold_type == "by"

    if is_by and key_field and _should_group_by_namespace(rows, key_field):
        return _render_grouped(
            rows, key_field, zoom, fmt, width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            section_kind=kind,
            preview_fields=preview_fields,
            lines=lines, chars=chars,
        )
    else:
        return _render_flat(
            rows, key_field, fold_type,
            zoom, fmt, width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            section_kind=kind,
            preview_fields=preview_fields,
            lines=lines, chars=chars,
        )


# ---------------------------------------------------------------------------
# Namespace-grouped rendering (Strategy C)
# ---------------------------------------------------------------------------

_GROUP_SHOW_ALL_THRESHOLD = 5


def _render_grouped(
    items: list["Row"],
    key_field: str,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    section_kind: str = "",
    preview_fields: tuple[str, ...] = (),
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render by-fold rows grouped by namespace prefix.

    Reads the materialized ``Row.salience`` for group ordering and windowing.
    As of A1 of the trace-dissolution arc, --refs no longer filters items to
    the ref-connected subset — orphans render normally with edge decoration
    where edges exist. See decision/design/trace-dissolves-into-read-with-
    unified-refs.
    """
    groups = _group_by_namespace(items, key_field)

    sorted_groups = sorted(
        groups.items(),
        key=lambda g: sum(i.salience for i in g[1]),
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
            key=lambda i: i.salience,
            reverse=True,
        )

        # Salience windowing: when group is large, show only high-salience items.
        # The pre-A1 "if refs in visible: show all" branch was retired alongside
        # the refs filter — normal windowing applies regardless of --refs.
        if len(sorted_items) <= _GROUP_SHOW_ALL_THRESHOLD:
            show_items = sorted_items
        else:
            show_items = [
                i for i in sorted_items
                if i.salience > 1
            ]
            if not show_items:
                show_items = sorted_items[:1]

        # Apply lines budget (highest-salience kept; rest collapse to "more")
        if lines > 0 and len(show_items) > lines:
            show_items = list(show_items)[:lines]

        for item in show_items:
            blocks.append(_render_item_line(
                item, key_field, zoom, fmt, width,
                inbound_edges=inbound_edges,
                facts_by_key=facts_by_key,
                fp=fp, show_observer=show_observer, visible=visible,
                indent=4, strip_namespace=True, section_kind=section_kind,
                preview_fields=preview_fields,
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
    items: list["Row"],
    key_field: str | None,
    fold_type: str,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    section_kind: str = "",
    preview_fields: tuple[str, ...] = (),
    lines: int = 0, chars: int = 0,
) -> Block:
    """Render rows as a flat list — sorted by salience for by-folds.

    Reads the materialized ``Row.salience``. As of A1 of the trace-dissolution
    arc, --refs no longer filters items to the ref-connected subset — see
    decision/design/trace-dissolves-into-read-with-unified-refs.
    """
    is_by = fold_type == "by"

    if is_by:
        sorted_items: list[Row] = sorted(
            items,
            key=lambda i: i.salience,
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
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            indent=2, strip_namespace=False, is_by=is_by, section_kind=section_kind,
            preview_fields=preview_fields,
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
    item: "Row",
    key_field: str | None,
    zoom: Zoom,
    fmt,
    width: int | None,
    *,
    inbound_edges: dict[str, list[str]],
    facts_by_key: dict[str, list[dict]],
    fp: FoldPalette,
    show_observer: bool,
    visible: frozenset[str] = frozenset(),
    indent: int = 2,
    strip_namespace: bool = False,
    is_by: bool = True,
    section_kind: str = "",
    preview_fields: tuple[str, ...] = (),
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
    ref_count = item.inbound  # materialized in project() (was _inbound_count)
    ref_in_text = f" ←{ref_count}" if ref_count > 0 else ""
    ref_out_text = f" →{len(item.refs)}" if item.refs else ""

    # Recency tag
    recency_text = ""
    if item.ts:
        recency_text = f" {_recency_tag(item.ts)}"

    # Body — either preview-driven (explicit per-kind decl) or fallback
    # (first non-label payload field, the historical behavior). An empty
    # preview_fields tuple means "no decl" → fall through to _find_body_entry
    # for back-compat with kinds that haven't migrated.
    body_field: str | None = None
    body: str = ""
    candidate_vals: list[str] = []
    if preview_fields:
        candidate_vals = [
            str(payload.get(f) or "").strip() for f in preview_fields
        ]
        non_empty = [v for v in candidate_vals if v]
        # body_len = full untruncated render size; the [+Nc] hint then
        # accurately reflects what the cascade dropped or truncated.
        body_len = sum(len(v) for v in non_empty) + max(
            0, (len(non_empty) - 1)
        ) * len(PREVIEW_SEPARATOR)
    else:
        body_field, found = _find_body_entry(payload, used_label_field)
        body = found or ""
        body_len = len(body)

    has_body = body_len > 0
    separator = ": " if has_body else ""

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

    if has_body:
        # Determine body budget (cap for both preview and fallback paths).
        # At DETAILED+: preview renders untruncated (no width cap). The fallback
        # path retains the existing width-budget behavior; preview is the
        # higher-fidelity path so it overrides.
        if zoom >= Zoom.DETAILED and preview_fields:
            body_budget = body_len  # untruncated
        elif width is not None:
            # Reserve space for potential truncation hint " [+NNNc]"
            hint_reserve = 10
            body_budget = max(10, width - fixed_len - hint_reserve)
            if chars > 0:
                body_budget = min(body_budget, chars)
        else:
            body_budget = chars if chars > 0 else body_len

        # Field budgeting dissolves into painted.budget_fields — the
        # shrink-then-drop allocator (wcwidth-measured, fixing the latent
        # len()/CJK bug; min_field gates *truncation* not presence, so short
        # whole values are kept where the old guard dropped them —
        # decision:design/budget-fields-truncation-gate-contract).
        if preview_fields and zoom >= Zoom.DETAILED:
            # DETAILED+: untruncated — join every non-empty field, no budget.
            body_text = PREVIEW_SEPARATOR.join(v for v in candidate_vals if v)
        else:
            fields = candidate_vals if preview_fields else [body]
            fit = budget_fields(
                fields, body_budget,
                min_field=MIN_FIELD_BUDGET, sep=PREVIEW_SEPARATOR,
            )
            body_text = fit.text
            if fit.dropped > 0:
                truncation_hint = f" [+{fit.dropped}c]"
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
        # Preview fields already render inline (untruncated at DETAILED+) —
        # don't double-print them as extra-field lines below.
        if preview_fields:
            skip.update(preview_fields)
        for k, v in payload.items():
            if k in skip or not v:
                continue
            lines.append(Block.text(f"{detail_pad}{k}: {v}", fp.meta, width=width))
        # Outbound refs gated on "refs" visibility — not shown at DETAILED by default

    # Edge expansion: gated on "refs" in visible, shown at any zoom >= SUMMARY
    if "refs" in visible and zoom >= Zoom.SUMMARY:
        edge_pad = " " * (indent + 2)
        # Inbound edges: who references this item? Row.address == the old
        # _item_full_key(item, key_field, kind) for keyed rows; keyless
        # (collect) rows had "" then and contribute no edges now.
        item_key = item.address if item.key is not None else ""
        if item_key and item_key in inbound_edges:
            for source in inbound_edges[item_key]:
                lines.append(Block.text(f"{edge_pad}← {source}", fp.ref_edge_in, width=width))
        # Outbound edges
        for ref in item.refs:
            lines.append(Block.text(f"{edge_pad}→ {ref}", fp.ref_edge_out, width=width))

    # Source facts: gated on "facts" in visible, shown at any zoom >= SUMMARY
    if "facts" in visible and zoom >= Zoom.SUMMARY:
        fact_pad = " " * (indent + 2)
        item_key = item.address if item.key is not None else ""
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
                    sf_body = elide(sf_body, max_body)
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
# Salience computation — LIFTED to loops.surface (project materializes
# Row.salience / Row.inbound / Surface.inbound_edges). The lens reads those
# materialized scalars; the helpers live in surface.py now.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Namespace grouping
# ---------------------------------------------------------------------------


_NAMESPACE_DEGENERATE_RATIO = 2  # ungrouped > ratio × grouped → fall back to flat

def _should_group_by_namespace(items: tuple[FoldItem, ...], key_field: str) -> bool:
    """True when namespace grouping improves orientation over a flat list.

    Two conditions must both hold:

    1. At least one item has a namespaced key (contains '/').
    2. The grouped portion is not degenerate — when ungrouped items dominate
       (ungrouped > ``_NAMESPACE_DEGENERATE_RATIO`` × grouped), the breakdown
       buries the majority behind an unhelpful '(ungrouped: N)' label and
       flat rendering is more honest.

    Concrete failure mode this prevents::

        autoresearch/ (1)
        substrate-friction/ (1)
        (ungrouped) (173)   ← hides 99% of items

    In that case the ratio check fails (173 > 2×2) and we fall through to
    flat rendering, surfacing the full index salience-sorted.
    """
    namespaced = sum(
        1 for item in items if "/" in str(item.payload.get(key_field, ""))
    )
    if namespaced == 0:
        return False
    ungrouped = len(items) - namespaced
    return ungrouped <= _NAMESPACE_DEGENERATE_RATIO * namespaced


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
