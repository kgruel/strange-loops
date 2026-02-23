"""Tests for the data_explorer component."""

import pytest

from fidelis.widgets import (
    DataExplorerState,
    DataNode,
    data_explorer,
    flatten,
)


class TestFlatten:
    """Tests for the flatten function."""

    def test_dict_root_produces_nodes(self):
        """Dict keys become top-level nodes."""
        data = {"a": 1, "b": 2, "c": 3}
        nodes = flatten(data)
        assert len(nodes) == 3
        assert [n.key for n in nodes] == ["a", "b", "c"]

    def test_expanded_children_visible(self):
        """Expanding a dict node reveals its children."""
        data = {"outer": {"inner1": 1, "inner2": 2}}
        nodes = flatten(data, expanded=frozenset({("outer",)}))
        keys = [n.key for n in nodes]
        assert "outer" in keys
        assert "inner1" in keys
        assert "inner2" in keys
        assert len(nodes) == 3  # outer + 2 children

    def test_collapsed_hides_children(self):
        """Collapsed node hides children."""
        data = {"outer": {"inner1": 1, "inner2": 2}}
        nodes = flatten(data, expanded=frozenset())
        assert len(nodes) == 1
        assert nodes[0].key == "outer"
        assert nodes[0].expandable is True
        assert nodes[0].expanded is False

    def test_large_collection_truncated(self):
        """Collection exceeding max_children gets sentinel node."""
        data = {f"k{i}": i for i in range(100)}
        nodes = flatten(data, max_children=10)
        assert len(nodes) == 11  # 10 items + sentinel
        assert "+90 more" in nodes[-1].key
        assert nodes[-1].expandable is False

    def test_list_indexing(self):
        """List items use integer index as key."""
        data = {"items": ["a", "b", "c"]}
        nodes = flatten(data, expanded=frozenset({("items",)}))
        # items node + 3 children
        assert len(nodes) == 4
        assert nodes[1].key == "0"
        assert nodes[2].key == "1"
        assert nodes[3].key == "2"

    def test_nested_depth(self):
        """Nested expansion sets correct depth."""
        data = {"a": {"b": {"c": 1}}}
        expanded = frozenset({("a",), ("a", "b")})
        nodes = flatten(data, expanded=expanded)
        assert nodes[0].depth == 0  # a
        assert nodes[1].depth == 1  # b
        assert nodes[2].depth == 2  # c

    def test_empty_dict(self):
        """Empty dict produces no nodes."""
        assert flatten({}) == []

    def test_empty_list(self):
        """Empty list produces no nodes."""
        assert flatten([]) == []

    def test_leaf_not_expandable(self):
        """Scalar values are not expandable."""
        data = {"name": "Alice", "age": 30}
        nodes = flatten(data)
        assert all(not n.expandable for n in nodes)


class TestDataExplorerState:
    """Tests for DataExplorerState."""

    def test_toggle_expand_adds_path(self):
        """Toggling a collapsed node adds it to expanded set."""
        data = {"a": {"b": 1}}
        state = DataExplorerState(data=data)
        state = state.toggle_expand()
        assert ("a",) in state.expanded

    def test_toggle_expand_removes_path(self):
        """Toggling an expanded node removes it from expanded set."""
        data = {"a": {"b": 1}}
        state = DataExplorerState(data=data, expanded=frozenset({("a",)}))
        state = state.toggle_expand()
        assert ("a",) not in state.expanded

    def test_move_down_clamps_at_end(self):
        """Move down past last item clamps to last."""
        data = {"a": 1, "b": 2}
        state = DataExplorerState(data=data).move_down()
        state = state.move_down()
        assert state.cursor_index == 1  # stays at last

    def test_move_up_clamps_at_zero(self):
        """Move up past first item clamps to 0."""
        data = {"a": 1}
        state = DataExplorerState(data=data)
        state = state.move_up()
        assert state.cursor_index == 0

    def test_move_down_increments(self):
        """Move down increments cursor."""
        data = {"a": 1, "b": 2, "c": 3}
        state = DataExplorerState(data=data)
        state = state.move_down()
        assert state.cursor_index == 1

    def test_home_goes_to_zero(self):
        """Home moves cursor to 0."""
        data = {"a": 1, "b": 2, "c": 3}
        state = DataExplorerState(data=data).end()
        state = state.home()
        assert state.cursor_index == 0

    def test_end_goes_to_last(self):
        """End moves cursor to last item."""
        data = {"a": 1, "b": 2, "c": 3}
        state = DataExplorerState(data=data).end()
        assert state.cursor_index == 2

    def test_toggle_leaf_is_noop(self):
        """Toggling a non-expandable node is a no-op."""
        data = {"a": 1}
        state = DataExplorerState(data=data)
        new_state = state.toggle_expand()
        assert new_state.expanded == state.expanded


class TestDataExplorerRender:
    """Tests for the data_explorer render function."""

    def test_output_fits_dimensions(self):
        """Rendered block fits within specified width and height."""
        data = {"a": 1, "b": {"c": 2}, "d": [1, 2, 3]}
        state = DataExplorerState(data=data).with_visible(10)
        block = data_explorer(state, width=40, height=10)
        assert block.width == 40
        assert block.height == 10

    def test_empty_data_shows_placeholder(self):
        """Empty data shows (empty) message."""
        state = DataExplorerState(data={})
        block = data_explorer(state, width=40, height=5)
        text = _block_to_text(block)
        assert "empty" in text

    def test_expand_indicator_shown(self):
        """Expandable nodes show > indicator."""
        data = {"nested": {"a": 1}}
        state = DataExplorerState(data=data)
        block = data_explorer(state, width=40, height=5)
        text = _block_to_text(block)
        assert ">" in text

    def test_expanded_indicator_shown(self):
        """Expanded nodes show v indicator."""
        data = {"nested": {"a": 1}}
        state = DataExplorerState(data=data, expanded=frozenset({("nested",)}))
        block = data_explorer(state, width=40, height=5)
        text = _block_to_text(block)
        assert "v " in text

    def test_leaf_values_shown(self):
        """Leaf nodes show key: value."""
        data = {"name": "Alice"}
        state = DataExplorerState(data=data)
        block = data_explorer(state, width=40, height=5)
        text = _block_to_text(block)
        assert "name" in text
        assert "Alice" in text


def _block_to_text(block) -> str:
    """Extract text content from a block for testing."""
    result = []
    for y in range(block.height):
        row = block.row(y)
        line = "".join(cell.char for cell in row)
        result.append(line)
    return "\n".join(result)
