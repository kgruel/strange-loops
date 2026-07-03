"""declarations lens — `sl ls <vertex>` as stat-over-containment.

The default (unnarrowed) view leads with the vertex stat header (type / Σfacts /
kind-count / last-update) and lists its KINDS as containment entries with live
count / share / mtime columns — the "what's inside this directory" descent
(decision:design/ls-as-stat-over-containment). The declarations that used to be
top-level sections (observers / combine / sources) become a header summary, and
surface in full at DETAILED+ or when narrowed to with ``--observer`` / etc.

Narrowing (``--kind`` / ``--observer`` / ``--combine`` / ``--row``) preserves
the section-focused back-compat behavior from plan:vertex-living-document.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Align, Block, Line, Style, Wrap, Zoom, join_vertical, vslice
from painted.views import Column, Fill

from ._statview import (
    card,
    card_width,
    cell,
    freshness_style,
    meter_cell,
    palette_of,
    spark,
    stat_table,
    updated_text,
)
from ._grammar import recency
from .store import _format_count


_SECTION_TITLES = {
    "kinds": "KINDS",
    "observers": "OBSERVERS",
    "combine": "COMBINE",
    "sources": "SOURCES",
}
# Filter sub-verb / flag name -> section key in data.
_FILTER_TO_SECTION = {
    "kind": "kinds",
    "observer": "observers",
    "combine": "combine",
    "row": "sources",
}
# Inverse: section key -> the field on each row that names the entry. Used
# when a per-section narrow (e.g. ``--kind decision``) is in effect.
_SECTION_NAME_FIELD = {
    "kinds": "name",
    "observers": "name",
    "combine": "path",
    "sources": "template",
}


def declarations_view(
    data: dict[str, Any], zoom: Zoom, width: int | None, *, piped: bool = False
) -> Block:
    """Render the vertex's containment listing.

    Two registers (decision:design/presentation-register-keys-on-channel):
    the TTY/human path (``piped=False``) draws a rounded stat card over a clean
    columnar table with a share meter, density sparkline, and freshness-graded
    "updated" column; the pipe/agent path (``piped=True``) stays terse aligned
    text, monochrome, with no visual-only columns. Colour strips at the writer
    regardless of ``piped``; the *structural* divergence is keyed here.
    """
    if "error" in data:
        return Block.text(f"Error: {data['error']}", Style(), width=width)

    # The piped/agent register is information-faithful — never truncate to a
    # terminal edge (ctx.width may inherit COLUMNS even on a pipe). Render
    # width-free so no stat cell is clipped (e.g. "115d ago" → "115d ag").
    if piped:
        width = None

    # Prefer the new (filters/narrows) shape; fall back to legacy (filter).
    filters = data.get("filters")
    if filters is None:
        legacy = data.get("filter")
        filters = [legacy] if legacy else None
    narrows = data.get("narrows") or {}

    # Narrowed form — section-focused, back-compat (plan:vertex-living-document).
    if filters:
        return _render_narrowed(filters, data, zoom, width, narrows, piped)

    # Default form — stat-over-containment: header + kinds-as-entries body.
    return _render_stat_view(data, zoom, width, piped)


def _vertex_header(data: dict[str, Any], width: int | None) -> list[Block]:
    """The vertex stat line + declaration-summary subline."""
    name = data.get("vertex_name", "?")
    vkind = data.get("vertex_kind", "instance")
    facts = data.get("facts")
    kc = data.get("kind_count")
    mtime = data.get("mtime")

    cols = [name, vkind]
    cols.append(f"{_format_count(facts)} facts" if facts is not None else "—")
    if kc:
        cols.append(f"{kc} kinds")
    # signed ratio is data (not chrome) — carry it on both registers (the TTY
    # card shows it too) so the piped channel stays information-faithful.
    signed = data.get("signed")
    if signed:
        cols.append(f"signed {_format_count(signed[0])}/{_format_count(signed[1])}")
    if mtime is not None:
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        cols.append(f"updated {recency(dt)}")
    head = Block.text("   ".join(cols), Style(bold=True), width=width)

    nobs = len(data.get("observers") or [])
    ncomb = len(data.get("combine") or [])
    nsrc = len(data.get("sources") or [])
    sub_parts = []
    if nobs:
        sub_parts.append(f"{nobs} observer{'s' if nobs != 1 else ''}")
    if ncomb:
        sub_parts.append(f"{ncomb} combine")
    if nsrc:
        sub_parts.append(f"{nsrc} source{'s' if nsrc != 1 else ''}")
    blocks = [head]
    if sub_parts:
        blocks.append(
            Block.text("  " + " · ".join(sub_parts), Style(dim=True), width=width)
        )
    return blocks


def _render_stat_view(
    data: dict[str, Any], zoom: Zoom, width: int | None, piped: bool = False
) -> Block:
    """Default `sl ls <vertex>` — stat header + kinds-as-entries body."""
    name = data.get("vertex_name", "?")
    facts = data.get("facts")
    kc = data.get("kind_count")

    if zoom == Zoom.MINIMAL:
        parts = [name]
        if facts is not None:
            parts.append(f"{_format_count(facts)} facts")
        if kc:
            parts.append(f"{kc} kinds")
        return Block.text(" · ".join(parts), Style(), width=width)

    if not piped:
        return _render_stat_view_tty(data, zoom, width)

    blocks: list[Block] = [*_vertex_header(data, width)]
    blocks.append(Block.text("", Style(), width=width))
    blocks.extend(_render_kind_body(data.get("kinds") or [], zoom, width))

    # The declaration detail (observers/combine/sources) drops below the body
    # at DETAILED+; at SUMMARY it stays folded into the header subline.
    if zoom >= Zoom.DETAILED:
        for section in ("observers", "combine", "sources"):
            if data.get(section):
                blocks.append(Block.text("", Style(), width=width))
                blocks.append(_render_section(section, data, zoom, width, {}))

    return join_vertical(*blocks)


# ---------------------------------------------------------------------------
# TTY register — boxed stat card + clean columnar table
# ---------------------------------------------------------------------------


def _vertex_card_sublines(data: dict[str, Any]) -> list[str]:
    """The stat lines inside the header card: totals, then a declaration tally."""
    facts = data.get("facts")
    kc = data.get("kind_count")
    signed = data.get("signed")
    mtime = data.get("mtime")

    bits: list[str] = []
    if facts is not None:
        bits.append(f"{_format_count(facts)} facts")
    if kc:
        bits.append(f"{kc} kinds")
    if signed:
        bits.append(f"signed {_format_count(signed[0])}/{_format_count(signed[1])}")
    if mtime is not None:
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        bits.append(f"updated {recency(dt)}")

    sub = [" · ".join(bits)] if bits else []
    decl = _decl_tally(data)
    if decl:
        sub.append(decl)
    return sub


def _decl_tally(data: dict[str, Any]) -> str:
    """`3 observers · 1 combine · 2 sources` — the declaration summary."""
    nobs = len(data.get("observers") or [])
    ncomb = len(data.get("combine") or [])
    nsrc = len(data.get("sources") or [])
    parts: list[str] = []
    if nobs:
        parts.append(f"{nobs} observer{'s' if nobs != 1 else ''}")
    if ncomb:
        parts.append(f"{ncomb} combine")
    if nsrc:
        parts.append(f"{nsrc} source{'s' if nsrc != 1 else ''}")
    return " · ".join(parts)


def _render_stat_view_tty(
    data: dict[str, Any], zoom: Zoom, width: int | None
) -> Block:
    """Rich TTY listing — header card over the kinds table."""
    p = palette_of(None)
    name = data.get("vertex_name", "?")
    vkind = data.get("vertex_kind", "instance")
    kinds = data.get("kinds") or []

    body = _kind_table(kinds, width, p)
    sublines = _vertex_card_sublines(data)
    title = f"{name} · {vkind}"
    card_w = card_width(body, title, sublines, width)
    head = card(title, sublines, card_w, p=p)

    blocks: list[Block] = [head, Block.empty(card_w, 1), body]

    if zoom >= Zoom.DETAILED:
        for section in ("observers", "combine", "sources"):
            if data.get(section):
                blocks.append(Block.empty(card_w, 1))
                blocks.append(_render_section(section, data, zoom, width, {}))

    return join_vertical(*blocks)


def _kind_dt(latest: Any) -> datetime | None:
    """Coerce a kind's `latest` (epoch float or datetime) to an aware datetime."""
    if latest is None:
        return None
    if isinstance(latest, datetime):
        return latest
    return datetime.fromtimestamp(float(latest), tz=timezone.utc)


def _share_cell(share: float, max_pct: float, p: Any) -> Line:
    """Share meter + exact percent — a ranked bar scaled to the listing's max."""
    return meter_cell(share, max_pct, f"{share:>4.1f}%", p)


# A kind below this fact count is "minor" — vestigial/system kinds (old pings,
# one-off rebirths, stray system kinds). Kept (faithful listing) but demoted
# below a rule and dimmed, so the eye skips the tail without losing the census.
_MINOR_FLOOR = 10

# Below this terminal width the decorative TREND column is dropped so the dense
# six-column kinds table still fits (narrow-terminal graceful degradation).
_TREND_MIN_WIDTH = 64


def _kind_columns(
    kinds: list[dict[str, Any]], has_trend: bool, has_time: bool,
    *, name_kinds: list[dict[str, Any]] | None = None,
) -> list[Column]:
    """Columns sized across *all* kinds, so the substantive and minor rows align
    under one shared header (the name column fills/shrinks, numerics fixed).

    ``name_kinds`` overrides the set the KIND column sizes to: when a minor tail
    is split off, the column sizes to the *substantive* names so one long
    vestigial kind name doesn't stretch the important rows — the minor names
    ellipsize into the shared width instead (Fill + ellipsis). Numeric columns
    still size across *all* kinds, so a wide minor mtime ("121d ago") fits.
    """
    def w(texts: list[str], header: str) -> int:
        return max([len(header)] + [len(t) for t in texts])

    name_w = min(22, w([k["name"] for k in (name_kinds or kinds)], "KIND"))
    fold_w = w([(k.get("fold_op") or "—").replace('"', "") for k in kinds], "FOLD")
    count_w = w([_format_count(k.get("count", 0)) for k in kinds], "COUNT")
    share_w = max(len("SHARE"), 7 + 1 + 6)  # bar + space + "NN.N%"
    # KIND fills to its natural width (max_width) on a roomy terminal but
    # shrinks+ellipsizes when the budget is tight — so the table honours width
    # (Overflow.FIT can only shrink Fill columns). The numeric columns stay fixed.
    cols = [
        Column(cell("KIND"), width=Fill(), min_width=6, max_width=name_w, ellipsis=True),
        Column(cell("FOLD"), width=fold_w),
        Column(cell("COUNT"), width=count_w, align=Align.END),
        # END-align so the exact percent right-aligns across the column — the
        # substantive meter (bar + percent) and a demoted minor row (bare
        # percent, no bar) then share one decimal-aligned right edge.
        Column(cell("SHARE"), width=share_w, align=Align.END),
    ]
    if has_trend:
        cols.append(Column(cell("TREND"), width=8))
    if has_time:
        upd_w = w(
            [updated_text(_kind_dt(k.get("latest"))) for k in kinds
             if k.get("latest") is not None] or [""],
            "UPDATED",
        )
        cols.append(Column(cell("UPDATED"), width=upd_w, align=Align.END))
    return cols


def _kind_cells(
    k: dict[str, Any], max_pct: float, has_trend: bool, has_time: bool,
    p: Any, *, dim: bool,
) -> list[Line]:
    """One kind's row. ``dim`` renders the minor register — no kind colour, no
    bar/sparkline, freshness flattened — so demoted rows recede."""
    fold_op = (k.get("fold_op") or "—").replace('"', "")
    if dim:
        row = [
            cell(k["name"], p.metadata),
            cell(fold_op, p.metadata),
            cell(_format_count(k.get("count", 0)), p.metadata),
            cell(f"{k.get('share', 0.0):>4.1f}%", p.metadata),
        ]
        if has_trend:
            row.append(cell("", p.metadata))
        if has_time:
            row.append(cell(updated_text(_kind_dt(k.get("latest"))), p.metadata))
        return row
    row = [
        cell(k["name"], p.kind_style(k["name"])),
        cell(fold_op, p.metadata),
        cell(_format_count(k.get("count", 0))),
        _share_cell(k.get("share", 0.0), max_pct, p),
    ]
    if has_trend:
        row.append(cell(spark(k.get("trend") or []), Style(fg="cyan")))
    if has_time:
        dt = _kind_dt(k.get("latest"))
        row.append(cell(updated_text(dt), freshness_style(p, dt)))
    return row


def _labeled_rule(label: str, width: int, p: Any) -> Block:
    """A centred ``──── label ────`` divider."""
    tag = f" {label} "
    fill = max(0, width - len(tag))
    left = fill // 2
    line = "─" * left + tag + "─" * (fill - left)
    return Block.text(line[:width], p.chrome, width=width)


def _kind_table(kinds: list[dict[str, Any]], width: int | None, p: Any) -> Block:
    """The containment body — one stat row per kind. When a substantive set and
    a low-count tail coexist, the tail demotes below a ``minor`` rule, dimmed."""
    if not kinds:
        return Block.text("  (no kinds)", p.metadata, width=width)

    max_pct = max((k.get("share", 0.0) for k in kinds), default=0.0)
    has_time = any(k.get("latest") is not None for k in kinds)
    # TREND is decorative; the other columns have hard floors, so when the budget
    # is too tight to seat all six, drop TREND first (graceful narrow-terminal
    # degradation — below this the dense table would overflow regardless).
    has_trend = any(k.get("trend") for k in kinds) and (
        width is None or width >= _TREND_MIN_WIDTH
    )

    substantive = [k for k in kinds if k.get("count", 0) >= _MINOR_FLOOR]
    minor = [k for k in kinds if k.get("count", 0) < _MINOR_FLOOR]
    # Only split when it earns its keep: a clear substantive set plus a tail.
    splitting = bool(substantive) and len(minor) >= 3

    # When splitting, size KIND to the substantive names (minor names ellipsize).
    cols = _kind_columns(
        kinds, has_trend, has_time,
        name_kinds=substantive if splitting else None,
    )

    def rows_of(ks: list[dict[str, Any]], *, dim: bool) -> list[list[Line]]:
        return [_kind_cells(k, max_pct, has_trend, has_time, p, dim=dim) for k in ks]

    if splitting:
        # Render as ONE table so the Fill KIND column sizes once across *all*
        # rows — two separate table() calls would each fit-shrink Fill to their
        # own content (substantive ~"tick.project" vs minor "friction:emit-…"),
        # drifting every column right of KIND. Slice the rendered block to drop
        # the labelled rule between the substantive set and the dimmed tail.
        all_rows = rows_of(substantive, dim=False) + rows_of(minor, dim=True)
        full = stat_table(cols, all_rows, width, p=p)
        n_head = 2  # header row + separator rule
        top = vslice(full, 0, n_head + len(substantive))
        bottom = vslice(full, n_head + len(substantive), len(minor))
        return join_vertical(top, _labeled_rule("minor", full.width, p), bottom)

    return stat_table(cols, rows_of(kinds, dim=False), width, p=p)


# ---------------------------------------------------------------------------
# `ls <vertex> --kind <K>` — the kind stat view (descent to entries, not facts)
# ---------------------------------------------------------------------------

_ENTRY_CAP = 30


def _entry_noun(data: dict[str, Any]) -> str:
    if data.get("by") == "observer":
        return "observers"
    kf = data.get("key_field") or "key"
    return {"topic": "topics", "name": "names"}.get(kf, f"{kf}s")


def _span_str(earliest: Any, latest: Any) -> str:
    lo, hi = _kind_dt(earliest), _kind_dt(latest)
    if lo is None or hi is None:
        return ""
    return f"{lo:%b %d}–{hi:%b %d}"


def _entry_style(key: str, leaf: bool, p: Any) -> Style:
    """Colour an entry like ``ls`` colours a tree: namespaces (drillable) pop,
    leaves are plain, the orphan bucket dims."""
    if key.startswith("(no ") or key == "(none)":
        return p.metadata
    if not leaf:
        return Style(fg="blue", bold=True)
    return p.content


def _kind_card_sublines(data: dict[str, Any]) -> list[str]:
    count = data.get("count", 0)
    share = data.get("share", 0.0)
    vname = data.get("vertex_name", "?")
    noun = _entry_noun(data)
    distinct = data.get("distinct_keys", 0)

    line1 = [f"{_format_count(count)} facts", f"{share:.1f}% of {vname}"]
    if data.get("key_prefix"):
        line1.append(f"under {data['key_prefix']}")
    sub = [" · ".join(line1)]

    line2 = [f"{distinct} {noun}"]
    span = _span_str(data.get("earliest"), data.get("latest"))
    if span:
        line2.append(f"span {span}")
    latest_dt = _kind_dt(data.get("latest"))
    if latest_dt is not None:
        line2.append(f"updated {recency(latest_dt)}")
    sub.append(" · ".join(line2))
    return sub


def _entry_table(
    data: dict[str, Any], width: int | None, p: Any
) -> tuple[Block, str]:
    """The entries body (one stat row per namespace/leaf/observer) + a hint
    footer. Capped at ``_ENTRY_CAP`` rows with a ``+N more`` note."""
    entries = data.get("entries") or []
    by = data.get("by", "key")
    if not entries:
        return Block.text("  (no entries)", p.metadata, width=width), ""

    # Share is relative to the *view* (the kind, or the drilled subtree) so each
    # level reads as "share of its parent"; the bar scales to the leading row.
    view_total = sum(e["count"] for e in entries) or 1
    shown = entries[:_ENTRY_CAP]
    max_count = max((e["count"] for e in shown), default=0)
    has_time = any(e.get("latest") is not None for e in shown)

    # ENTRY fills, capped at 40 (keys can be long); shrinks+ellipsizes when the
    # terminal is narrow so the table honours width (FIT shrinks Fill columns).
    cols = [
        Column(
            cell("OBSERVER" if by == "observer" else "ENTRY"),
            width=Fill(), min_width=10, max_width=40, ellipsis=True,
        ),
        Column(cell("COUNT"), align=Align.END),
        Column(cell("SHARE")),
    ]
    if has_time:
        cols.append(Column(cell("UPDATED"), align=Align.END))

    has_ns = False
    rows: list[list[Line]] = []
    for e in shown:
        key, cnt, leaf = e["key"], e["count"], e.get("leaf", True)
        has_ns = has_ns or not leaf
        pct = cnt / view_total * 100
        row = [
            cell(key, _entry_style(key, leaf, p)),
            cell(_format_count(cnt)),
            meter_cell(cnt, max_count, f"{pct:>4.1f}%", p),
        ]
        if has_time:
            dt = _kind_dt(e.get("latest"))
            row.append(cell(updated_text(dt), freshness_style(p, dt)))
        rows.append(row)

    tbl = stat_table(cols, rows, width, p=p)

    foot: list[str] = []
    if len(entries) > len(shown):
        foot.append(f"+{len(entries) - len(shown)} more")
    if has_ns:
        foot.append("--key <ns>/ to drill")
    foot.append(f"read {data.get('vertex_name', '?')} --kind {data['kind']} for content")
    return tbl, "  " + " · ".join(foot)


def kind_stat_view(
    data: dict[str, Any], zoom: Zoom, width: int | None, *, piped: bool = False
) -> Block:
    """Render ``ls <vertex> --kind <K>`` — the kind's stat header over its
    entries one containment level down (namespaces / leaf keys / observers).
    Never the facts: that is ``read`` (decision:design/ls-as-stat-over-containment).
    """
    if "error" in data:
        return Block.text(f"Error: {data['error']}", Style(), width=width)

    # Piped/agent register is information-faithful — render width-free so no
    # entry row is clipped (see declarations_view).
    if piped:
        width = None

    kind = data.get("kind", "?")
    fold_op = (data.get("fold_op") or "").replace('"', "")

    if zoom == Zoom.MINIMAL:
        parts = [kind]
        if fold_op:
            parts.append(fold_op)
        parts.append(f"{_format_count(data.get('count', 0))} facts")
        if data.get("key_prefix"):
            parts.append(f"under {data['key_prefix']}")
        parts.append(f"{data.get('distinct_keys', 0)} {_entry_noun(data)}")
        return Block.text(" · ".join(parts), Style(), width=width)

    if piped:
        return _kind_stat_plain(data, width)

    p = palette_of(None)
    body, footer = _entry_table(data, width, p)
    sublines = _kind_card_sublines(data)
    title = f"{kind} · {fold_op}" if fold_op else kind
    card_w = card_width(body, title, sublines, width)
    head = card(title, sublines, card_w, p=p)

    blocks = [head, Block.empty(card_w, 1), body]
    if footer:
        blocks.append(Block.empty(card_w, 1))
        blocks.append(Block.text(footer, p.metadata, width=width, wrap=Wrap.ELLIPSIS))
    return join_vertical(*blocks)


def _kind_stat_plain(data: dict[str, Any], width: int | None) -> Block:
    """Pipe/agent register for the kind stat view — terse aligned rows."""
    kind = data.get("kind", "?")
    entries = data.get("entries") or []
    head = f"{kind} ({_format_count(data.get('count', 0))})"
    if data.get("key_prefix"):
        head += f" under {data['key_prefix']}"
    lines: list[Block] = [Block.text(head, Style(bold=True), width=width)]

    # Parity: carry the kind's share / span / freshness the TTY card shows, so
    # the piped channel is information-faithful (these are data, not chrome).
    meta = [
        f"{data.get('share', 0.0):.1f}% of {data.get('vertex_name', '?')}",
        f"{data.get('distinct_keys', 0)} {_entry_noun(data)}",
    ]
    span = _span_str(data.get("earliest"), data.get("latest"))
    if span:
        meta.append(f"span {span}")
    ldt = _kind_dt(data.get("latest"))
    if ldt is not None:
        meta.append(f"updated {recency(ldt)}")
    lines.append(Block.text("  " + " · ".join(meta), Style(dim=True), width=width))

    if not entries:
        lines.append(Block.text("  (no entries)", Style(dim=True), width=width))
        return join_vertical(*lines)

    view_total = sum(e["count"] for e in entries) or 1
    shown = entries[:_ENTRY_CAP]
    name_w = max((len(str(e["key"])) for e in shown), default=8)
    for e in shown:
        pct = e["count"] / view_total * 100
        upd = updated_text(_kind_dt(e.get("latest")))
        lines.append(Block.text(
            f"  {str(e['key']).ljust(name_w)}  {_format_count(e['count']):>6}  "
            f"{pct:5.1f}%  {upd}",
            Style(), width=width,
        ))
    if len(entries) > len(shown):
        lines.append(Block.text(
            f"  +{len(entries) - len(shown)} more", Style(dim=True), width=width
        ))
    return join_vertical(*lines)


def _render_kind_body(
    kinds: list[dict[str, Any]], zoom: Zoom, width: int | None
) -> list[Block]:
    """The containment body — one stat row per kind (count/share/mtime).

    At DETAILED+ each declared kind gains a dim sub-line carrying its fold
    target and declared preview fields (the declaration detail that used to
    live in the old KINDS section).
    """
    if not kinds:
        return [Block.text("  (no kinds)", Style(dim=True), width=width)]
    name_w = max((len(k["name"]) for k in kinds), default=8)
    op_w = max((len(k.get("fold_op") or "") for k in kinds), default=0)
    rows: list[Block] = []
    for k in kinds:
        rows.append(_render_kind_stat(k, name_w, op_w, width))
        if zoom >= Zoom.DETAILED:
            detail = _kind_decl_detail(k)
            if detail:
                rows.append(
                    Block.text(f"    {detail}", Style(dim=True), width=width)
                )
    return rows


def _kind_decl_detail(item: dict[str, Any]) -> str:
    """Fold target + declared preview fields for a kind (DETAILED+ sub-line)."""
    bits = []
    target = item.get("target")
    if target:
        bits.append(f"target={target}")
    preview = item.get("preview_fields") or ()
    if preview:
        bits.append(f"preview={','.join(preview)}")
    return "  ".join(bits)


def _render_kind_stat(
    item: dict[str, Any], name_w: int, op_w: int, width: int | None
) -> Block:
    # First column is a fixed name+op block so the count column aligns whether
    # or not a kind is declared (undeclared system kinds have an empty op).
    first = item["name"].ljust(name_w) + "  " + (item.get("fold_op") or "").ljust(op_w)
    count = item.get("count", 0)
    share = item.get("share", 0.0)
    cols = [first.rstrip() if not op_w else first, f"{count:>6}", f"{share:>5.1f}%"]
    latest = item.get("latest")
    if latest is not None:
        dt = latest if isinstance(latest, datetime) else datetime.fromtimestamp(
            float(latest), tz=timezone.utc
        )
        cols.append(f"updated {recency(dt)}")
    return Block.text("  " + "   ".join(cols), Style(), width=width)


def _render_narrowed(
    filters: list[str], data: dict[str, Any], zoom: Zoom, width: int | None,
    narrows: dict[str, str], piped: bool = False,
) -> Block:
    """Section-focused narrowed view (--kind / --observer / --combine / --row)."""
    visible_sections = [_FILTER_TO_SECTION[f] for f in filters]

    if zoom == Zoom.MINIMAL:
        parts = [data.get("vertex_name", "?")]
        for s in visible_sections:
            items = _narrow_section_items(s, data, narrows)
            parts.append(f"{s}={len(items)}")
        return Block.text(" ".join(parts), Style(), width=width)

    blocks: list[Block] = []
    for i, section in enumerate(visible_sections):
        if i > 0:
            blocks.append(Block.text("", Style(), width=width))
        if section == "kinds":
            # Kinds narrow to the stat body (containment entries), not the
            # old declaration-only rows.
            items = _narrow_section_items("kinds", data, narrows)
            if not piped:
                blocks.append(_kind_table(items, width, palette_of(None)))
            else:
                blocks.append(
                    Block.text(
                        f"KINDS ({len(items) or '—'})", Style(bold=True), width=width
                    )
                )
                blocks.extend(_render_kind_body(items, zoom, width))
        else:
            blocks.append(_render_section(section, data, zoom, width, narrows))
    return join_vertical(*blocks) if blocks else Block.text("", Style(), width=width)


def _narrow_section_items(
    section: str, data: dict[str, Any], narrows: dict[str, str],
) -> list[dict[str, Any]]:
    """Apply the optional per-section name narrowing to raw items.

    A narrowing miss (NAME matches nothing) renders an empty section — same
    convention as ``read --kind <unknown>``.
    """
    items = list(data.get(section) or [])
    # narrows is keyed by the section sub-verb (kind/observer/combine/row),
    # not the data-section key (kinds/observers/combine/sources).
    inv = {v: k for k, v in _FILTER_TO_SECTION.items()}
    verb = inv[section]
    name_field = _SECTION_NAME_FIELD[section]
    needle = narrows.get(verb)
    if needle is None:
        return items
    return [it for it in items if it.get(name_field) == needle]


def _render_section(
    section: str, data: dict[str, Any], zoom: Zoom, width: int | None,
    narrows: dict[str, str],
) -> Block:
    items = _narrow_section_items(section, data, narrows)
    title = _SECTION_TITLES[section]
    count_repr = str(len(items)) if items else "—"
    head = Block.text(
        f"{title} ({count_repr})", Style(bold=True), width=width
    )
    if not items:
        return head

    renderer = {
        "observers": _render_observer,
        "combine": _render_combine_entry,
        "sources": _render_source,
    }[section]
    rows = [renderer(item, zoom, width) for item in items]
    return join_vertical(head, *rows)


def _render_observer(
    item: dict[str, Any], zoom: Zoom, width: int | None
) -> Block:
    name = item["name"]
    bits = [name]
    if zoom >= Zoom.DETAILED:
        if "identity" in item:
            bits.append(f"identity={item['identity']}")
        if "grants" in item:
            bits.append(f"grants={','.join(item['grants'])}")
    return Block.text("  " + "  ".join(bits), Style(), width=width)


def _render_combine_entry(
    item: dict[str, str], zoom: Zoom, width: int | None
) -> Block:
    path = item["path"]
    if "alias" in item:
        return Block.text(
            f"  {path}  (as {item['alias']})", Style(), width=width
        )
    return Block.text(f"  {path}", Style(), width=width)


def _render_source(
    pop: dict[str, Any], zoom: Zoom, width: int | None
) -> Block:
    tname = pop["template"]
    header = pop.get("header") or []
    rows = pop.get("rows") or []
    list_path = pop.get("list_path", "")
    list_name = list_path.rsplit("/", 1)[-1] if list_path else ""

    head_text = f"  {tname}  [{list_name}]  ({len(rows)} rows)"
    head_block = Block.text(head_text, Style(bold=True), width=width)
    if zoom == Zoom.SUMMARY or not header:
        return head_block

    # DETAILED+: render rows aligned by header columns.
    col_widths = {h: len(h) for h in header}
    for r in rows:
        for h in header:
            col_widths[h] = max(col_widths[h], len(str(r.get(h, ""))))

    def fmt(values: dict[str, str]) -> str:
        return "  ".join(
            str(values.get(h, "")).ljust(col_widths[h]) for h in header
        )

    body: list[Block] = [head_block]
    body.append(
        Block.text(
            "    " + fmt({h: h for h in header}),
            Style(bold=True),
            width=width,
        )
    )
    limit = len(rows) if zoom == Zoom.FULL else min(5, len(rows))
    for r in rows[:limit]:
        body.append(Block.text("    " + fmt(r), Style(), width=width))
    if limit < len(rows):
        body.append(
            Block.text(
                f"    ... {len(rows) - limit} more rows",
                Style(dim=True),
                width=width,
            )
        )
    return join_vertical(*body)
