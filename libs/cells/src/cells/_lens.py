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
    default_zoom: suggested starting zoom level (default 1, caller decides)
    """

    render: Callable[[T, int, int], Block]
    max_zoom: int = 2
    default_zoom: int = 1


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


# ---------------------------------------------------------------------------
# Tree Lens — hierarchical data with branch characters
# ---------------------------------------------------------------------------

# Tree branch characters (box-drawing)
_TREE_BRANCH = "├─ "
_TREE_LAST = "└─ "
_TREE_PIPE = "│  "
_TREE_SPACE = "   "


def tree_lens(data: Any, zoom: int, width: int) -> Block:
    """Render hierarchical data as an indented tree with branch characters.

    Supports:
    - Nested dicts: keys as nodes, values as children
    - Tuples (label, children): explicit tree structure
    - Objects with .children attribute: node protocol

    Zoom levels:
    - 0: Root label + child count
    - 1: Root + immediate children (single line each)
    - 2+: Full tree, depth expands with zoom
    """
    if width <= 0:
        return Block.empty(0, 1)

    label, children = _tree_extract(data)

    if zoom <= 0:
        # Root label + count only
        count = len(children) if children else 0
        text = f"{label} [{count}]" if count else label
        return _tree_truncate(text, width)

    # Build tree rows
    rows: list[Block] = []
    rows.append(_tree_truncate(label, width))

    if children:
        _tree_render_children(children, zoom - 1, width, "", rows)

    return join_vertical(*rows) if rows else Block.empty(width, 1)


def _tree_extract(data: Any) -> tuple[str, list[tuple[str, Any]] | None]:
    """Extract (label, children) from various tree representations."""
    # Tuple form: (label, children)
    if isinstance(data, tuple) and len(data) == 2:
        label, children = data
        if isinstance(label, str) and (children is None or isinstance(children, (list, dict))):
            if children is None:
                return label, None
            if isinstance(children, dict):
                return label, [(str(k), v) for k, v in children.items()]
            return label, [(str(i), c) for i, c in enumerate(children)]

    # Dict: keys as children
    if isinstance(data, dict):
        if not data:
            return "{}", None
        # Root is implicit, children are key-value pairs
        return "root", [(str(k), v) for k, v in data.items()]

    # Node protocol: has .children attribute
    if hasattr(data, "children") and hasattr(data, "__str__"):
        children_attr = getattr(data, "children")
        if isinstance(children_attr, (list, tuple)):
            child_list = [(str(i), c) for i, c in enumerate(children_attr)]
            return str(data), child_list if child_list else None
        return str(data), None

    # Leaf node
    return str(data), None


def _tree_render_children(
    children: list[tuple[str, Any]],
    remaining_zoom: int,
    width: int,
    prefix: str,
    rows: list[Block],
) -> None:
    """Recursively render children with branch characters."""
    for i, (key, value) in enumerate(children):
        is_last = i == len(children) - 1
        branch = _TREE_LAST if is_last else _TREE_BRANCH
        continuation = _TREE_SPACE if is_last else _TREE_PIPE

        _, grandchildren = _tree_extract(value)

        # Calculate available width for content
        branch_prefix = prefix + branch
        content_width = width - len(branch_prefix)

        if content_width <= 0:
            continue

        if remaining_zoom <= 0 or grandchildren is None:
            # Leaf or zoom exhausted: show label (and count if has children)
            if grandchildren:
                text = f"{key} [{len(grandchildren)}]"
            else:
                # Show value for leaf nodes
                if value is None or isinstance(value, (str, int, float, bool)):
                    text = f"{key}: {value}"
                else:
                    text = key
            row_text = branch_prefix + _truncate_ellipsis(text, content_width)
            rows.append(Block.text(row_text, Style(), width=width))
        else:
            # Expand this branch
            row_text = branch_prefix + _truncate_ellipsis(key, content_width)
            rows.append(Block.text(row_text, Style(), width=width))
            _tree_render_children(
                grandchildren,
                remaining_zoom - 1,
                width,
                prefix + continuation,
                rows,
            )


def _tree_truncate(text: str, width: int) -> Block:
    """Create a single-row block, truncating if needed."""
    if len(text) > width:
        text = _truncate_ellipsis(text, width)
    return Block.text(text, Style(), width=width)


def _truncate_ellipsis(text: str, width: int) -> str:
    """Truncate text with ellipsis if it exceeds width."""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


# Default tree lens
TREE_LENS: Lens[Any] = Lens(render=tree_lens, max_zoom=4)


# ---------------------------------------------------------------------------
# Chart Lens — text-based visualizations for numeric data
# ---------------------------------------------------------------------------

# Sparkline characters (8 levels)
_SPARK_CHARS = "▁▂▃▄▅▆▇█"

# Bar characters
_BAR_FILLED = "█"
_BAR_EMPTY = "░"


def chart_lens(data: Any, zoom: int, width: int) -> Block:
    """Render numeric data as text-based charts.

    Supports:
    - List of numbers: sequence chart (sparkline or bars)
    - Dict {label: number}: labeled bar chart
    - Single number: inline bar (requires max_value hint or uses 100)

    Zoom levels:
    - 0: Summary stats (count, range)
    - 1: Inline sparkline
    - 2: Vertical bars with labels
    """
    if width <= 0:
        return Block.empty(0, 1)

    values, labels = _chart_extract(data)

    if not values:
        return Block.text("(no data)", Style(), width=width)

    if zoom <= 0:
        # Stats only
        return _chart_stats(values, width)

    if zoom == 1:
        # Sparkline
        return _chart_sparkline(values, width)

    # zoom >= 2: labeled bars
    return _chart_bars(values, labels, width)


def _chart_extract(data: Any) -> tuple[list[float], list[str] | None]:
    """Extract (values, labels) from various data formats."""
    # Dict with numeric values
    if isinstance(data, dict):
        labels = []
        values = []
        for k, v in data.items():
            if isinstance(v, (int, float)):
                labels.append(str(k))
                values.append(float(v))
        return values, labels if labels else None

    # List/tuple of numbers
    if isinstance(data, (list, tuple)):
        values = []
        for item in data:
            if isinstance(item, (int, float)):
                values.append(float(item))
        return values, None

    # Single number
    if isinstance(data, (int, float)):
        return [float(data)], None

    return [], None


def _chart_stats(values: list[float], width: int) -> Block:
    """Render summary statistics."""
    n = len(values)
    lo = min(values)
    hi = max(values)

    if lo == hi:
        text = f"[{n} values, all {lo:.4g}]"
    else:
        text = f"[{n} values, {lo:.4g}–{hi:.4g}]"

    return Block.text(_truncate_ellipsis(text, width), Style(), width=width)


def _chart_sparkline(values: list[float], width: int) -> Block:
    """Render an inline sparkline."""
    if not values:
        return Block.empty(width, 1)

    # Sample if more values than width
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values

    lo = min(sampled)
    hi = max(sampled)
    span = hi - lo if hi > lo else 1.0

    chars = []
    for v in sampled:
        # Map value to 0-7 index
        idx = int((v - lo) / span * 7)
        idx = max(0, min(7, idx))
        chars.append(_SPARK_CHARS[idx])

    text = "".join(chars)
    return Block.text(text, Style(), width=width)


def _chart_bars(values: list[float], labels: list[str] | None, width: int) -> Block:
    """Render horizontal bars with optional labels."""
    if not values:
        return Block.empty(width, 1)

    # Generate labels if not provided
    if labels is None:
        labels = [str(i) for i in range(len(values))]

    # Calculate column widths
    max_label = max(len(lbl) for lbl in labels)
    label_col = min(max_label + 1, width // 3)  # cap at 1/3 of width

    # Value suffix: " XXX%" or " XXX.X" — reserve 6 chars
    value_col = 6
    bar_width = width - label_col - value_col

    if bar_width < 2:
        # Not enough room for bars, just show values
        rows = []
        for lbl, val in zip(labels, values):
            text = f"{lbl}: {val:.4g}"
            rows.append(Block.text(_truncate_ellipsis(text, width), Style(), width=width))
        return join_vertical(*rows)

    lo = min(values)
    hi = max(values)
    span = hi - lo if hi > lo else 1.0

    # Determine if values look like percentages (0-100 range)
    is_percent = lo >= 0 and hi <= 100

    rows = []
    for lbl, val in zip(labels, values):
        # Label column (right-padded)
        lbl_text = _truncate_ellipsis(lbl, label_col - 1).ljust(label_col)

        # Bar
        if span > 0:
            ratio = (val - lo) / span
        else:
            ratio = 1.0
        filled_count = int(ratio * bar_width)
        filled_count = max(0, min(bar_width, filled_count))
        bar = _BAR_FILLED * filled_count + _BAR_EMPTY * (bar_width - filled_count)

        # Value suffix
        if is_percent:
            val_text = f"{val:3.0f}%".rjust(value_col)
        else:
            val_text = f"{val:.4g}".rjust(value_col)

        row_text = lbl_text + bar + val_text
        rows.append(Block.text(row_text[:width], Style(), width=width))

    return join_vertical(*rows)


# Default chart lens
CHART_LENS: Lens[Any] = Lens(render=chart_lens, max_zoom=2)
