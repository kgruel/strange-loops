"""Data explorer: interactive tree navigation for nested data structures."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .._text_width import display_width, truncate
from ..block import Block
from ..cell import Style
from ..compose import join_vertical
from ..cursor import Cursor
from ..viewport import Viewport

_MAX_CHILDREN = 50


@dataclass(frozen=True, slots=True)
class DataNode:
    """Single visible node in the flattened tree."""

    key: str
    value: Any
    depth: int
    path: tuple[str, ...]
    expandable: bool
    expanded: bool


def flatten(
    data: Any,
    expanded: frozenset[tuple[str, ...]] = frozenset(),
    *,
    max_children: int = _MAX_CHILDREN,
    _path: tuple[str, ...] = (),
    _depth: int = 0,
) -> list[DataNode]:
    """Convert nested data + expansion state into a flat visible list.

    Large collections get a sentinel "... +N more" node.
    """
    nodes: list[DataNode] = []

    if isinstance(data, dict):
        items = list(data.items())
        truncated = len(items) - max_children if len(items) > max_children else 0
        if truncated:
            items = items[:max_children]

        for key, value in items:
            str_key = str(key)
            child_path = _path + (str_key,)
            expandable = isinstance(value, (dict, list)) and len(value) > 0
            is_expanded = child_path in expanded

            nodes.append(
                DataNode(
                    key=str_key,
                    value=value,
                    depth=_depth,
                    path=child_path,
                    expandable=expandable,
                    expanded=is_expanded,
                )
            )

            if is_expanded and expandable:
                nodes.extend(
                    flatten(
                        value,
                        expanded,
                        max_children=max_children,
                        _path=child_path,
                        _depth=_depth + 1,
                    )
                )

        if truncated:
            sentinel_path = _path + (f"__more_{truncated}__",)
            nodes.append(
                DataNode(
                    key=f"... +{truncated} more",
                    value=None,
                    depth=_depth,
                    path=sentinel_path,
                    expandable=False,
                    expanded=False,
                )
            )

    elif isinstance(data, list):
        items = list(enumerate(data))
        truncated = len(items) - max_children if len(items) > max_children else 0
        if truncated:
            items = items[:max_children]

        for idx, value in items:
            str_key = str(idx)
            child_path = _path + (str_key,)
            expandable = isinstance(value, (dict, list)) and len(value) > 0
            is_expanded = child_path in expanded

            nodes.append(
                DataNode(
                    key=str_key,
                    value=value,
                    depth=_depth,
                    path=child_path,
                    expandable=expandable,
                    expanded=is_expanded,
                )
            )

            if is_expanded and expandable:
                nodes.extend(
                    flatten(
                        value,
                        expanded,
                        max_children=max_children,
                        _path=child_path,
                        _depth=_depth + 1,
                    )
                )

        if truncated:
            sentinel_path = _path + (f"__more_{truncated}__",)
            nodes.append(
                DataNode(
                    key=f"... +{truncated} more",
                    value=None,
                    depth=_depth,
                    path=sentinel_path,
                    expandable=False,
                    expanded=False,
                )
            )

    return nodes


@dataclass(frozen=True, slots=True)
class DataExplorerState:
    """Immutable state for data explorer navigation."""

    data: Any
    cursor: Cursor = Cursor()
    expanded: frozenset[tuple[str, ...]] = frozenset()
    viewport: Viewport = Viewport()
    _nodes: tuple[DataNode, ...] | None = None

    @property
    def cursor_index(self) -> int:
        return self.cursor.index

    @property
    def nodes(self) -> tuple[DataNode, ...]:
        """Current visible nodes.

        Cached on the instance to avoid re-flattening on cursor/viewport-only updates.
        """
        if self._nodes is None:
            object.__setattr__(self, "_nodes", tuple(flatten(self.data, self.expanded)))
        nodes = self._nodes
        assert nodes is not None
        return nodes

    def toggle_expand(self) -> DataExplorerState:
        """Toggle expansion of the node at cursor."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        viewport = self.viewport.with_content(len(nodes))
        if not nodes:
            return replace(self, cursor=cursor, viewport=viewport)

        node = nodes[cursor.index]
        if not node.expandable:
            return replace(self, cursor=cursor, viewport=viewport)
        if node.expanded:
            new_expanded = self.expanded - {node.path}
        else:
            new_expanded = self.expanded | {node.path}

        # After expansion change, re-sync cursor + viewport to the new node list.
        new_state = replace(self, expanded=new_expanded, _nodes=None)
        new_nodes = new_state.nodes
        new_cursor = cursor.with_count(len(new_nodes))
        new_viewport = viewport.with_content(len(new_nodes)).scroll_into_view(new_cursor.index)
        return replace(new_state, cursor=new_cursor, viewport=new_viewport)

    def move_up(self) -> DataExplorerState:
        """Move cursor up by one."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        viewport = self.viewport.with_content(len(nodes))
        new_cursor = cursor.prev()
        new_vp = viewport.scroll_into_view(new_cursor.index)
        return replace(self, cursor=new_cursor, viewport=new_vp)

    def move_down(self) -> DataExplorerState:
        """Move cursor down by one."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        viewport = self.viewport.with_content(len(nodes))
        new_cursor = cursor.next()
        new_vp = viewport.scroll_into_view(new_cursor.index)
        return replace(self, cursor=new_cursor, viewport=new_vp)

    def page_up(self) -> DataExplorerState:
        """Move cursor up by one page."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        viewport = self.viewport.with_content(len(nodes))
        new_cursor = cursor.move(-viewport.visible)
        new_vp = viewport.scroll_into_view(new_cursor.index)
        return replace(self, cursor=new_cursor, viewport=new_vp)

    def page_down(self) -> DataExplorerState:
        """Move cursor down by one page."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        viewport = self.viewport.with_content(len(nodes))
        new_cursor = cursor.move(viewport.visible)
        new_vp = viewport.scroll_into_view(new_cursor.index)
        return replace(self, cursor=new_cursor, viewport=new_vp)

    def home(self) -> DataExplorerState:
        """Move cursor to first item."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        viewport = self.viewport.with_content(len(nodes))
        new_cursor = cursor.home()
        new_vp = viewport.scroll_into_view(new_cursor.index)
        return replace(self, cursor=new_cursor, viewport=new_vp)

    def end(self) -> DataExplorerState:
        """Move cursor to last item."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        viewport = self.viewport.with_content(len(nodes))
        new_cursor = cursor.end()
        new_vp = viewport.scroll_into_view(new_cursor.index)
        return replace(self, cursor=new_cursor, viewport=new_vp)

    def with_visible(self, height: int) -> DataExplorerState:
        """Update viewport visible height."""
        nodes = self.nodes
        cursor = self.cursor.with_count(len(nodes))
        new_vp = self.viewport.with_visible(height).with_content(len(nodes))
        return replace(self, cursor=cursor, viewport=new_vp)


def _format_leaf_value(value: Any, max_len: int) -> str:
    """Format a leaf value for inline display."""
    if max_len <= 0:
        return ""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        if display_width(value) > max_len:
            return truncate(value, max_len - 3) + "..." if max_len > 3 else truncate(value, max_len)
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    text = str(value)
    if display_width(text) > max_len:
        return truncate(text, max_len - 3) + "..." if max_len > 3 else truncate(text, max_len)
    return text


def data_explorer(
    state: DataExplorerState,
    width: int,
    height: int,
    *,
    cursor_style: Style = Style(reverse=True),
    key_style: Style = Style(bold=True),
    dim_style: Style = Style(dim=True),
) -> Block:
    """Render the data explorer as a Block.

    Shows an indented tree with expand indicators, inline value previews,
    and cursor highlight.
    """
    nodes = state.nodes
    if not nodes:
        return Block.text("(empty)", dim_style, width=width)

    # Apply viewport
    vp = state.viewport.with_visible(height).with_content(len(nodes))
    start = vp.offset
    end = min(start + height, len(nodes))

    rows: list[Block] = []
    for i in range(start, end):
        node = nodes[i]
        is_cursor = i == state.cursor_index

        # Build line: indent + indicator + key + value
        indent = "  " * node.depth
        if node.expandable:
            indicator = "v " if node.expanded else "> "
        else:
            indicator = "  "

        prefix = indent + indicator
        remaining = width - display_width(prefix)

        if remaining <= 0:
            line_text = truncate(prefix, width)
        elif node.expandable and not node.expanded:
            # Show key + summary count
            count = len(node.value) if isinstance(node.value, (dict, list)) else 0
            summary = f"{node.key} [{count}]"
            line_text = prefix + summary
        elif not node.expandable and node.value is not None:
            # Leaf: key: value
            val_text = _format_leaf_value(
                node.value, max(1, remaining - display_width(node.key) - 2)
            )
            leaf = f"{node.key}: {val_text}"
            line_text = prefix + leaf
        else:
            line_text = prefix + node.key

        row_style = cursor_style if is_cursor else Style()
        rows.append(Block.text(line_text, row_style, width=width))

    # Fill remaining height with empty rows
    while len(rows) < height:
        rows.append(Block.text(" " * width, Style(), width=width))

    return join_vertical(*rows)
