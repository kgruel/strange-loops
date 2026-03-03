"""Vertices lens — zoom-aware rendering for vertex listings."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical


def vertices_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render vertex listing at the given zoom level.

    data: {"vertices": [{name, path, kind, loops, store?, combine?, discover?}, ...]}

    Zoom levels:
    - MINIMAL: count only
    - SUMMARY: name + kind + brief loop summary per vertex
    - DETAILED: + indented loop names with fold types
    - FULL: + store paths, combine targets, discover patterns
    """
    vertices = data.get("vertices", [])

    if zoom == Zoom.MINIMAL:
        n = len(vertices)
        label = "vertex" if n == 1 else "vertices"
        return Block.text(f"{n} {label}", Style(), width=width)

    if not vertices:
        return Block.text(
            "No vertices discovered.", Style(dim=True), width=width,
        )

    dim = Style(dim=True)
    rows: list[Block] = []

    # Calculate column widths for alignment
    max_name = max(len(v["name"]) for v in vertices)
    max_kind = max(len(v["kind"]) for v in vertices)

    for v in vertices:
        name = v["name"].ljust(max_name)
        kind = v["kind"].ljust(max_kind)
        loops = v.get("loops", [])

        # Brief summary for SUMMARY+
        if v["kind"] == "aggregation":
            combine = v.get("combine", [])
            if combine:
                brief = f"combines {len(combine)}"
            else:
                brief = ""
        elif loops:
            loop_names = [l["name"] for l in loops]
            brief = ", ".join(loop_names)
        else:
            brief = ""

        line = f"  {name}  {kind}  {brief}"
        if len(line) > width:
            line = line[: width - 1] + "…"
        rows.append(Block.text(line, Style(), width=width))

        if zoom >= Zoom.DETAILED and loops:
            for l in loops:
                folds_str = ", ".join(l["folds"]) if l["folds"] else "no folds"
                detail = f"    {l['name']} ({folds_str})"
                if len(detail) > width:
                    detail = detail[: width - 1] + "…"
                rows.append(Block.text(detail, dim, width=width))

        if zoom >= Zoom.FULL:
            if "store" in v:
                rows.append(Block.text(f"    store: {v['store']}", dim, width=width))
            if "combine" in v:
                rows.append(Block.text(f"    combine: {', '.join(v['combine'])}", dim, width=width))
            if "discover" in v:
                rows.append(Block.text(f"    discover: {v['discover']}", dim, width=width))

    return join_vertical(*rows)
