"""Trace index lens — kind-level drill-down menu.

Rendered when ``sl trace <vertex>`` is invoked without a ``kind/key`` entity.
Shows the kinds present in the vertex with item counts and explicit hints
for the next drill-down level (``sl trace <vertex> <kind>/``).

Two drill-down levels exist below this view:
    sl trace <vertex>                — this index (kinds + counts)
    sl trace <vertex> <kind>/        — kind-wide listing (entities in kind)
    sl trace <vertex> <kind>/<key>   — entity lifecycle

Data contract: a ``FoldState`` (from ``atoms``) and a ``vertex_name`` passed
through ``call_lens``.

Zoom levels:

- MINIMAL: one line — ``<vertex> — N kinds, M entities``
- SUMMARY: header + kind list (count + drill-down hint)
- DETAILED/FULL: + fold-type and key-field per kind
"""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical


def trace_index_view(
    data: Any, zoom: Zoom, width: int | None,
    vertex_name: str | None = None,
) -> Block:
    """Render kind-level index for ``sl trace <vertex>``."""
    sections = getattr(data, "sections", ())
    vname = vertex_name or getattr(data, "vertex", "") or "vertex"

    kinds: list[tuple[str, int, str | None, str | None]] = []
    for section in sections:
        count = len(section.items)
        if count == 0:
            continue
        kinds.append((
            section.kind, count, section.fold_type, section.key_field,
        ))
    kinds.sort(key=lambda row: -row[1])

    total_entities = sum(row[1] for row in kinds)

    plain = Style()
    bold = Style(bold=True)
    dim = Style(dim=True)

    def _t(s: str, style: Style = plain) -> Block:
        if width is not None:
            return Block.text(s, style, width=width)
        return Block.text(s, style)

    if zoom == Zoom.MINIMAL:
        line = f"{vname} — {len(kinds)} kind{'' if len(kinds) == 1 else 's'}, {total_entities} entit{'y' if total_entities == 1 else 'ies'}"
        return _t(line)

    if not kinds:
        header = _t(f"trace {vname}", bold)
        empty = _t("No entities in this vertex.", dim)
        return join_vertical(header, _t(""), empty)

    header = _t(f"trace {vname} — {len(kinds)} kinds, {total_entities} entities", bold)

    kind_width = max(len(row[0]) for row in kinds)
    rows: list[Block] = []
    for kind, count, fold_type, key_field in kinds:
        left = f"  {kind:<{kind_width}}  {count:>5}"
        hint = f"   sl trace {vname} {kind}/"
        if zoom >= Zoom.DETAILED and key_field:
            meta = f"   ({fold_type} {key_field})" if fold_type else f"   (by {key_field})"
            rows.append(_t(left + hint + meta))
        elif zoom >= Zoom.DETAILED and fold_type:
            meta = f"   ({fold_type})"
            rows.append(_t(left + hint + meta))
        else:
            rows.append(_t(left + hint))

    footer = _t(
        "  append a key prefix to drill in (e.g. sl trace "
        + vname + " "
        + kinds[0][0] + "/<prefix>)",
        dim,
    )

    return join_vertical(header, _t(""), *rows, _t(""), footer)
