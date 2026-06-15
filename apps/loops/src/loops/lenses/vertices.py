"""Vertices lens — zoom-aware rendering for vertex listings."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical

from ._helpers import elide


def vertices_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render vertex listing at the given zoom level.

    data: {"vertices": [{name, path, kind, loops, store?, combine?, discover?}, ...],
           "local_vertices": [...]?,  # cwd layer — verbs resolve these first
           "cwd": str?}

    When ``local_vertices`` is present the listing renders in two labelled
    groups — local first, matching verb resolution order
    (thread:global-local-walk-broken). Without it, rendering is unchanged
    from the single-list form.

    Zoom levels:
    - MINIMAL: count only
    - SUMMARY: name + kind + brief loop summary per vertex
    - DETAILED: + indented loop names with fold types
    - FULL: + store paths, combine targets, discover patterns
    """
    vertices = data.get("vertices", [])
    local = data.get("local_vertices", [])

    if zoom == Zoom.MINIMAL:
        n = len(vertices)
        if local:
            m = len(local)
            return Block.text(
                f"{m} local + {n} config vertices", Style(), width=width,
            )
        label = "vertex" if n == 1 else "vertices"
        return Block.text(f"{n} {label}", Style(), width=width)

    if not vertices and not local:
        return Block.text(
            "No vertices discovered.", Style(dim=True), width=width,
        )

    dim = Style(dim=True)

    # Column widths computed across both groups so the table stays aligned.
    every = [*local, *vertices]
    max_name = max(len(v["name"]) for v in every)
    max_kind = max(len(v["kind"]) for v in every)

    if not local:
        return join_vertical(
            *_vertex_rows(vertices, zoom, width, max_name, max_kind, dim)
        )

    rows: list[Block] = [
        Block.text("local — cwd, verbs resolve these first", dim, width=width),
        *_vertex_rows(local, zoom, width, max_name, max_kind, dim),
        Block.text("config — ~/.config/loops", dim, width=width),
        *_vertex_rows(vertices, zoom, width, max_name, max_kind, dim),
    ]
    return join_vertical(*rows)


def _vertex_rows(
    vertices: list[dict[str, Any]],
    zoom: Zoom,
    width: int,
    max_name: int,
    max_kind: int,
    dim: Style,
) -> list[Block]:
    """Rows for one group of vertices — shared by both layers."""
    rows: list[Block] = []

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
            loop_names = [lp["name"] for lp in loops]
            brief = ", ".join(loop_names)
        else:
            brief = ""

        line = f"  {name}  {kind}  {brief}"
        # The shadow marker is the load-bearing signal — it survives
        # truncation; the brief gives way first.
        marker = "  ⊳ shadows config" if v.get("shadows") else ""
        avail = width - len(marker)
        line = elide(line, avail)
        line += marker
        rows.append(Block.text(line, Style(), width=width))

        if zoom >= Zoom.DETAILED and loops:
            for lp in loops:
                folds_str = ", ".join(lp["folds"]) if lp["folds"] else "no folds"
                detail = elide(f"    {lp['name']} ({folds_str})", width)
                rows.append(Block.text(detail, dim, width=width))

        if zoom >= Zoom.FULL:
            if "store" in v:
                rows.append(Block.text(f"    store: {v['store']}", dim, width=width))
            if "combine" in v:
                rows.append(Block.text(f"    combine: {', '.join(v['combine'])}", dim, width=width))
            if "discover" in v:
                rows.append(Block.text(f"    discover: {v['discover']}", dim, width=width))

    return rows
