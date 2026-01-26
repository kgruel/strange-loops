"""Lens: stateless content-to-Block transformation at zoom levels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from .block import Block
from .cell import Style
from .compose import join_vertical, join_horizontal
from .span import Line, Span

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Lens(Generic[T]):
    """Bundles a render function with zoom metadata.

    render: (content, zoom, width) -> Block
    max_zoom: highest meaningful zoom level (default 2)
    """

    render: Callable[[T, int, int], Block]
    max_zoom: int = 2


def shape_lens(content: Any, zoom: int, width: int) -> Block:
    """Convention-based rendering of Python data structures at zoom levels.

    Zoom levels:
    - 0: minimal (type/count)
    - 1: summary (keys or truncated values)
    - 2: full (complete representation)

    For nested structures, each nesting level reduces effective zoom by 1.
    """
    if width <= 0:
        return Block.empty(0, 1)

    if content is None:
        return _render_scalar(content, zoom, width)

    if isinstance(content, bool):
        # Check bool before int since bool is subclass of int
        return _render_scalar(content, zoom, width)

    if isinstance(content, (str, int, float)):
        return _render_scalar(content, zoom, width)

    if isinstance(content, dict):
        return _render_dict(content, zoom, width)

    if isinstance(content, list):
        return _render_list(content, zoom, width)

    if isinstance(content, set):
        return _render_set(content, zoom, width)

    # Fallback: treat as string representation
    return _render_scalar(str(content), zoom, width)


def _render_scalar(value: Any, zoom: int, width: int) -> Block:
    """Render scalar values (str, int, float, bool, None) at zoom levels."""
    style = Style()

    if zoom <= 0:
        # Type name only
        type_name = type(value).__name__
        return Block.text(type_name, style, width=width)

    if zoom == 1:
        # Truncated value
        text = _format_value(value)
        if len(text) > width:
            if width > 1:
                text = text[: width - 1] + "\u2026"  # ellipsis
            else:
                text = text[:width]
        return Block.text(text, style, width=width)

    # zoom >= 2: full value
    text = _format_value(value)
    if len(text) > width:
        if width > 1:
            text = text[: width - 1] + "\u2026"
        else:
            text = text[:width]
    return Block.text(text, style, width=width)


def _format_value(value: Any) -> str:
    """Format a value for display."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value
    return str(value)


def _render_dict(d: dict, zoom: int, width: int) -> Block:
    """Render dict at zoom levels."""
    style = Style()

    if zoom <= 0:
        # Count only
        text = f"dict[{len(d)}]"
        return Block.text(text, style, width=width)

    if zoom == 1:
        # Keys only, comma-separated
        if not d:
            text = "{}"
        else:
            keys = ", ".join(str(k) for k in d.keys())
            if len(keys) > width:
                if width > 1:
                    keys = keys[: width - 1] + "\u2026"
                else:
                    keys = keys[:width]
            text = keys
        return Block.text(text, style, width=width)

    # zoom >= 2: key-value table
    if not d:
        return Block.text("{}", style, width=width)

    rows: list[Block] = []
    key_style = Style(bold=True)
    val_style = Style()

    # Calculate key column width (max key length + 2 for ": ")
    max_key_len = max((len(str(k)) for k in d.keys()), default=0)
    key_col_width = min(max_key_len + 2, width // 2)
    val_col_width = max(1, width - key_col_width)

    for key, value in d.items():
        key_text = str(key) + ":"
        if len(key_text) > key_col_width:
            key_text = key_text[: key_col_width - 1] + "\u2026" if key_col_width > 1 else key_text[:key_col_width]
        key_block = Block.text(key_text.ljust(key_col_width), key_style)

        # Render value recursively with reduced zoom
        nested_zoom = max(0, zoom - 1)
        val_block = shape_lens(value, nested_zoom, val_col_width)

        row = join_horizontal(key_block, val_block)
        rows.append(row)

    if not rows:
        return Block.text("{}", style, width=width)

    return join_vertical(*rows)


def _render_list(lst: list, zoom: int, width: int) -> Block:
    """Render list at zoom levels."""
    style = Style()

    if zoom <= 0:
        # Count only
        text = f"list[{len(lst)}]"
        return Block.text(text, style, width=width)

    if zoom == 1:
        # First N items inline, comma-separated
        if not lst:
            text = "[]"
        else:
            items: list[str] = []
            total_len = 0
            for item in lst:
                item_str = _summarize_item(item)
                # Check if adding this item would exceed width
                sep_len = 2 if items else 0  # ", "
                if total_len + sep_len + len(item_str) > width - 3:  # reserve for "..."
                    items.append("...")
                    break
                items.append(item_str)
                total_len += sep_len + len(item_str)
            text = ", ".join(items)
        return Block.text(text, style, width=width)

    # zoom >= 2: vertical list
    if not lst:
        return Block.text("[]", style, width=width)

    rows: list[Block] = []
    prefix_width = 2  # "- "
    item_width = max(1, width - prefix_width)

    for item in lst:
        # Render item recursively with reduced zoom
        nested_zoom = max(0, zoom - 1)
        item_block = shape_lens(item, nested_zoom, item_width)

        # Prefix with "- "
        prefix_block = Block.text("- ", Style(dim=True))

        # Join prefix with first row of item, keep remaining rows aligned
        if item_block.height == 1:
            row = join_horizontal(prefix_block, item_block)
            rows.append(row)
        else:
            # Multi-row item: prefix first row, indent remaining
            from .cell import Cell

            first_row_cells = [Cell("-", Style(dim=True)), Cell(" ", Style())]
            first_row_cells.extend(item_block.row(0))
            rows.append(Block([first_row_cells], len(first_row_cells)))

            for row_idx in range(1, item_block.height):
                indent_cells = [Cell(" ", Style()), Cell(" ", Style())]
                indent_cells.extend(item_block.row(row_idx))
                rows.append(Block([indent_cells], len(indent_cells)))

    return join_vertical(*rows)


def _render_set(s: set, zoom: int, width: int) -> Block:
    """Render set at zoom levels."""
    style = Style()

    if zoom <= 0:
        # Count only
        text = f"set[{len(s)}]"
        return Block.text(text, style, width=width)

    # zoom >= 1: inline tags [a] [b] [c]
    if not s:
        return Block.text("{}", style, width=width)

    tag_style = Style()
    tags: list[str] = []
    total_len = 0

    for item in sorted(s, key=str):
        tag = f"[{item}]"
        sep_len = 1 if tags else 0  # space separator
        if total_len + sep_len + len(tag) > width:
            break
        tags.append(tag)
        total_len += sep_len + len(tag)

    text = " ".join(tags)
    return Block.text(text, style, width=width)


def _summarize_item(item: Any) -> str:
    """Create a short summary string for a list item."""
    if item is None:
        return "None"
    if isinstance(item, bool):
        return str(item)
    if isinstance(item, str):
        if len(item) > 10:
            return item[:9] + "\u2026"
        return item
    if isinstance(item, (int, float)):
        return str(item)
    if isinstance(item, dict):
        return f"dict[{len(item)}]"
    if isinstance(item, list):
        return f"list[{len(item)}]"
    if isinstance(item, set):
        return f"set[{len(item)}]"
    return str(item)[:10]


# Default lens for shape-based rendering
SHAPE_LENS: Lens[Any] = Lens(render=shape_lens, max_zoom=2)
