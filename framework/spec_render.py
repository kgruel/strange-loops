"""Convention-based renderer for spec-driven projections.

Maps projection state shapes to render components:
  - dict → table (keys as rows, nested fields as columns)
  - list → scrolling list (most recent at bottom)
  - set  → inline tags
  - scalar → labeled value

The primary view is the first dict or list field. Other fields
render as compact header/footer context.
"""

from __future__ import annotations

from typing import Any

from render.block import Block
from render.cell import Style
from render.span import Line, Span
from render.components.table import Column, TableState, table
from render.components.list_view import ListState, list_view
from render.compose import join_vertical

from .spec import ProjectionSpec, FieldSpec


def render_projection(
    spec: ProjectionSpec,
    state: dict[str, Any],
    width: int,
    height: int,
    *,
    table_state: TableState | None = None,
    list_state: ListState | None = None,
) -> Block:
    """Render a projection's state using convention-based component mapping.

    Returns a Block sized to fit within (width, height).
    """
    # Find the primary field (first dict or list)
    primary: FieldSpec | None = None
    secondary: list[FieldSpec] = []

    for f in spec.state_fields:
        if primary is None and f.type in ("dict", "list"):
            primary = f
        else:
            secondary.append(f)

    if primary is None:
        # All scalars — render as labeled values
        return _render_scalars(spec.state_fields, state, width)

    # Render secondary fields as a compact header
    header_lines: list[Block] = []
    if secondary:
        header_block = _render_secondary(secondary, state, width)
        if header_block.height > 0:
            header_lines.append(header_block)

    header_height = sum(b.height for b in header_lines)
    primary_height = max(1, height - header_height)

    # Render primary field
    if primary.type == "dict":
        primary_block = _render_dict(
            state.get(primary.name, {}), width, primary_height, table_state
        )
    else:  # list
        primary_block = _render_list(
            state.get(primary.name, []), width, primary_height, list_state
        )

    parts = header_lines + [primary_block]
    if len(parts) == 1:
        return parts[0]
    return join_vertical(*parts)


def _render_dict(
    data: dict[str, Any],
    width: int,
    height: int,
    state: TableState | None,
) -> Block:
    """Render a dict as a table. Keys are rows, nested dict values become columns."""
    if not data:
        return Block.text("(empty)", Style(dim=True), width=width)

    # Infer columns from the first entry's keys
    first_value = next(iter(data.values()))
    if isinstance(first_value, dict):
        col_names = [k for k in first_value.keys() if not k.startswith("_")]
    else:
        col_names = ["key", "value"]

    # Distribute column widths
    n_cols = len(col_names)
    sep_space = n_cols - 1  # 1 char per separator
    available = width - sep_space
    col_width = max(4, available // n_cols)

    columns = [
        Column(header=Line.plain(name), width=col_width)
        for name in col_names
    ]

    # Build rows
    rows: list[list[Line]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            row = [
                Line.plain(str(value.get(col, ""))[:col_width])
                for col in col_names
            ]
        else:
            row = [Line.plain(str(key)[:col_width]), Line.plain(str(value)[:col_width])]
        rows.append(row)

    # Create table state if not provided
    visible = max(1, height - 2)  # header + separator take 2 rows
    if state is None:
        state = TableState(row_count=len(rows))

    return table(state, columns, rows, visible)


def _render_list(
    data: list[Any],
    width: int,
    height: int,
    state: ListState | None,
) -> Block:
    """Render a list as a scrolling list view."""
    if not data:
        return Block.text("(no items)", Style(dim=True), width=width)

    # Convert items to Lines
    items: list[Line] = []
    for item in data:
        if isinstance(item, dict):
            # Format dict items as key fields
            parts = []
            for k, v in item.items():
                if k.startswith("_"):
                    continue
                parts.append(f"{v}")
            text = " | ".join(parts)
        else:
            text = str(item)
        items.append(Line.plain(text[:width]))

    # Auto-scroll to bottom (most recent)
    if state is None:
        last = max(0, len(items) - 1)
        state = ListState(
            selected=last,
            scroll_offset=max(0, len(items) - height),
            item_count=len(items),
        )

    return list_view(state, items, height)


def _render_secondary(
    fields: list[FieldSpec],
    state: dict[str, Any],
    width: int,
) -> Block:
    """Render secondary fields as a compact single-line summary."""
    parts: list[str] = []
    for f in fields:
        value = state.get(f.name)
        if value is None:
            continue
        if isinstance(value, set):
            parts.append(f"{f.name}: {', '.join(sorted(value))}")
        else:
            # Truncate long values
            s = str(value)
            if len(s) > 30:
                s = s[:27] + "..."
            parts.append(f"{f.name}: {s}")

    if not parts:
        return Block.text("", Style(), width=0)

    text = "  ".join(parts)
    return Block.text(text[:width], Style(dim=True), width=width)


def _render_scalars(
    fields: list[FieldSpec],
    state: dict[str, Any],
    width: int,
) -> Block:
    """Render all-scalar state as labeled values, one per line."""
    lines: list[Block] = []
    for f in fields:
        value = state.get(f.name, "")
        text = f"{f.name}: {value}"
        lines.append(Block.text(text[:width], Style(), width=width))
    if not lines:
        return Block.text("(empty)", Style(dim=True), width=width)
    return join_vertical(*lines)
