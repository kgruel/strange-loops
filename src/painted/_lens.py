"""Lens functions: stateless content-to-Block transformation at zoom levels.

Three built-in strategies:
  shape_lens  — auto-dispatches by data shape (generic Python values)
  tree_lens   — hierarchical data with branch characters
  chart_lens  — numeric data as sparklines/bars

All share the same signature: (data, zoom, width) -> Block.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence, TYPE_CHECKING

from .block import Block
from .cell import Style
from .compose import join_vertical, join_horizontal
from .span import Line, Span
from ._text_width import display_width, truncate, truncate_ellipsis
from ._sparkline_core import sparkline_text

if TYPE_CHECKING:
    from .icon_set import IconSet

# Sampling limits for large data at zoom >= 2
_MAX_DICT_ITEMS = 20
_MAX_LIST_ITEMS = 20
_MAX_STR_DISPLAY = 200

# Type alias for node renderer callback
NodeRenderer = Callable[[str, Any, int], Block]


def _is_numeric_sequence(data: Any) -> bool:
    """Check if data is a non-empty list/tuple of all numbers."""
    if not isinstance(data, (list, tuple)) or not data:
        return False
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in data)


def _is_labeled_numeric(data: Any) -> bool:
    """Check if data is a non-empty dict with all numeric values."""
    if not isinstance(data, dict) or not data:
        return False
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in data.values())


def _is_hierarchical(data: Any) -> bool:
    """Check if data is a dict containing nested dict/list values."""
    if not isinstance(data, dict) or not data:
        return False
    return any(isinstance(v, (dict, list)) and v for v in data.values())


def shape_lens(content: Any, zoom: int, width: int) -> Block:
    """Auto-dispatching renderer: picks the best strategy based on data shape.

    Dispatch rules:
    - Numeric sequences (list/tuple of numbers) → chart_lens
    - Labeled numeric dicts (all values are numbers) → chart_lens
    - Hierarchical dicts (nested dict/list values) → tree_lens
    - Everything else → built-in shape rendering

    Zoom levels (for built-in rendering):
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

    # Auto-dispatch: numeric data → chart
    if _is_numeric_sequence(content):
        return chart_lens(content, zoom, width)

    if _is_labeled_numeric(content):
        return chart_lens(content, zoom, width)

    # Auto-dispatch: hierarchical data → tree
    if _is_hierarchical(content):
        return tree_lens(content, zoom, width)

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
        if display_width(text) > width:
            text = truncate_ellipsis(text, width) if width > 1 else truncate(text, width)
        return Block.text(text, style, width=width)

    # zoom >= 2: full value (with length indicator for long strings)
    text = _format_value(value)
    if isinstance(value, str) and display_width(text) > _MAX_STR_DISPLAY:
        original_chars = len(value)
        text = truncate(text, _MAX_STR_DISPLAY) + f"... [{original_chars} chars]"
    if display_width(text) > width:
        text = truncate_ellipsis(text, width) if width > 1 else truncate(text, width)
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
            if display_width(keys) > width:
                keys = truncate_ellipsis(keys, width) if width > 1 else truncate(keys, width)
            text = keys
        return Block.text(text, style, width=width)

    # zoom >= 2: key-value table
    if not d:
        return Block.text("{}", style, width=width)

    rows: list[Block] = []
    key_style = Style(bold=True)
    val_style = Style()

    # Sample items if too many
    items = list(d.items())
    truncated = len(items) - _MAX_DICT_ITEMS if len(items) > _MAX_DICT_ITEMS else 0
    if truncated:
        items = items[:_MAX_DICT_ITEMS]

    # Calculate key column width (max key length + 2 for ": ")
    max_key_len = max((display_width(str(k)) for k, _ in items), default=0)
    key_col_width = min(max_key_len + 2, width // 2)
    val_col_width = max(1, width - key_col_width)

    for key, value in items:
        key_text = str(key) + ":"
        if display_width(key_text) > key_col_width:
            key_text = truncate_ellipsis(key_text, key_col_width) if key_col_width > 1 else truncate(key_text, key_col_width)
        key_block = Block.text(key_text, key_style, width=key_col_width)

        # Render value recursively with reduced zoom
        nested_zoom = max(0, zoom - 1)
        val_block = shape_lens(value, nested_zoom, val_col_width)

        row = join_horizontal(key_block, val_block)
        rows.append(row)

    if truncated:
        footer = Block.text(f"... +{truncated} more", Style(dim=True), width=width)
        rows.append(footer)

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
                item_w = display_width(item_str)
                if total_len + sep_len + item_w > width - 3:  # reserve for "..."
                    items.append("...")
                    break
                items.append(item_str)
                total_len += sep_len + item_w
            text = ", ".join(items)
        return Block.text(text, style, width=width)

    # zoom >= 2: vertical list
    if not lst:
        return Block.text("[]", style, width=width)

    # Sample items if too many
    truncated = len(lst) - _MAX_LIST_ITEMS if len(lst) > _MAX_LIST_ITEMS else 0
    visible = lst[:_MAX_LIST_ITEMS] if truncated else lst

    rows: list[Block] = []
    prefix_width = 2  # "- "
    item_width = max(1, width - prefix_width)

    for item in visible:
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

    if truncated:
        footer = Block.text(f"... +{truncated} more", Style(dim=True), width=width)
        rows.append(footer)

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
        if total_len + sep_len + display_width(tag) > width:
            break
        tags.append(tag)
        total_len += sep_len + display_width(tag)

    text = " ".join(tags)
    return Block.text(text, style, width=width)


def _summarize_item(item: Any) -> str:
    """Create a short summary string for a list item."""
    if item is None:
        return "None"
    if isinstance(item, bool):
        return str(item)
    if isinstance(item, str):
        if display_width(item) > 10:
            return truncate_ellipsis(item, 10) if 10 > 1 else truncate(item, 10)
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




# ---------------------------------------------------------------------------
# Tree Lens — hierarchical data with branch characters
# ---------------------------------------------------------------------------


def _get_tree_icons(icons: "IconSet | None") -> tuple[str, str, str, str]:
    """Get tree branch characters from icons or ambient defaults."""
    from .icon_set import current_icons

    ic = icons or current_icons()
    return ic.tree_branch, ic.tree_last, ic.tree_indent, ic.tree_space


def tree_lens(
    data: Any,
    zoom: int,
    width: int,
    *,
    node_renderer: NodeRenderer | None = None,
    icons: "IconSet | None" = None,
) -> Block:
    """Render hierarchical data as an indented tree with branch characters.

    Supports:
    - Nested dicts: keys as nodes, values as children
    - Tuples (label, children): explicit tree structure
    - Objects with .children attribute: node protocol

    Zoom levels:
    - 0: Root label + child count
    - 1: Root + immediate children (single line each)
    - 2+: Full tree, depth expands with zoom

    Args:
        data: Tree data in supported format.
        zoom: Zoom level (0-4).
        width: Available width in characters.
        node_renderer: Optional (key, value, depth) -> Block for custom node formatting.
            Branch characters are added automatically; return content only.
        icons: Optional IconSet override (uses ambient if None).

    Returns:
        Block with rendered tree.
    """
    if width <= 0:
        return Block.empty(0, 1)

    label, children = _tree_extract(data)
    tree_branch, tree_last, tree_indent, tree_space = _get_tree_icons(icons)

    if zoom <= 0:
        # Root label + count only
        count = len(children) if children else 0
        text = f"{label} [{count}]" if count else label
        return _tree_truncate(text, width)

    # Build tree rows
    rows: list[Block] = []

    # Root node
    if node_renderer is not None:
        root_block = node_renderer(label, data, 0)
        # Truncate if needed
        if root_block.width > width:
            root_block = Block.text(_truncate_ellipsis(label, width), Style(), width=width)
        rows.append(root_block)
    else:
        rows.append(_tree_truncate(label, width))

    if children:
        _tree_render_children_themed(
            children,
            zoom - 1,
            width,
            "",
            rows,
            1,  # depth
            tree_branch,
            tree_last,
            tree_indent,
            tree_space,
            node_renderer,
        )

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


def _tree_render_children_themed(
    children: list[tuple[str, Any]],
    remaining_zoom: int,
    width: int,
    prefix: str,
    rows: list[Block],
    depth: int,
    tree_branch: str,
    tree_last: str,
    tree_indent: str,
    tree_space: str,
    node_renderer: NodeRenderer | None,
) -> None:
    """Recursively render children with themed branch characters."""
    for i, (key, value) in enumerate(children):
        is_last = i == len(children) - 1
        branch = tree_last if is_last else tree_branch
        continuation = tree_space if is_last else tree_indent

        _, grandchildren = _tree_extract(value)

        # Calculate available width for content
        branch_prefix = prefix + branch
        content_width = width - display_width(branch_prefix)

        if content_width <= 0:
            continue

        if remaining_zoom <= 0 or grandchildren is None:
            # Leaf or zoom exhausted
            if node_renderer is not None:
                content_block = node_renderer(key, value, depth)
                # Prefix with branch chars
                row_cells = list(Block.text(branch_prefix, Style(), width=display_width(branch_prefix)).row(0))
                # Add content (truncated if needed)
                for cell in content_block.row(0)[:content_width]:
                    row_cells.append(cell)
                rows.append(Block([row_cells], width))
            else:
                # Default formatting
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
            if node_renderer is not None:
                content_block = node_renderer(key, value, depth)
                row_cells = list(Block.text(branch_prefix, Style(), width=display_width(branch_prefix)).row(0))
                for cell in content_block.row(0)[:content_width]:
                    row_cells.append(cell)
                rows.append(Block([row_cells], width))
            else:
                row_text = branch_prefix + _truncate_ellipsis(key, content_width)
                rows.append(Block.text(row_text, Style(), width=width))

            _tree_render_children_themed(
                grandchildren,
                remaining_zoom - 1,
                width,
                prefix + continuation,
                rows,
                depth + 1,
                tree_branch,
                tree_last,
                tree_indent,
                tree_space,
                node_renderer,
            )


def _tree_truncate(text: str, width: int) -> Block:
    """Create a single-row block, truncating if needed."""
    if display_width(text) > width:
        text = truncate_ellipsis(text, width) if width > 1 else truncate(text, width)
    return Block.text(text, Style(), width=width)


def _truncate_ellipsis(text: str, width: int) -> str:
    """Truncate text with ellipsis if it exceeds width."""
    return truncate_ellipsis(text, width) if width > 1 else truncate(text, width)




# ---------------------------------------------------------------------------
# Chart Lens — text-based visualizations for numeric data
# ---------------------------------------------------------------------------


def _get_chart_icons(icons: "IconSet | None") -> tuple[str | tuple[str, ...], str, str]:
    """Get chart characters from icons or ambient defaults."""
    from .icon_set import current_icons

    ic = icons or current_icons()
    return ic.sparkline, ic.bar_fill, ic.bar_empty


def chart_lens(
    data: Any,
    zoom: int,
    width: int,
    *,
    icons: "IconSet | None" = None,
) -> Block:
    """Render numeric data as text-based charts.

    Supports:
    - List of numbers: sequence chart (sparkline or bars)
    - Dict {label: number}: labeled bar chart
    - Single number: inline bar (requires max_value hint or uses 100)

    Zoom levels:
    - 0: Summary stats (count, range)
    - 1: Inline sparkline
    - 2: Vertical bars with labels

    Args:
        data: Numeric data in supported format.
        zoom: Zoom level (0-2).
        width: Available width in characters.
        icons: Optional IconSet override (uses ambient if None).

    Returns:
        Block with rendered chart.
    """
    if width <= 0:
        return Block.empty(0, 1)

    values, labels = _chart_extract(data)
    spark_chars, bar_filled, bar_empty = _get_chart_icons(icons)

    if not values:
        return Block.text("(no data)", Style(), width=width)

    if zoom <= 0:
        # Stats only
        return _chart_stats(values, width)

    if zoom == 1:
        # Sparkline
        return _chart_sparkline_themed(values, width, spark_chars)

    # zoom >= 2: labeled bars
    return _chart_bars_themed(values, labels, width, bar_filled, bar_empty)


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


def _chart_sparkline_themed(values: list[float], width: int, spark_chars: Sequence[str]) -> Block:
    """Render an inline sparkline with themed characters."""
    if not values:
        return Block.empty(width, 1)

    text = sparkline_text(
        values,
        width,
        chars=spark_chars,
        sampling="uniform",
        pad_left=False,
        pad_char=" ",
    )
    return Block.text(text, Style(), width=width)


def _chart_bars_themed(
    values: list[float],
    labels: list[str] | None,
    width: int,
    bar_filled: str,
    bar_empty: str,
) -> Block:
    """Render horizontal bars with themed characters."""
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
        bar = bar_filled * filled_count + bar_empty * (bar_width - filled_count)

        # Value suffix
        if is_percent:
            val_text = f"{val:3.0f}%".rjust(value_col)
        else:
            val_text = f"{val:.4g}".rjust(value_col)

        row_text = lbl_text + bar + val_text
        rows.append(Block.text(row_text[:width], Style(), width=width))

    return join_vertical(*rows)


