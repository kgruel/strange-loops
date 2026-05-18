"""declarations lens — unified vertex view (KINDS / OBSERVERS / COMBINE / SOURCES).

Phase 3 of plan:vertex-living-document. Renders the structured output of
``loops.commands.ls.fetch_declarations`` at four zoom levels.
"""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical


_SECTIONS = ("kinds", "observers", "combine", "sources")
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

    if filters:
        visible_sections = [_FILTER_TO_SECTION[f] for f in filters]
    else:
        visible_sections = list(_SECTIONS)

    if zoom == Zoom.MINIMAL:
        # One-line counts, only for visible sections.
        parts = [data.get("vertex_name", "?")]
        for s in visible_sections:
            items = _narrow_section_items(s, data, narrows)
            parts.append(f"{s}={len(items)}")
        return Block.text(" ".join(parts), Style(), width=width)

    blocks: list[Block] = []
    for i, section in enumerate(visible_sections):
        if i > 0:
            blocks.append(Block.text("", Style(), width=width))
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
        "kinds": _render_kind,
        "observers": _render_observer,
        "combine": _render_combine_entry,
        "sources": _render_source,
    }[section]
    rows = [renderer(item, zoom, width) for item in items]
    return join_vertical(head, *rows)


def _render_kind(item: dict[str, str], zoom: Zoom, width: int | None) -> Block:
    name = item["name"]
    op = item["fold_op"]
    if zoom >= Zoom.DETAILED:
        target = item.get("target") or "items"
        return Block.text(
            f"  {name:<14} {target} {op}", Style(), width=width
        )
    return Block.text(f"  {name:<14} {op}", Style(), width=width)


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
