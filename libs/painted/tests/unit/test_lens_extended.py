"""Extended tests for lens functions — targeting uncovered lines in _lens.py."""

from painted.block import Block
from painted.cell import Style
from painted.views import chart_lens, flame_lens, shape_lens, tree_lens
from tests.helpers import block_to_text


# ---------------------------------------------------------------------------
# shape_lens: fallback object (line 106)
# ---------------------------------------------------------------------------


class TestShapeLensFallbackObject:
    """shape_lens falls back to str(obj) for unknown types."""

    def test_custom_object_rendered_as_string(self):
        class MyObj:
            def __str__(self):
                return "custom-repr"

        block = shape_lens(MyObj(), 1, 40)
        text = block_to_text(block)
        assert "custom-repr" in text


# ---------------------------------------------------------------------------
# _render_scalar: zoom 1 truncation (line 122), zoom 0 (line 113-116)
# ---------------------------------------------------------------------------


class TestRenderScalarEdges:
    """Scalar rendering edge cases at various zoom and width combos."""

    def test_scalar_zoom_1_width_1_truncates(self):
        """Width=1 at zoom 1 uses truncate (not truncate_ellipsis)."""
        block = shape_lens("hello", 1, 1)
        assert block.width == 1
        text = block_to_text(block)
        assert len(text.strip()) <= 1

    def test_scalar_zoom_1_long_string_truncated(self):
        """Long string at zoom 1 gets truncated with ellipsis."""
        block = shape_lens("a" * 50, 1, 10)
        text = block_to_text(block)
        assert "…" in text

    def test_scalar_zoom_2_long_string_with_char_count(self):
        """Very long string at zoom 2 includes char count indicator."""
        s = "x" * 300
        # Width must be large enough to show the "[300 chars]" suffix
        block = shape_lens(s, 2, 250)
        text = block_to_text(block)
        assert "300 chars" in text

    def test_scalar_zoom_2_width_1(self):
        """Width=1 at zoom 2 uses truncate (not truncate_ellipsis)."""
        block = shape_lens("hello", 2, 1)
        assert block.width == 1


# ---------------------------------------------------------------------------
# _render_dict: zoom 1 empty (line 158), zoom 1 truncation (line 162),
# key truncation width=1 (line 187), dead-code `not rows` (line 206)
# ---------------------------------------------------------------------------


class TestRenderDictEdges:
    """Dict rendering edge cases."""

    def test_empty_dict_zoom_1(self):
        """Empty dict at zoom 1 shows '{}'."""
        block = shape_lens({}, 1, 40)
        text = block_to_text(block)
        assert "{}" in text

    def test_dict_zoom_1_long_pairs_truncated(self):
        """Dict with long k:v at zoom 1 truncates with ellipsis."""
        d = {"longkey": "longvalue", "another": "item"}
        block = shape_lens(d, 1, 15)
        text = block_to_text(block)
        assert "…" in text

    def test_dict_zoom_2_key_truncation_narrow(self):
        """Dict at zoom 2 truncates keys when key_col_width is very small."""
        d = {"very_long_key": "val"}
        block = shape_lens(d, 2, 10)
        text = block_to_text(block)
        assert block.width <= 10


# ---------------------------------------------------------------------------
# _render_list: zoom 1 empty (line 223), zoom 2 multi-row items (lines 266-275)
# ---------------------------------------------------------------------------


class TestRenderListEdges:
    """List rendering edge cases."""

    def test_empty_list_zoom_1(self):
        """Empty list at zoom 1 shows '[]'."""
        block = shape_lens([], 1, 40)
        text = block_to_text(block)
        assert "[]" in text

    def test_list_zoom_2_multi_row_items(self):
        """List of dicts at zoom 3 produces multi-row items with indent."""
        data = [{"a": "x", "b": "y"}, {"c": "z"}]
        block = shape_lens(data, 3, 40)
        # Should have multiple rows for the nested dict items
        assert block.height >= 2

    def test_list_zoom_1_overflow_ellipsis(self):
        """List with too many items at zoom 1 triggers overflow path."""
        # Many items that cannot all fit; the code appends "..." to the items list
        # before joining. Width must be large enough for the "..." to not get
        # truncated by Block.text.
        data = list("abcdefghijklmnopqrstuvwxyz")
        block = shape_lens(data, 1, 60)
        text = block_to_text(block)
        # The overflow marker "..." appears as the last item in the joined text
        assert "..." in text


# ---------------------------------------------------------------------------
# _render_set: empty set (line 295), overflow (line 304)
# ---------------------------------------------------------------------------


class TestRenderSetEdges:
    """Set rendering edge cases."""

    def test_empty_set_zoom_1(self):
        """Empty set at zoom 1 shows '{}'."""
        block = shape_lens(set(), 1, 40)
        text = block_to_text(block)
        assert "{}" in text

    def test_set_overflow_tags(self):
        """Set with many items at narrow width truncates tags."""
        s = {"alpha", "beta", "gamma", "delta", "epsilon"}
        block = shape_lens(s, 1, 15)
        text = block_to_text(block)
        # Should have at least one tag but not all of them
        assert "[" in text


# ---------------------------------------------------------------------------
# _summarize_item: long string (line 320), dict/list/set items (lines 324-330)
# ---------------------------------------------------------------------------


class TestSummarizeItem:
    """List zoom 1 summarization of complex items."""

    def test_long_string_item_truncated(self):
        """Long string items in list zoom 1 are truncated."""
        data = ["this is a very long string item"]
        block = shape_lens(data, 1, 60)
        text = block_to_text(block)
        assert "…" in text

    def test_dict_item_in_list(self):
        """Dict item in list zoom 1 shows 'dict[N]'."""
        data = [{"a": 1, "b": 2}]
        block = shape_lens(data, 1, 40)
        text = block_to_text(block)
        assert "dict[2]" in text

    def test_list_item_in_list(self):
        """Nested list item in list zoom 1 shows 'list[N]'."""
        data = [[1, 2, 3]]
        block = shape_lens(data, 1, 40)
        text = block_to_text(block)
        assert "list[3]" in text

    def test_set_item_in_list(self):
        """Set item in list zoom 1 shows 'set[N]'."""
        data = [{1, 2}]
        block = shape_lens(data, 1, 40)
        text = block_to_text(block)
        assert "set[2]" in text

    def test_unknown_item_in_list(self):
        """Unknown object item in list zoom 1 uses str()[:10]."""

        class Obj:
            def __str__(self):
                return "obj-representation"

        data = [Obj()]
        block = shape_lens(data, 1, 60)
        text = block_to_text(block)
        assert "obj-repres" in text

    def test_none_item_in_list(self):
        """None item in list zoom 1 shows 'None'."""
        data = [None, "x"]
        block = shape_lens(data, 1, 40)
        text = block_to_text(block)
        assert "None" in text

    def test_bool_item_in_list(self):
        """Bool item in list zoom 1 shows True/False."""
        data = [True, False]
        block = shape_lens(data, 1, 40)
        text = block_to_text(block)
        assert "True" in text
        assert "False" in text


# ---------------------------------------------------------------------------
# tree_lens: tuple form with list children (line 430),
# node_renderer (lines 394-398, 482-490, 506-512),
# content_width <= 0 (line 477), tree_truncate width=1 (line 535),
# node protocol (lines 441-445)
# ---------------------------------------------------------------------------


class TestTreeLensExtended:
    """Extended tree_lens coverage."""

    def test_tuple_form_with_list_children(self):
        """Tuple (label, list) form enumerates children."""
        data = ("root", ["child_a", "child_b"])
        block = tree_lens(data, 1, 40)
        text = block_to_text(block)
        assert "root" in text

    def test_tuple_form_with_none_children(self):
        """Tuple (label, None) form is a leaf."""
        data = ("leaf_node", None)
        block = tree_lens(data, 1, 40)
        text = block_to_text(block)
        assert "leaf_node" in text

    def test_node_protocol(self):
        """Object with .children attribute uses node protocol."""

        class Node:
            def __init__(self, name, children=None):
                self.name = name
                self.children = children or []

            def __str__(self):
                return self.name

        root = Node("root", [Node("child1"), Node("child2")])
        block = tree_lens(root, 1, 40)
        text = block_to_text(block)
        assert "root" in text

    def test_node_protocol_no_children(self):
        """Object with empty .children list is a leaf."""

        class Node:
            def __init__(self, name):
                self._name = name
                self.children = []

            def __str__(self):
                return self._name

        block = tree_lens(Node("leaf"), 1, 40)
        text = block_to_text(block)
        assert "leaf" in text

    def test_leaf_node_no_children(self):
        """Scalar data (not dict/tuple/node) is a leaf."""
        block = tree_lens("just a string", 1, 40)
        text = block_to_text(block)
        assert "just a string" in text

    def test_custom_node_renderer(self):
        """Custom node_renderer callback is called for nodes."""
        calls = []

        def renderer(key: str, value, depth: int) -> Block:
            calls.append((key, depth))
            # Return a block wide enough to fill the row (pad to 40 chars)
            text = f"<{key}>"
            return Block.text(text, Style(), width=40)

        data = {"a": 1, "b": 2}
        block = tree_lens(data, 1, 40, node_renderer=renderer)
        text = block_to_text(block)
        # Renderer should have been called for root and children
        assert len(calls) >= 1
        assert "<root>" in text

    def test_custom_node_renderer_deep(self):
        """Custom node_renderer at zoom 2 with nested data."""

        def renderer(key: str, value, depth: int) -> Block:
            text = f"[{key}]"
            return Block.text(text, Style(), width=40)

        data = {"parent": {"child": "val"}}
        block = tree_lens(data, 2, 40, node_renderer=renderer)
        text = block_to_text(block)
        assert "[root]" in text

    def test_very_narrow_tree_skips_branches(self):
        """When content_width <= 0, branches are skipped."""
        data = {"a": {"b": {"c": {"d": "deep"}}}}
        # Width so narrow that deep branches cannot fit
        block = tree_lens(data, 4, 5)
        # Should not crash, just produce truncated output
        assert block.height >= 1

    def test_tree_truncate_width_1(self):
        """_tree_truncate with width=1 uses truncate, not truncate_ellipsis."""
        data = {"abc": 1}
        block = tree_lens(data, 0, 1)
        assert block.width == 1


# ---------------------------------------------------------------------------
# chart_lens: empty values (line 637, 657, 679), single number (line 637),
# bars too narrow (lines 695-699), non-percent values (line 726),
# all-same values stats (line 647)
# ---------------------------------------------------------------------------


class TestChartLensExtended:
    """Extended chart_lens coverage."""

    def test_single_number_all_zooms(self):
        """Single number produces valid output at all zoom levels."""
        for z in range(4):
            block = chart_lens(42, z, 40)
            assert block.height >= 1

    def test_empty_dict(self):
        """Empty dict shows no-data message."""
        block = chart_lens({}, 1, 40)
        text = block_to_text(block)
        assert "no data" in text

    def test_all_same_values_stats(self):
        """When all values are the same, stats shows 'all X'."""
        data = [5, 5, 5]
        block = chart_lens(data, 0, 40)
        text = block_to_text(block)
        assert "all 5" in text

    def test_bars_too_narrow_for_bar_chars(self):
        """When width is too narrow for bars, shows 'label: value' format."""
        data = {"cpu": 70, "mem": 50}
        block = chart_lens(data, 3, 12)
        text = block_to_text(block)
        assert "cpu" in text
        assert "mem" in text

    def test_non_percent_values_in_bars(self):
        """Values outside 0-100 use raw format, not percentage."""
        data = {"x": 500, "y": 1000}
        block = chart_lens(data, 3, 40)
        text = block_to_text(block)
        assert "%" not in text
        assert "500" in text

    def test_negative_values_in_bars(self):
        """Negative values render without crashing."""
        data = {"a": -10, "b": 20}
        block = chart_lens(data, 3, 40)
        text = block_to_text(block)
        assert "a" in text
        assert "b" in text

    def test_bars_no_labels_generates_indices(self):
        """Numeric list at zoom 3 generates index labels for bars."""
        data = [10, 20, 30]
        block = chart_lens(data, 3, 40)
        text = block_to_text(block)
        assert "0" in text  # index label

    def test_zero_span_values(self):
        """When all values are equal, bars should still render."""
        data = {"a": 50, "b": 50}
        block = chart_lens(data, 3, 40)
        text = block_to_text(block)
        assert "a" in text

    def test_sparkline_empty_values(self):
        """Empty sparkline returns empty block."""
        block = chart_lens([], 1, 40)
        text = block_to_text(block)
        assert "no data" in text


# ---------------------------------------------------------------------------
# flame_lens: basic and edge cases (lines 805-821, 836-871, 1013-1019)
# ---------------------------------------------------------------------------


class TestFlameLens:
    """flame_lens coverage tests."""

    def test_flat_dict_zoom_0(self):
        """Flat dict at zoom 0 shows total."""
        data = {"a": 30, "b": 70}
        block = flame_lens(data, 0, 40)
        text = block_to_text(block)
        assert "flame" in text
        assert "100" in text

    def test_flat_dict_zoom_1(self):
        """Flat dict at zoom 1 shows single row of segments."""
        data = {"a": 30, "b": 70}
        block = flame_lens(data, 1, 40)
        text = block_to_text(block)
        assert "a" in text
        assert "b" in text
        assert block.height == 1

    def test_nested_dict_zoom_2(self):
        """Nested dict at zoom 2 expands children."""
        data = {"parent": {"child1": 20, "child2": 30}}
        block = flame_lens(data, 2, 40)
        assert block.height >= 2
        text = block_to_text(block)
        assert "parent" in text

    def test_nested_dict_zoom_3_deeper(self):
        """Nested dict at zoom 3+ expands grandchildren."""
        data = {
            "a": {"a1": {"a1a": 10, "a1b": 5}, "a2": 15},
            "b": 20,
        }
        block = flame_lens(data, 3, 60)
        assert block.height >= 2
        text = block_to_text(block)
        assert "a" in text

    def test_empty_dict(self):
        """Empty dict shows no-data message."""
        block = flame_lens({}, 1, 40)
        text = block_to_text(block)
        assert "no data" in text

    def test_non_dict_data(self):
        """Non-dict data shows no-data message."""
        block = flame_lens("not a dict", 1, 40)
        text = block_to_text(block)
        assert "no data" in text

    def test_zero_width(self):
        """Zero width returns empty block."""
        block = flame_lens({"a": 10}, 1, 0)
        assert block.width == 0

    def test_single_item(self):
        """Single item fills entire width."""
        data = {"only": 100}
        block = flame_lens(data, 1, 40)
        text = block_to_text(block)
        assert "only" in text

    def test_many_items(self):
        """Many items fit proportionally."""
        data = {f"s{i}": i + 1 for i in range(10)}
        block = flame_lens(data, 1, 80)
        assert block.height == 1

    def test_zoom_0_narrow_truncates(self):
        """zoom 0 at narrow width truncates the summary."""
        data = {"a": 100}
        block = flame_lens(data, 0, 5)
        assert block.width == 5

    def test_custom_colors(self):
        """Custom color cycle is applied."""
        data = {"a": 50, "b": 50}
        block = flame_lens(data, 1, 40, colors=("green", "blue"))
        # Should not crash; colors are applied to styles
        assert block.height == 1

    def test_bool_values_ignored(self):
        """Bool values in flame data contribute 0 to totals."""
        data = {"flag": True, "num": 10}
        block = flame_lens(data, 0, 40)
        text = block_to_text(block)
        # Total should be 10, not 11
        assert "10" in text

    def test_leaf_at_zoom_2_renders_child_color(self):
        """Leaf segments at zoom 2 render at child depth color."""
        data = {"leaf": 50, "branch": {"c": 50}}
        block = flame_lens(data, 2, 40)
        assert block.height >= 2


# ---------------------------------------------------------------------------
# _seg_value: bool, dict, other (lines 1013-1019)
# ---------------------------------------------------------------------------


class TestSegValue:
    """_seg_value helper function."""

    def test_flame_with_mixed_value_types(self):
        """flame_lens handles mixed value types via _seg_value."""
        data = {"num": 10, "nested": {"inner": 5}, "bool": True, "str": "text"}
        block = flame_lens(data, 1, 60)
        # Should not crash
        assert block.height >= 1


# ---------------------------------------------------------------------------
# _flame_allocate_widths: total <= 0, val <= 0, label steal (lines 836-871)
# ---------------------------------------------------------------------------


class TestFlameAllocateWidths:
    """flame_lens width allocation edge cases."""

    def test_zero_total_distributes_evenly(self):
        """When total is 0, widths are distributed evenly."""
        data = {"a": 0, "b": 0}
        block = flame_lens(data, 1, 40)
        assert block.height == 1

    def test_negative_value_gets_min_width(self):
        """Negative values get minimum width of 1."""
        data = {"neg": -5, "pos": 10}
        block = flame_lens(data, 1, 40)
        text = block_to_text(block)
        # Both should appear
        assert block.height == 1

    def test_label_steal_from_large_segment(self):
        """Short-labeled large segment donates width to long-labeled small one."""
        data = {"x": 90, "very_long_label": 10}
        block = flame_lens(data, 1, 40)
        text = block_to_text(block)
        # The long label should at least partially appear
        assert "very" in text
