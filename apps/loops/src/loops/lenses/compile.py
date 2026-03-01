"""Compile lens — zoom-aware rendering for compiled AST structure."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical


def compile_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render compiled AST at the given zoom level.

    data keys depend on file type:
      .loop:   {type: "loop", name, command, kind, observer, every, format, parse}
      .vertex: {type: "vertex", name, store, discover, emit, specs, routes}

    Zoom levels:
    - MINIMAL: summary counts
    - SUMMARY: names + field names + boundary kinds + routes
    - DETAILED: + parse op details, fold definitions
    - FULL: full AST repr
    """
    file_type = data.get("type", "unknown")

    if file_type == "loop":
        return _render_loop(data, zoom, width)
    elif file_type == "vertex":
        return _render_vertex(data, zoom, width)
    else:
        return Block.text(f"Unknown type: {file_type}", Style(dim=True), width=width)


def _render_loop(data: dict, zoom: Zoom, width: int) -> Block:
    """Render compiled .loop source."""
    name = data.get("name", "?")
    parse_ops = data.get("parse", [])

    if zoom == Zoom.MINIMAL:
        parts = [f'Source "{name}"']
        if parse_ops:
            parts.append(f"{len(parse_ops)} parse ops")
        return Block.text(", ".join(parts), Style(), width=width)

    header_style = Style(bold=True)
    dim_style = Style(dim=True)
    rows: list[Block] = []

    rows.append(Block.text(f"Source: {name}", header_style, width=width))

    if zoom >= Zoom.SUMMARY:
        rows.append(Block.text(f"  command: {data.get('command', '?')}", Style(), width=width))
        rows.append(Block.text(f"  kind: {data.get('kind', '?')}", Style(), width=width))
        rows.append(Block.text(f"  observer: {data.get('observer', '?')}", Style(), width=width))
        every = data.get("every")
        rows.append(Block.text(
            f"  every: {every}s" if every else "  every: (once)",
            Style(), width=width,
        ))
        rows.append(Block.text(f"  format: {data.get('format', '?')}", Style(), width=width))

    if parse_ops:
        if zoom >= Zoom.SUMMARY:
            rows.append(Block.text(f"  parse: {len(parse_ops)} ops", Style(), width=width))
        if zoom >= Zoom.DETAILED:
            for i, op in enumerate(parse_ops):
                rows.append(Block.text(f"    {i+1}. {op}", dim_style, width=width))

    return join_vertical(*rows)


def _render_vertex(data: dict, zoom: Zoom, width: int) -> Block:
    """Render compiled .vertex specs."""
    name = data.get("name", "?")
    specs = data.get("specs", {})
    routes = data.get("routes", {})

    if zoom == Zoom.MINIMAL:
        parts = [f'Vertex "{name}": {len(specs)} loops']
        if routes:
            parts.append(f"{len(routes)} routes")
        return Block.text(", ".join(parts), Style(), width=width)

    header_style = Style(bold=True)
    dim_style = Style(dim=True)
    rows: list[Block] = []

    rows.append(Block.text(f"Vertex: {name}", header_style, width=width))
    if data.get("store"):
        rows.append(Block.text(f"  store: {data['store']}", Style(), width=width))
    if data.get("discover"):
        rows.append(Block.text(f"  discover: {data['discover']}", Style(), width=width))
    if data.get("emit"):
        rows.append(Block.text(f"  emit: {data['emit']}", Style(), width=width))

    if specs:
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text(f"Loops ({len(specs)}):", header_style, width=width))
        for spec_name, spec_data in specs.items():
            rows.append(Block.text("", Style(), width=width))
            rows.append(Block.text(f"  {spec_name}:", header_style, width=width))
            rows.append(Block.text(
                f"    state_fields: {spec_data['state_fields']}",
                Style(), width=width,
            ))
            rows.append(Block.text(
                f"    folds: {len(spec_data['folds'])}",
                Style(), width=width,
            ))
            if zoom >= Zoom.DETAILED:
                for fold in spec_data["folds"]:
                    rows.append(Block.text(f"      - {fold}", dim_style, width=width))
            if spec_data.get("boundary"):
                rows.append(Block.text(
                    f"    boundary: {spec_data['boundary']}",
                    Style(), width=width,
                ))

    if routes:
        rows.append(Block.text("", Style(), width=width))
        rows.append(Block.text("Routes:", header_style, width=width))
        for kind, loop in routes.items():
            rows.append(Block.text(f"  {kind} -> {loop}", Style(), width=width))

    return join_vertical(*rows)
