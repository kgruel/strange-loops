"""Docs lens — living documentation rendered progressively.

Renders all documentation kinds: vocab (primitives), contracts (API shapes),
conventions (invariants), patterns (composition), guides (workflows).
Each kind renders as a section. Vocab groups by category field; others
render flat by name/topic.

Zoom levels:
- MINIMAL: counts per kind — "30 vocab · 12 contracts · 5 patterns"
- SUMMARY: name + first sentence per entry, grouped by kind
- DETAILED: full descriptions, code/KDL examples, scope tags
- FULL: + observer, timestamp, all metadata
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# Display order for kinds
_KIND_ORDER = ["contract", "convention", "vocab", "pattern", "guide"]

# Within vocab, display order for categories
_VOCAB_CATEGORY_ORDER = ["fold", "boundary", "structure", "parse"]


def fold_view(
    data: "FoldState",
    zoom: Zoom,
    width: int | None,
    **kwargs: Any,
) -> Block:
    """Render docs fold as progressive reference."""
    plain = Style()
    bold = Style(bold=True)
    dim = Style(dim=True)

    sections = {s.kind: s for s in data.sections if s.items}

    if not sections:
        return Block.text("(empty)", dim, width=width)

    if zoom <= Zoom.MINIMAL:
        return _minimal(sections, plain, width)

    rows: list[Block] = []

    for kind in _KIND_ORDER:
        section = sections.get(kind)
        if not section:
            continue

        if kind == "vocab":
            _render_vocab(rows, section, zoom, width, bold, plain, dim)
        elif kind == "guide":
            _render_guides(rows, section, zoom, width, bold, plain, dim)
        else:
            _render_section(rows, section, kind, zoom, width, bold, plain, dim)

    # Any kinds not in _KIND_ORDER
    for kind, section in sections.items():
        if kind not in _KIND_ORDER:
            _render_section(rows, section, kind, zoom, width, bold, plain, dim)

    return join_vertical(*rows) if rows else Block.text("(empty)", dim)


# ---------------------------------------------------------------------------
# MINIMAL
# ---------------------------------------------------------------------------

def _minimal(
    sections: dict[str, "FoldSection"],
    plain: Style,
    width: int | None,
) -> Block:
    parts: list[str] = []
    for kind in _KIND_ORDER:
        if kind in sections:
            parts.append(f"{len(sections[kind].items)} {kind}")
    for kind in sections:
        if kind not in _KIND_ORDER:
            parts.append(f"{len(sections[kind].items)} {kind}")
    return Block.text(" · ".join(parts) if parts else "(empty)", plain, width=width)


# ---------------------------------------------------------------------------
# Vocab — grouped by category
# ---------------------------------------------------------------------------

def _render_vocab(
    rows: list[Block],
    section: "FoldSection",
    zoom: Zoom,
    width: int | None,
    bold: Style,
    plain: Style,
    dim: Style,
) -> None:
    items_by_cat = _group_by_field(section, "category")

    for cat in _VOCAB_CATEGORY_ORDER:
        if cat not in items_by_cat:
            continue
        items = items_by_cat[cat]
        rows.append(Block.text("", plain))
        rows.append(Block.text(
            f"## VOCAB / {cat.upper()} ({len(items)})",
            bold,
            width=width,
        ))
        for item in sorted(items, key=lambda i: i.payload.get("name", "")):
            _render_item(rows, item, section, zoom, width, bold, plain, dim)

    # Uncategorized vocab
    uncategorized = [
        i for i in section.items
        if i.payload.get("category", "") not in _VOCAB_CATEGORY_ORDER
    ]
    if uncategorized:
        rows.append(Block.text("", plain))
        rows.append(Block.text(
            f"## VOCAB / OTHER ({len(uncategorized)})",
            bold,
            width=width,
        ))
        for item in uncategorized:
            _render_item(rows, item, section, zoom, width, bold, plain, dim)


# ---------------------------------------------------------------------------
# Guides — progressive levels with rich structured payloads
# ---------------------------------------------------------------------------

def _render_guides(
    rows: list[Block],
    section: "FoldSection",
    zoom: Zoom,
    width: int | None,
    bold: Style,
    plain: Style,
    dim: Style,
) -> None:
    # Group by scope
    items_by_scope = _group_by_field(section, "scope")

    for scope in sorted(items_by_scope):
        items = items_by_scope[scope]
        # Sort by level
        items.sort(key=lambda i: int(i.payload.get("level", 99)))
        scope_label = scope if scope else "general"

        rows.append(Block.text("", plain))
        rows.append(Block.text(
            f"## GUIDE / {scope_label} ({len(items)} levels)",
            bold,
            width=width,
        ))

        for item in items:
            _render_guide_item(rows, item, zoom, width, bold, plain, dim)


def _render_guide_item(
    rows: list[Block],
    item: "FoldItem",
    zoom: Zoom,
    width: int | None,
    bold: Style,
    plain: Style,
    dim: Style,
) -> None:
    p = item.payload
    level = p.get("level", "?")
    title = p.get("title", p.get("name", "?"))
    trigger = p.get("trigger", "")
    msg = p.get("message", "")
    examples = p.get("examples", "")
    api = p.get("api", "")
    crossref = p.get("crossref", "")
    barrier = p.get("barrier", "")

    if zoom <= Zoom.MINIMAL:
        return  # MINIMAL handled at section level

    if zoom <= Zoom.SUMMARY:
        # Level title + trigger
        rows.append(Block.text("", plain))
        rows.append(Block.text(
            f"  Level {level} — {title}",
            bold,
            width=width,
        ))
        if trigger:
            rows.append(Block.text(f"    Trigger: {trigger}", dim, width=width))
        if msg:
            first = msg.split(". ")[0] + "."
            rows.append(Block.text(f"    {first}", plain, width=width))
        if barrier:
            rows.append(Block.text(
                f"    Don't reach for yet: {barrier}",
                dim,
                width=width,
            ))
        return

    # DETAILED and FULL — full progressive section
    rows.append(Block.text("", plain))
    rows.append(Block.text(
        f"  Level {level} — {title}",
        bold,
        width=width,
    ))

    if trigger:
        rows.append(Block.text(f"    Trigger: {trigger}", Style(italic=True), width=width))
        rows.append(Block.text("", plain))

    if examples:
        for line in examples.split("\n"):
            rows.append(Block.text(f"    {line}", dim, width=width))
        rows.append(Block.text("", plain))

    if msg:
        rows.append(Block.text(f"    {msg}", plain, width=width))

    if api:
        rows.append(Block.text("", plain))
        for line in api.split("\n"):
            rows.append(Block.text(f"    {line}", dim, width=width))

    if crossref:
        rows.append(Block.text("", plain))
        rows.append(Block.text(f"    {crossref}", Style(dim=True), width=width))

    if barrier:
        rows.append(Block.text("", plain))
        rows.append(Block.text(
            f"    Don't reach for yet: {barrier}",
            Style(bold=True, dim=True),
            width=width,
        ))

    if zoom >= Zoom.FULL and item.ts:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(item.ts, tz=timezone.utc)
        rows.append(Block.text(
            f"    observer: {item.observer}  "
            f"updated: {dt.strftime('%Y-%m-%d')}",
            dim,
            width=width,
        ))


# ---------------------------------------------------------------------------
# Generic section — contracts, conventions, patterns
# ---------------------------------------------------------------------------

def _render_section(
    rows: list[Block],
    section: "FoldSection",
    kind: str,
    zoom: Zoom,
    width: int | None,
    bold: Style,
    plain: Style,
    dim: Style,
) -> None:
    rows.append(Block.text("", plain))

    # Group by scope if present
    items_by_scope = _group_by_field(section, "scope")

    if len(items_by_scope) <= 1:
        # No meaningful scope grouping — render flat
        rows.append(Block.text(
            f"## {kind.upper()} ({len(section.items)})",
            bold,
            width=width,
        ))
        for item in sorted(section.items, key=lambda i: _item_label(i, section)):
            _render_item(rows, item, section, zoom, width, bold, plain, dim)
    else:
        # Group by scope
        total = len(section.items)
        rows.append(Block.text(
            f"## {kind.upper()} ({total})",
            bold,
            width=width,
        ))
        for scope in sorted(items_by_scope):
            items = items_by_scope[scope]
            scope_label = scope if scope else "general"
            rows.append(Block.text("", plain))
            rows.append(Block.text(
                f"  [{scope_label}]",
                Style(bold=True, dim=True),
                width=width,
            ))
            for item in sorted(items, key=lambda i: _item_label(i, section)):
                _render_item(rows, item, section, zoom, width, bold, plain, dim)


# ---------------------------------------------------------------------------
# Item rendering
# ---------------------------------------------------------------------------

def _render_item(
    rows: list[Block],
    item: "FoldItem",
    section: "FoldSection",
    zoom: Zoom,
    width: int | None,
    bold: Style,
    plain: Style,
    dim: Style,
) -> None:
    label = _item_label(item, section)
    msg = item.payload.get("message", "")
    kdl = item.payload.get("kdl", "")
    code = item.payload.get("code", "")
    status = item.payload.get("status", "")
    status_tag = f" [{status}]" if status else ""

    if zoom <= Zoom.SUMMARY:
        first_sentence = msg.split(". ")[0] + "." if msg else ""
        rows.append(Block.text(
            f"  {label}{status_tag}: {first_sentence}",
            plain,
            width=width,
        ))
    else:
        rows.append(Block.text(f"  {label}{status_tag}", bold, width=width))
        if kdl:
            rows.append(Block.text(f"    {kdl}", dim, width=width))
        if code:
            for line in code.split("\n"):
                rows.append(Block.text(f"    {line}", dim, width=width))
        if msg:
            rows.append(Block.text(f"    {msg}", plain, width=width))
        if zoom >= Zoom.FULL and item.ts:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(item.ts, tz=timezone.utc)
            rows.append(Block.text(
                f"    observer: {item.observer}  "
                f"updated: {dt.strftime('%Y-%m-%d')}",
                dim,
                width=width,
            ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item_label(item: "FoldItem", section: "FoldSection") -> str:
    """Extract display label from item."""
    key = section.key_field
    if key and item.payload.get(key):
        label = str(item.payload[key])
        # Strip scope prefix for cleaner display
        if "/" in label:
            return label.split("/", 1)[1]
        return label
    for field in ("name", "topic", "title"):
        if item.payload.get(field):
            return str(item.payload[field])
    return "?"


def _group_by_field(
    section: "FoldSection",
    field: str,
) -> dict[str, list["FoldItem"]]:
    """Group items by a payload field."""
    groups: dict[str, list["FoldItem"]] = {}
    for item in section.items:
        val = str(item.payload.get(field, ""))
        groups.setdefault(val, []).append(item)
    return groups
