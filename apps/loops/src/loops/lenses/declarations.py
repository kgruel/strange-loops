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

from painted import Block, Style, Zoom, join_vertical

from .store import _format_count, _relative_time


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


def declarations_view(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
    if "error" in data:
        return Block.text(f"Error: {data['error']}", Style(), width=width)

    # Prefer the new (filters/narrows) shape; fall back to legacy (filter).
    filters = data.get("filters")
    if filters is None:
        legacy = data.get("filter")
        filters = [legacy] if legacy else None
    narrows = data.get("narrows") or {}

    # Narrowed form — section-focused, back-compat (plan:vertex-living-document).
    if filters:
        return _render_narrowed(filters, data, zoom, width, narrows)

    # Default form — stat-over-containment: header + kinds-as-entries body.
    return _render_stat_view(data, zoom, width)


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
    if mtime is not None:
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        cols.append(f"updated {_relative_time(dt)}")
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
    data: dict[str, Any], zoom: Zoom, width: int | None
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
        cols.append(f"updated {_relative_time(dt)}")
    return Block.text("  " + "   ".join(cols), Style(), width=width)


def _render_narrowed(
    filters: list[str], data: dict[str, Any], zoom: Zoom, width: int | None,
    narrows: dict[str, str],
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
            blocks.append(
                Block.text(f"KINDS ({len(items) or '—'})", Style(bold=True), width=width)
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
