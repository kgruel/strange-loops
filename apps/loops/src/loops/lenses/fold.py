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

import textwrap
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, budget_fields, join_horizontal, join_vertical

from painted.palette import current_palette

from atoms import FoldState  # runtime: the polymorphic fold_view front door
from loops.surface import project  # runtime: FoldState → Surface (idempotent)

from ._grammar import (
    RAIL_LEGEND,
    card,
    card_width,
    coerce_dt,
    date_key,
    rail_glyph,
    recency_style,
    rollup_line,
)
from ._grammar import full_iso as _format_ts_full
from ._grammar import recency as _recency_tag
from ._grammar import short_date as _format_date
from ._statview import palette_of

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

# TTY rail rows: a body that doesn't fit inline drops to a hanging block
# wrapped under the key column. At the SUMMARY orientation view the block is
# height-capped so one long decision can't sever the rail; -v/-vv and exact
# key addresses render the block uncapped (flip-invariance keeps its
# retrieval-path promise). See decision:design/tier-allocated-disclosure.
BODY_WRAP_MAX_LINES = 4


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
# The TTY header card (spine G5) — the shared letterhead over the rail body.
# ---------------------------------------------------------------------------


def _fold_card(
    surface: "Surface",
    populated: list[tuple[str, list["Row"]]],
    primary: list["Row"],
    body: Block,
    width: int | None,
    vertex_name: str | None,
) -> Block | None:
    """The TTY header card for a fold read — vertex letterhead + stat sublines.

    Title = ``<vertex> · fold``; the sublines are aggregates the piped ledger
    already carries per-kind (key/kind/fact counts via the ``## KIND (N)``
    headers) plus the freshness of the newest key, so the card states nothing
    the agent channel lacks — no piped parity addition is owed. Returns None
    when there's no vertex to title (legacy list-shaped callers)."""
    name = vertex_name or surface.vertex
    if not name:
        return None
    keys = len(primary)
    kinds = len(populated)
    facts = sum(r.n for r in primary)
    sublines = [f"{keys} keys · {kinds} kinds · {facts} facts"]
    stamps = [dt for r in primary if (dt := coerce_dt(r.ts)) is not None]
    if stamps:
        sublines.append(f"updated {_recency_tag(max(stamps))}")
    title = f"{name} · fold"
    p = palette_of(None)
    card_w = card_width(body, title, sublines, width)
    return card(title, sublines, card_w, p=p)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fold_view(
    data: "Surface | FoldState", zoom: Zoom, width: int | None,
    *, vertex_name: str | None = None, vertex_path: str | None = None,
    visible: frozenset[str] = frozenset(),
    lines: int = 0, chars: int = 0,
    piped: bool | None = None,
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

    # MINIMAL: one-liner on the spine grammar (vertex · N kinds · …).
    if zoom == Zoom.MINIMAL:
        name = vertex_name or data.vertex
        parts = [f"{len(rows)} {kind}s" for kind, rows in populated]
        if data.unfolded:
            loose = ", ".join(f"{c} {k}" for k, c in sorted(data.unfolded.items()))
            parts.append(f"unfolded: {loose}")
        return Block.text(rollup_line(name, parts), Style(), width=width)

    # Edge adjacency + source facts come materialized off the Surface.
    inbound_edges = data.inbound_edges if "refs" in visible else {}
    facts_by_key = data.source_facts if "facts" in visible else {}
    fp = _default_fold_palette()
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    blocks: list[Block] = []

    # Presentation register is the CHANNEL, not the width. Truncation is now
    # dropped on human reads (width=None there too), so width can no longer tell
    # a human TTY read from a piped one — the explicit `piped` flag does. Default
    # to the old width-is-None proxy for direct/legacy callers (goldens, tests).
    # (decision:design/drop-truncation-from-human-reads — presentation half)
    is_piped = (width is None) if piped is None else piped

    # Tier-allocated disclosure engages only when the population HAS a tier
    # gradient (decision:design/tier-allocated-disclosure). A flat population
    # (all one tier — the _tier_thresholds None case, e.g. a tiny vertex) has
    # nothing to allocate ALONG, so it renders uniform bodies as before. TTY
    # only; the piped ledger never allocates.
    tier_allocate = (
        not is_piped and len({r.tier for r in primary}) > 1
    )

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

        header = _section_header(kind, display_count, piped=is_piped)
        # Section header carries the kind's stable hue on the TTY register (the
        # header text is identical on both channels). Keep it bold — the kind
        # colour rides the fold-palette's section emphasis.
        header_style = (
            fp.section_header if is_piped
            else Style(bold=True, fg=palette_of(None).kind_style(kind).fg)
        )
        blocks.append(Block.text(header, header_style, width=width))

        observers = {r.observer for r in rows if r.observer}
        show_observer = len(observers) > 1

        section_block = _render_section(
            kind, rows, fold_type, key_field, preview_fields,
            zoom, fmt, width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            lines=lines, chars=chars, piped=is_piped,
            tier_allocate=tier_allocate,
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

    # Rail legend — TTY only; the piped ledger spells tiers as words.
    if not is_piped:
        blocks.append(Block.text(RAIL_LEGEND, fp.meta, width=width))

    body = join_vertical(*blocks)

    # Header card — TTY letterhead over the rail body (decision:design/static-
    # grammar-hybrid-by-register; fidelity policy B). SUMMARY and above only;
    # -q (MINIMAL) already returned its bare one-liner above, and the piped
    # ledger never wears chrome.
    if not is_piped and zoom >= Zoom.SUMMARY:
        head = _fold_card(data, populated, primary, body, width, vertex_name)
        if head is not None:
            return join_vertical(head, body)

    return body


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
        parts = [f"{n} match{'es' if n != 1 else ''} for {q!r}"]
        if data.window.unindexed:
            parts.append(f"{len(data.window.unindexed)} not indexed")
        return Block.text(rollup_line(data.vertex, parts), Style(), width=width)

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
        prefix = f"  {date}  {r.kind}: "
        # Full extraction (newlines collapsed), no 80-cap — search now honors
        # the same width contract as the fold path
        # (friction:read-tty-truncation-not-defeatable, --match 80-cap).
        gist = content_gist(r.kind, r.payload, max_width=None)
        if width is None:
            # piped: the whole body — the dominant agent path
            blocks.append(Block.text(f"{prefix}{gist}".rstrip(), Style(), width=None))
            continue
        # TTY: budget the body to the line width (wcwidth) and announce the
        # magnitude dropped, instead of a silent 80-char clip. Reserve room
        # for the " [+Nc]" hint so it survives the width fit.
        budget = max(width - len(prefix) - 10, MIN_FIELD_BUDGET)
        fit = budget_fields(
            [gist], budget, min_field=MIN_FIELD_BUDGET, sep=PREVIEW_SEPARATOR,
        )
        hint = f" [+{fit.dropped}c]" if fit.dropped > 0 else ""
        blocks.append(Block.text(f"{prefix}{fit.text}{hint}", Style(), width=width))

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
    piped: bool = False,
    tier_allocate: bool = False,
) -> Block:
    """Render a section's rows — TTY: rail rows, grouped by namespace or
    flat; piped: the flat ledger (full keys, named columns)."""
    is_by = fold_type == "by"

    if piped:
        return _render_ledger(
            rows, key_field, fold_type, zoom, fmt, width,
            inbound_edges=inbound_edges, facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            section_kind=kind, preview_fields=preview_fields,
            lines=lines, chars=chars,
        )

    grouped = bool(is_by and key_field and _should_group_by_namespace(rows, key_field))
    cols = _section_cols(rows, key_field, is_by, strip_namespace=grouped)

    if grouped:
        return _render_grouped(
            rows, key_field, zoom, fmt, width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            section_kind=kind,
            preview_fields=preview_fields,
            lines=lines, chars=chars, cols=cols,
            tier_allocate=tier_allocate,
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
            lines=lines, chars=chars, cols=cols,
            tier_allocate=tier_allocate,
        )


# ---------------------------------------------------------------------------
# Section column widths — computed ONCE across the whole section so rows
# align across namespace groups (the ls cross-group column-drift lesson:
# per-group widths silently misalign; see observation
# rendering/piped-faithfulness-forces-width-none).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Cols:
    key_w: int = 0
    age_w: int = 0
    cluster_w: int = 0  # the "×n ←n →n" cluster (TTY register)
    n_w: int = 1  # ledger N column
    in_w: int = 2  # ledger IN column


def _row_label(item: "Row", key_field: str | None, is_by: bool,
               strip_namespace: bool) -> str:
    if is_by and key_field:
        label = str(item.payload.get(key_field, ""))
        if strip_namespace and "/" in label:
            label = label.split("/", 1)[1]
        return label
    label, _ = _first_field(item.payload)
    return label or ""


def _cluster_text(item: "Row", is_by: bool) -> str:
    parts = []
    if is_by and item.n > 1:
        parts.append(f"×{item.n}")
    if item.inbound > 0:
        parts.append(f"←{item.inbound}")
    out = len(item.refs) + len(item.edges)
    if out:
        parts.append(f"→{out}")
    return " ".join(parts)


def _section_cols(rows: list["Row"], key_field: str | None, is_by: bool,
                  *, strip_namespace: bool) -> _Cols:
    if not rows:
        return _Cols()
    key_w = max(
        (len(_row_label(r, key_field, is_by, strip_namespace)) for r in rows),
        default=0,
    )
    age_w = max((len(_recency_tag(r.ts)) for r in rows), default=0)
    cluster_w = max((len(_cluster_text(r, is_by)) for r in rows), default=0)
    n_w = max(max((len(str(r.n)) for r in rows), default=1), 1)
    in_w = max(max((len(str(r.inbound)) for r in rows), default=1), 2)
    return _Cols(key_w=key_w, age_w=age_w, cluster_w=cluster_w,
                 n_w=n_w, in_w=in_w)


# ---------------------------------------------------------------------------
# Piped register — the ledger (decision:design/static-grammar-hybrid-by-
# register: 2a columns). Flat, full keys, salience-sorted; TIER carried as a
# word (information-faithfulness — the tier function has vertex-population
# context a pipe consumer can't reconstruct); DATE is the ISO column
# (time-vocab option C).
# ---------------------------------------------------------------------------


def _render_ledger(
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
    is_by = fold_type == "by"
    sorted_items = (
        sorted(items, key=lambda i: i.salience, reverse=True) if is_by else items
    )

    total = len(sorted_items)
    if lines > 0 and total > lines:
        sorted_items = list(sorted_items)[:lines]

    cols = _section_cols(sorted_items, key_field, is_by, strip_namespace=False)
    header = (
        f"{'KEY':<{max(cols.key_w, 3)}}  {'TIER':<5}  {'N':>{cols.n_w}}  "
        f"{'IN':>{cols.in_w}}  {'DATE':<10}  MESSAGE"
    )
    blocks: list[Block] = [Block.text(header, fp.meta, width=width)]

    for item in sorted_items:
        blocks.append(_render_item_line(
            item, key_field, zoom, fmt, width,
            inbound_edges=inbound_edges,
            facts_by_key=facts_by_key,
            fp=fp, show_observer=show_observer, visible=visible,
            indent=0, strip_namespace=False, is_by=is_by,
            section_kind=section_kind,
            preview_fields=preview_fields,
            chars=chars, piped=True, cols=cols,
        ))

    remaining = total - len(sorted_items)
    if remaining > 0:
        blocks.append(Block.text(f"({remaining} more)", fp.collapse, width=width))

    return join_vertical(*blocks) if blocks else Block.empty(0, 0)


# ---------------------------------------------------------------------------
# Namespace-grouped rendering (Strategy C)
# ---------------------------------------------------------------------------


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
    cols: "_Cols | None" = None,
    tier_allocate: bool = False,
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

        # Human reads show every row. The salience auto-window (collapse a large
        # group to its salience>1 items) was the ROW-level twin of the body
        # truncation budget, and it forked the umwelt the same way: the text
        # lens hid rows the Surface — and --json — still carried, with no record
        # in Surface.window. Dropped, same as truncation, so both channels
        # deliver the same information (parity first; flood accepted). Curation
        # returns later as an explicit, DESIGNED budget — the `lines` opt-in
        # below, an `orient` door, or a Surface-recorded window per the
        # curation-in-surface arc — never an always-on default.
        # (decision:design/drop-truncation-from-human-reads — row half)
        show_items = sorted_items

        # Apply lines budget (explicit opt-in; 0 = unlimited, the read default).
        # Highest-salience kept; the rest collapse into the "(N more)" footer.
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
                chars=chars, cols=cols, tier_allocate=tier_allocate,
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
    cols: "_Cols | None" = None,
    tier_allocate: bool = False,
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
            chars=chars, cols=cols, tier_allocate=tier_allocate,
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
    piped: bool = False,
    cols: "_Cols | None" = None,
    tier_allocate: bool = False,
) -> Block:
    """Render a single fold item as a composed Block with multi-style.

    TTY register:   ◆ 2h  key  ×N ←N →N  body… [+Nc]   (rail row; columns
                    aligned section-wide via ``cols``)
    piped register: key  tier  N  IN  DATE  body        (ledger row)
    DETAILED adds:  observer, remaining payload fields
    +refs:          per-item edge expansion (← inbound sources, → outbound targets)
    +facts:         source facts that built this fold item
    FULL adds:      all metadata (_id, _ts, _observer, _origin, _n, _inbound_refs)
    """
    payload = item.payload
    pad = " " * indent
    cols = cols or _Cols()

    # Tier-allocated disclosure (decision:design/tier-allocated-disclosure):
    # the TTY default-zoom ORIENTATION view breathes by tier — high rows get
    # bodies, mid get headlines (key + cluster, no body), tail/untiered get
    # bare lines (key only). This is the fix for rail-drowns-under-full-bodies:
    # bodies become scarce, so the rail's spacing survives by construction.
    #
    # Flip-invariance is preserved on every RETRIEVAL path: an exact key address
    # (granularity=="whole") always forces the body; --full/-v/-vv (DETAILED+ or
    # whole) stay uniform and tier-blind; the piped ledger never allocates. Only
    # the SUMMARY-zoom TTY orientation view is exempt (tiers are quantile-
    # relative, so a row may flip body/headline as the population moves — honest
    # for orientation: attention moved).
    allocate = (
        tier_allocate
        and zoom == Zoom.SUMMARY
        and item.granularity != "whole"
    )
    show_body = (not allocate) or item.tier == "high"
    show_cluster = (not allocate) or item.tier in ("high", "mid")

    # Key
    if is_by and key_field:
        used_label_field = key_field
    else:
        _, used_label_field = _first_field(payload)
    label = _row_label(item, key_field, is_by, strip_namespace)

    cluster = _cluster_text(item, is_by)
    age = _recency_tag(item.ts) if item.ts else ""

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

    # Fixed prefix length per register (for the width-budgeted body path).
    key_w = max(cols.key_w, len(label))
    if piped:
        # "key  tier   N  IN  DATE  " ledger prefix
        fixed_len = (
            max(key_w, 3) + 2 + 5 + 2 + cols.n_w + 2 + cols.in_w + 2 + 10 + 2
        )
    else:
        # "  ◆ 2h  key  ×N ←N  " rail prefix (glyph+space+age col+gaps)
        fixed_len = (
            len(pad) + 2 + cols.age_w + 2 + key_w
            + ((2 + cols.cluster_w) if cols.cluster_w else 0) + 2
        )
    hang_body = ""  # TTY body too long for its row — wraps under the key

    # Body text for the piped ledger — the full untruncated render (piped is
    # information-faithful; that channel forces width=None). A chars fidelity
    # dial still budgets via painted.budget_fields (shrink-then-drop,
    # decision:design/budget-fields-truncation-gate-contract). The TTY
    # register composes its own body below (inline vs hanging block).
    if not has_body:
        body_text = ""
    elif chars > 0 and body_len > chars:
        fields = candidate_vals if preview_fields else [body]
        body_text = budget_fields(
            fields, chars, min_field=MIN_FIELD_BUDGET, sep=PREVIEW_SEPARATOR,
        ).text
    else:
        body_text = (
            PREVIEW_SEPARATOR.join(v for v in candidate_vals if v)
            if preview_fields else body
        )

    if piped:
        # Ledger row — plain text, one line, named columns (chrome-free; the
        # writer strips styles anyway, but the ledger IS the piped grammar).
        date = date_key(item.ts) if item.ts else "-"
        line = (
            f"{label:<{max(key_w, 3)}}  {item.tier:<5}  "
            f"{item.n:>{cols.n_w}}  {item.inbound:>{cols.in_w}}  "
            f"{date:<10}  {body_text}".rstrip()
        )
        main_line = Block.text(line, fp.body, width=width)
    else:
        # Rail row — ◆ 2h  key  ×N ←N →N  body
        glyph = rail_glyph(item.tier)
        glyph_style = {
            "high": fp.n_indicator,
            "stale": fp.ref_outbound,
        }.get(item.tier, fp.collapse)
        parts: list[Block] = [
            Block.text(pad, fp.body),
            Block.text(glyph, glyph_style),
            # Recency badge carries the freshness gradient (TTY-only chrome; the
            # tag text is identical to the piped ledger's DATE column).
            Block.text(
                f" {age:<{cols.age_w}}", recency_style(item.ts, palette_of(None))
            ),
            Block.text(f"  {label:<{key_w}}", fp.key),
        ]
        if cols.cluster_w and show_cluster:
            cluster_parts: list[Block] = [Block.text("  ", fp.body)]
            pos = 0
            for token in cluster.split():
                style = (
                    fp.n_indicator if token.startswith("×")
                    else fp.ref_indicator if token.startswith("←")
                    else fp.ref_outbound
                )
                if pos:
                    cluster_parts.append(Block.text(" ", fp.body))
                cluster_parts.append(Block.text(token, style))
                pos += len(token) + (1 if pos else 0)
            if pos < cols.cluster_w:
                cluster_parts.append(Block.text(" " * (cols.cluster_w - pos), fp.body))
            parts.extend(cluster_parts)
        # Body placement: inline when it fits the row, otherwise a hanging
        # block wrapped under the key column (rendered after main_line below).
        # The single-line budget_fields truncation above is the piped-with-
        # width legacy path; the TTY register never drops body content to fit
        # a line — it wraps (decision:design/tier-allocated-disclosure amends
        # drop-truncation-from-human-reads: wrap + explicit cap, not clip).
        if body_text and show_body:
            if width is None or fixed_len + len(body_text) <= width:
                parts.append(Block.text(f"  {body_text}", fp.body))
            else:
                hang_body = body_text

        main_line = join_horizontal(*parts)

        # If width is set, ensure line fits
        if width is not None:
            from painted import truncate as block_truncate
            main_line = block_truncate(main_line, width)

    lines: list[Block] = [main_line]

    # Hanging body block — wrapped under the key column, rail column left
    # clean so the glyph rail stays continuous. Height-capped only at the
    # SUMMARY orientation view for non-exact addresses; -v/-vv and exact key
    # addresses get the whole body (wrapped, never clipped).
    if hang_body and width is not None:
        hang_pad = " " * (len(pad) + 4 + cols.age_w)
        wrap_w = max(20, width - len(hang_pad))
        wrapped = textwrap.wrap(hang_body, wrap_w)
        capped = (
            zoom == Zoom.SUMMARY
            and item.granularity != "whole"
            and len(wrapped) > BODY_WRAP_MAX_LINES
        )
        shown = wrapped[:BODY_WRAP_MAX_LINES] if capped else wrapped
        for wline in shown:
            lines.append(Block.text(hang_pad + wline, fp.body, width=width))
        if capped:
            hidden = len(hang_body) - sum(len(w) for w in shown)
            lines.append(Block.text(
                f"{hang_pad}… [+{hidden}c · -v]", fp.collapse, width=width,
            ))

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

    # Predicate-labeled inbound summary — only when a typed edge is involved
    # (a bare "N via ref" adds nothing). Shown at DETAILED+ where it fits.
    if zoom >= Zoom.DETAILED:
        pred_summary = _predicate_summary(item.inbound_predicates)
        if pred_summary:
            detail_pad = " " * (indent + 2)
            lines.append(Block.text(
                f"{detail_pad}inbound: ←{item.inbound}{pred_summary}",
                fp.ref_indicator, width=width,
            ))

    # Edge expansion: gated on "refs" in visible, shown at any zoom >= SUMMARY
    if "refs" in visible and zoom >= Zoom.SUMMARY:
        edge_pad = " " * (indent + 2)
        # Inbound edges: who references this item? Row.address == the old
        # _item_full_key(item, key_field, kind) for keyed rows; keyless
        # (collect) rows had "" then and contribute no edges now. Each source
        # is (source_addr, predicate) — label the predicate when it's a typed
        # edge (not the grandfathered "ref" union edge).
        item_key = item.address if item.key is not None else ""
        if item_key and item_key in inbound_edges:
            for source, predicate in inbound_edges[item_key]:
                via = "" if predicate == "ref" else f" via {predicate}"
                lines.append(Block.text(
                    f"{edge_pad}← {source}{via}", fp.ref_edge_in, width=width))
        # Outbound edges — ref union edges first, then typed overlay edges
        # (labeled with their predicate).
        for ref in item.refs:
            lines.append(Block.text(f"{edge_pad}→ {ref}", fp.ref_edge_out, width=width))
        for edge in item.edges:
            lines.append(Block.text(
                f"{edge_pad}→ {edge.address} via {edge.predicate}",
                fp.ref_edge_out, width=width))

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
                    # wcwidth-aware budget so CJK doesn't silently over-clip and
                    # the magnitude marker survives the column fit (was a
                    # len()-based elide → silent loss on wide chars).
                    avail = width - len(fact_pad) - len(ts_str) - 3
                    max_body = max(10, avail - 10)  # reserve for " [+Nc]"
                    fit = budget_fields(
                        [sf_body], max_body,
                        min_field=MIN_FIELD_BUDGET, sep=PREVIEW_SEPARATOR,
                    )
                    sf_body = fit.text + (
                        f" [+{fit.dropped}c]" if fit.dropped > 0 else ""
                    )
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
        if item.inbound > 0:
            lines.append(Block.text(f"{meta_pad}_inbound_refs: {item.inbound}", fp.meta, width=width))

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
        # Carry the section total on the piped/agent surface too — still valid
        # markdown H2 (friction:read-tty-truncation-not-defeatable kin: the
        # count was TTY-only, dropped on the dominant pipe path).
        return f"## {kind.upper()} ({count})"
    label = kind.title()
    if not kind.endswith("s"):
        label += "s"
    return f"{label} ({count}):"


def _predicate_summary(inbound_predicates: tuple[tuple[str, int], ...]) -> str:
    """Format an inbound predicate breakdown, but only when it adds information.

    Returns e.g. ``" (3 via stakeholder, 2 via ref)"`` when a typed edge is
    among the inbound predicates. A pure ``"ref"`` breakdown returns "" — the
    bare ``←N`` badge already carries it, so labeling adds nothing (keeps the
    grandfathered ref path visually unchanged).
    """
    preds = list(inbound_predicates)
    if not preds or all(p == "ref" for p, _ in preds):
        return ""
    return " (" + ", ".join(f"{c} via {p}" for p, c in preds) + ")"


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


# _recency_tag / _format_date / _format_ts_full now live in ._grammar
# (recency / short_date / full_iso) — imported at the top of this module.
