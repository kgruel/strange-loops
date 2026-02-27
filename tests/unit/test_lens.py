"""Tests for lens functions (shape, tree, chart)."""

import pytest

from painted.views import (
    shape_lens,
    tree_lens,
    chart_lens,
)


class TestShapeLensDictZoom:
    """Tests for shape_lens with dict at each zoom level."""

    def test_dict_zoom_0_shows_count(self):
        """At zoom 0, dict shows 'dict[N]' count."""
        d = {"a": "x", "b": "y", "c": "z"}
        block = shape_lens(d, 0, 40)

        # Extract text from block
        text = _block_to_text(block)
        assert "dict[3]" in text

    def test_dict_zoom_1_shows_key_value_pairs(self):
        """At zoom 1, dict shows compact key: value pairs."""
        d = {"name": "Alice", "age": 30}
        block = shape_lens(d, 1, 40)

        text = _block_to_text(block)
        assert "name: Alice" in text
        assert "age: 30" in text

    def test_dict_zoom_2_shows_key_value_table(self):
        """At zoom 2, dict shows key-value pairs."""
        d = {"name": "Alice", "age": 30}
        block = shape_lens(d, 2, 40)

        text = _block_to_text(block)
        # Should have both keys and values
        assert "name" in text
        assert "Alice" in text
        assert "age" in text
        assert "30" in text

    def test_empty_dict_zoom_0(self):
        """Empty dict at zoom 0 shows 'dict[0]'."""
        block = shape_lens({}, 0, 40)
        text = _block_to_text(block)
        assert "dict[0]" in text

    def test_empty_dict_zoom_2(self):
        """Empty dict at zoom 2 shows '{}'."""
        block = shape_lens({}, 2, 40)
        text = _block_to_text(block)
        assert "{}" in text


class TestShapeLensListZoom:
    """Tests for shape_lens with list at each zoom level."""

    def test_list_zoom_0_shows_count(self):
        """At zoom 0, list shows 'list[N]' count."""
        lst = ["a", "b", "c", "d", "e"]
        block = shape_lens(lst, 0, 40)

        text = _block_to_text(block)
        assert "list[5]" in text

    def test_list_zoom_1_shows_inline_items(self):
        """At zoom 1, list shows comma-separated items inline."""
        lst = ["apple", "banana", "cherry"]
        block = shape_lens(lst, 1, 60)

        text = _block_to_text(block)
        assert "apple" in text
        assert "banana" in text
        # All items should be visible in sufficient width

    def test_list_zoom_2_shows_vertical_list(self):
        """At zoom 2, list shows items vertically with bullet prefix."""
        lst = ["first", "second"]
        block = shape_lens(lst, 2, 40)

        text = _block_to_text(block)
        # Should have multiple rows (one per item)
        assert block.height >= 2
        assert "first" in text
        assert "second" in text

    def test_empty_list_zoom_0(self):
        """Empty list at zoom 0 shows 'list[0]'."""
        block = shape_lens([], 0, 40)
        text = _block_to_text(block)
        assert "list[0]" in text

    def test_empty_list_zoom_2(self):
        """Empty list at zoom 2 shows '[]'."""
        block = shape_lens([], 2, 40)
        text = _block_to_text(block)
        assert "[]" in text


class TestShapeLensSetZoom:
    """Tests for shape_lens with set at each zoom level."""

    def test_set_zoom_0_shows_count(self):
        """At zoom 0, set shows 'set[N]' count."""
        s = {1, 2, 3}
        block = shape_lens(s, 0, 40)

        text = _block_to_text(block)
        assert "set[3]" in text

    def test_set_zoom_1_shows_tags(self):
        """At zoom 1, set shows items as inline tags."""
        s = {"a", "b"}
        block = shape_lens(s, 1, 40)

        text = _block_to_text(block)
        assert "[a]" in text
        assert "[b]" in text

    def test_empty_set_zoom_0(self):
        """Empty set at zoom 0 shows 'set[0]'."""
        block = shape_lens(set(), 0, 40)
        text = _block_to_text(block)
        assert "set[0]" in text


class TestShapeLensScalars:
    """Tests for shape_lens with scalar values."""

    def test_string_zoom_0_shows_type(self):
        """String at zoom 0 shows 'str'."""
        block = shape_lens("hello world", 0, 40)
        text = _block_to_text(block)
        assert "str" in text

    def test_string_zoom_1_shows_truncated(self):
        """String at zoom 1 shows truncated value."""
        block = shape_lens("hello", 1, 40)
        text = _block_to_text(block)
        assert "hello" in text

    def test_string_zoom_2_shows_full(self):
        """String at zoom 2 shows full value."""
        block = shape_lens("hello world", 2, 40)
        text = _block_to_text(block)
        assert "hello world" in text

    def test_int_zoom_0_shows_type(self):
        """Int at zoom 0 shows 'int'."""
        block = shape_lens(42, 0, 40)
        text = _block_to_text(block)
        assert "int" in text

    def test_int_zoom_2_shows_value(self):
        """Int at zoom 2 shows the value."""
        block = shape_lens(42, 2, 40)
        text = _block_to_text(block)
        assert "42" in text

    def test_float_zoom_0_shows_type(self):
        """Float at zoom 0 shows 'float'."""
        block = shape_lens(3.14, 0, 40)
        text = _block_to_text(block)
        assert "float" in text

    def test_bool_zoom_0_shows_type(self):
        """Bool at zoom 0 shows 'bool'."""
        block = shape_lens(True, 0, 40)
        text = _block_to_text(block)
        assert "bool" in text

    def test_bool_zoom_2_shows_value(self):
        """Bool at zoom 2 shows True/False."""
        block = shape_lens(True, 2, 40)
        text = _block_to_text(block)
        assert "True" in text

        block = shape_lens(False, 2, 40)
        text = _block_to_text(block)
        assert "False" in text

    def test_none_zoom_0_shows_type(self):
        """None at zoom 0 shows 'NoneType'."""
        block = shape_lens(None, 0, 40)
        text = _block_to_text(block)
        assert "NoneType" in text

    def test_none_zoom_2_shows_none(self):
        """None at zoom 2 shows 'None'."""
        block = shape_lens(None, 2, 40)
        text = _block_to_text(block)
        assert "None" in text


class TestShapeLensWidthConstraints:
    """Tests for shape_lens respecting width constraints."""

    def test_string_truncated_at_width(self):
        """Long string is truncated at width boundary."""
        block = shape_lens("hello world this is a long string", 2, 10)
        assert block.width == 10

    def test_dict_keys_truncated_at_width(self):
        """Dict keys at zoom 1 respect width."""
        d = {"very_long_key_name": 1, "another_long_key": 2}
        block = shape_lens(d, 1, 15)
        # Should not exceed width
        assert block.width <= 15

    def test_zero_width_returns_empty(self):
        """Zero width returns empty block."""
        block = shape_lens({"a": 1}, 2, 0)
        assert block.width == 0

    def test_narrow_width_still_works(self):
        """Very narrow width still produces valid block."""
        block = shape_lens("test", 2, 3)
        assert block.width == 3
        # Should have content (possibly truncated)
        text = _block_to_text(block)
        assert len(text.strip()) > 0


class TestShapeLensSampling:
    """Tests for shape_lens large collection and long string sampling."""

    def test_large_dict_truncated_at_zoom_2(self):
        """Large dict (100 keys) at zoom 2 shows '+80 more' footer."""
        d = {f"key_{i}": f"val_{i}" for i in range(100)}
        block = shape_lens(d, 2, 60)
        text = _block_to_text(block)
        assert "+80 more" in text
        assert block.height <= 25

    def test_large_list_truncated_at_zoom_2(self):
        """Large list (50 items) at zoom 2 shows '+30 more' footer."""
        lst = [f"item_{i}" for i in range(50)]
        block = shape_lens(lst, 2, 40)
        text = _block_to_text(block)
        assert "+30 more" in text

    def test_small_dict_no_truncation(self):
        """Small dict (5 keys) at zoom 2 has no 'more' text."""
        d = {f"key_{i}": f"val_{i}" for i in range(5)}
        block = shape_lens(d, 2, 60)
        text = _block_to_text(block)
        assert "more" not in text

    def test_long_string_shows_length(self):
        """Long string (5000 chars) at zoom 2 shows length indicator."""
        s = "x" * 5000
        block = shape_lens(s, 2, 300)
        text = _block_to_text(block)
        assert "5000 chars" in text

    def test_short_string_no_length(self):
        """Short string at zoom 2 shows no length indicator."""
        block = shape_lens("hello", 2, 40)
        text = _block_to_text(block)
        assert "chars" not in text

    def test_exactly_20_dict_items_no_truncation(self):
        """Dict with exactly 20 items is not truncated."""
        d = {f"key_{i}": f"val_{i}" for i in range(20)}
        block = shape_lens(d, 2, 60)
        text = _block_to_text(block)
        assert "more" not in text

    def test_21_dict_items_truncated(self):
        """Dict with 21 items shows '+1 more'."""
        d = {f"key_{i}": f"val_{i}" for i in range(21)}
        block = shape_lens(d, 2, 60)
        text = _block_to_text(block)
        assert "+1 more" in text


class TestShapeLensNestedStructures:
    """Tests for shape_lens with nested structures."""

    def test_nested_dict_reduces_zoom(self):
        """Nested dict renders at reduced zoom level."""
        d = {"outer": {"inner": "value"}}
        block = shape_lens(d, 2, 40)

        # Should still produce valid output
        text = _block_to_text(block)
        assert "outer" in text
        # Inner dict is rendered at zoom 1 (one less than 2)

    def test_list_of_dicts(self):
        """List of dicts renders properly."""
        data = [{"name": "Alice"}, {"name": "Bob"}]
        block = shape_lens(data, 2, 40)

        text = _block_to_text(block)
        # Should show list items
        assert block.height >= 2


def _block_to_text(block) -> str:
    """Extract text content from a block for testing."""
    result = []
    for y in range(block.height):
        row = block.row(y)
        line = "".join(cell.char for cell in row)
        result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Tree Lens Tests
# ---------------------------------------------------------------------------


class TestTreeLensZoom:
    """Tests for tree_lens at each zoom level."""

    def test_zoom_0_shows_root_and_count(self):
        """At zoom 0, tree shows root label + child count."""
        data = {"a": 1, "b": 2, "c": 3}
        block = tree_lens(data, 0, 40)

        text = _block_to_text(block)
        assert "root" in text
        assert "[3]" in text

    def test_zoom_1_shows_immediate_children(self):
        """At zoom 1, tree shows root + immediate children."""
        data = {"alpha": {"nested": 1}, "beta": 2}
        block = tree_lens(data, 1, 40)

        text = _block_to_text(block)
        assert "root" in text
        assert "alpha" in text
        assert "beta" in text
        # Children of alpha should show as collapsed count
        assert "[1]" in text

    def test_zoom_2_expands_nested(self):
        """At zoom 2, tree expands one more level."""
        data = {"parent": {"child": "value"}}
        block = tree_lens(data, 2, 40)

        text = _block_to_text(block)
        assert "parent" in text
        assert "child" in text

    def test_branch_characters_present(self):
        """Tree rendering includes branch characters."""
        data = {"a": 1, "b": 2}
        block = tree_lens(data, 1, 40)

        text = _block_to_text(block)
        # Should have tree branch chars
        assert "├" in text or "└" in text


class TestTreeLensStructures:
    """Tests for tree_lens with different data structures."""

    def test_nested_dict(self):
        """Nested dict renders as tree."""
        data = {"level1": {"level2": {"level3": "leaf"}}}
        block = tree_lens(data, 3, 60)

        text = _block_to_text(block)
        assert "level1" in text
        assert "level2" in text
        assert "level3" in text

    def test_tuple_form(self):
        """Tuple (label, children) form is recognized."""
        data = ("root", {"child1": None, "child2": None})
        block = tree_lens(data, 1, 40)

        text = _block_to_text(block)
        assert "root" in text
        assert "child1" in text
        assert "child2" in text

    def test_empty_dict(self):
        """Empty dict shows empty marker."""
        block = tree_lens({}, 2, 40)
        text = _block_to_text(block)
        assert "{}" in text

    def test_leaf_values_shown(self):
        """Leaf values are displayed with their values."""
        data = {"name": "Alice", "age": 30}
        block = tree_lens(data, 1, 40)

        text = _block_to_text(block)
        assert "Alice" in text
        assert "30" in text


class TestTreeLensWidth:
    """Tests for tree_lens width handling."""

    def test_respects_width(self):
        """Tree respects width constraint."""
        data = {"very_long_key_name": {"another_long_key": "value"}}
        block = tree_lens(data, 2, 20)

        assert block.width == 20

    def test_zero_width_returns_empty(self):
        """Zero width returns empty block."""
        block = tree_lens({"a": 1}, 2, 0)
        assert block.width == 0

    def test_truncates_long_labels(self):
        """Long labels are truncated with ellipsis."""
        data = {"this_is_a_very_very_long_key_name": 1}
        block = tree_lens(data, 1, 25)

        text = _block_to_text(block)
        assert "…" in text


# ---------------------------------------------------------------------------
# Chart Lens Tests
# ---------------------------------------------------------------------------


class TestChartLensZoom:
    """Tests for chart_lens at each zoom level."""

    def test_zoom_0_shows_stats(self):
        """At zoom 0, chart shows count and range."""
        data = [10, 20, 30, 40, 50]
        block = chart_lens(data, 0, 40)

        text = _block_to_text(block)
        assert "5 values" in text
        assert "10" in text
        assert "50" in text

    def test_zoom_1_shows_sparkline(self):
        """At zoom 1, chart shows sparkline characters."""
        data = [1, 3, 5, 3, 1]
        block = chart_lens(data, 1, 40)

        text = _block_to_text(block)
        # Should contain sparkline block characters
        assert any(c in text for c in "▁▂▃▄▅▆▇█")

    def test_zoom_2_shows_stats_and_sparkline(self):
        """At zoom 2, chart shows stats + sparkline."""
        data = {"cpu": 70, "mem": 50}
        block = chart_lens(data, 2, 40)

        text = _block_to_text(block)
        assert "2 values" in text  # stats line

    def test_zoom_3_shows_bars(self):
        """At zoom 3, chart shows horizontal bars."""
        data = {"cpu": 70, "mem": 50}
        block = chart_lens(data, 3, 40)

        text = _block_to_text(block)
        assert "cpu" in text
        assert "mem" in text
        # Should contain bar characters
        assert "█" in text
        assert "░" in text


class TestChartLensData:
    """Tests for chart_lens with different data formats."""

    def test_list_of_numbers(self):
        """List of numbers renders as chart."""
        data = [1, 2, 3, 4, 5]
        block = chart_lens(data, 1, 20)

        # Should produce valid output
        assert block.height >= 1
        assert block.width == 20

    def test_labeled_dict(self):
        """Dict with numeric values shows labels at zoom 3 (bars)."""
        data = {"alpha": 25, "beta": 75}
        block = chart_lens(data, 3, 40)

        text = _block_to_text(block)
        assert "alpha" in text
        assert "beta" in text

    def test_single_value(self):
        """Single number produces output."""
        block = chart_lens(42, 1, 20)
        assert block.height >= 1

    def test_empty_data(self):
        """Empty data shows no-data message."""
        block = chart_lens([], 2, 40)
        text = _block_to_text(block)
        assert "no data" in text

    def test_percentage_format(self):
        """Values 0-100 format as percentages."""
        data = {"test": 50}
        block = chart_lens(data, 3, 40)

        text = _block_to_text(block)
        assert "%" in text


class TestChartLensSparkline:
    """Tests for sparkline rendering specifics."""

    def test_sparkline_maps_range(self):
        """Sparkline maps values to character heights."""
        # Low value should use low char, high should use high char
        data = [0, 100]
        block = chart_lens(data, 1, 10)

        text = _block_to_text(block)
        # First char should be lowest, last should be highest
        assert "▁" in text
        assert "█" in text

    def test_sparkline_samples_long_data(self):
        """Sparkline samples when data exceeds width."""
        data = list(range(100))
        block = chart_lens(data, 1, 20)

        text = _block_to_text(block).strip()
        # Should fit within width (minus padding)
        assert len(text) <= 20


class TestChartLensWidth:
    """Tests for chart_lens width handling."""

    def test_respects_width(self):
        """Chart respects width constraint."""
        data = {"very_long_label_name": 50}
        block = chart_lens(data, 2, 30)

        assert block.width == 30

    def test_zero_width_returns_empty(self):
        """Zero width returns empty block."""
        block = chart_lens([1, 2, 3], 2, 0)
        assert block.width == 0

    def test_narrow_width_still_works(self):
        """Very narrow width produces valid output."""
        data = {"x": 50}
        block = chart_lens(data, 2, 15)

        assert block.width == 15
        text = _block_to_text(block)
        assert len(text.strip()) > 0


# ---------------------------------------------------------------------------
# Auto-dispatch Tests (shape_lens dispatching to chart/tree)
# ---------------------------------------------------------------------------


class TestShapeLensAutoDispatchChart:
    """Tests for shape_lens dispatching numeric data to chart_lens."""

    def test_numeric_list_gets_sparkline(self):
        """List of numbers at zoom 1 renders as sparkline, not comma-separated."""
        data = [0, 50, 100]
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        # Sparkline uses block characters
        assert any(c in text for c in "▁▂▃▄▅▆▇█")

    def test_numeric_list_zoom_0_gets_stats(self):
        """List of numbers at zoom 0 shows stats from chart_lens."""
        data = [10, 20, 30]
        block = shape_lens(data, 0, 40)
        text = _block_to_text(block)
        assert "3 values" in text

    def test_labeled_numeric_dict_gets_bars(self):
        """Dict with all-numeric values at zoom 3 renders as bar chart."""
        data = {"cpu": 70, "mem": 50}
        block = shape_lens(data, 3, 40)
        text = _block_to_text(block)
        assert "cpu" in text
        assert "█" in text

    def test_labeled_numeric_dict_zoom_1_gets_sparkline(self):
        """Dict with all-numeric values at zoom 1 renders as sparkline."""
        data = {"a": 10, "b": 50, "c": 90}
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        assert any(c in text for c in "▁▂▃▄▅▆▇█")

    def test_bool_list_not_dispatched(self):
        """List of bools is not treated as numeric."""
        data = [True, False, True]
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        # Should be comma-separated list, not sparkline
        assert "True" in text

    def test_mixed_list_not_dispatched(self):
        """List with mixed types falls back to shape rendering."""
        data = [1, "two", 3]
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        assert "two" in text

    def test_empty_list_not_dispatched(self):
        """Empty list uses shape rendering."""
        block = shape_lens([], 0, 40)
        text = _block_to_text(block)
        assert "list[0]" in text

    def test_single_number_not_dispatched(self):
        """Single number is a scalar, not a numeric sequence."""
        block = shape_lens(42, 0, 40)
        text = _block_to_text(block)
        assert "int" in text


class TestShapeLensAutoDispatchTree:
    """Tests for shape_lens dispatching hierarchical data to tree_lens."""

    def test_nested_dict_gets_tree(self):
        """Dict with nested dict values renders as tree."""
        data = {"parent": {"child": "value"}}
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        # Tree uses branch characters
        assert "├" in text or "└" in text

    def test_dict_with_nested_list_gets_tree(self):
        """Dict with nested list values renders as tree."""
        data = {"items": [1, 2, 3], "more": [4, 5]}
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        assert "├" in text or "└" in text

    def test_flat_dict_not_dispatched_to_tree(self):
        """Flat dict with string values uses shape rendering, not tree."""
        data = {"name": "Alice", "role": "admin"}
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        # Should be comma-separated keys, not tree branches
        assert "name" in text
        assert "├" not in text and "└" not in text

    def test_empty_nested_not_dispatched(self):
        """Dict with empty nested containers uses shape rendering."""
        data = {"items": [], "config": {}}
        block = shape_lens(data, 1, 40)
        text = _block_to_text(block)
        # Empty containers don't count as hierarchical
        assert "├" not in text and "└" not in text
