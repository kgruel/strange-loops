"""Tests for Lens primitive and lens functions (shape, tree, chart)."""

import pytest

from cells import (
    Lens,
    shape_lens,
    SHAPE_LENS,
    tree_lens,
    TREE_LENS,
    chart_lens,
    CHART_LENS,
)


class TestLensDataclass:
    """Tests for Lens dataclass properties."""

    def test_lens_is_frozen(self):
        """Lens dataclass is frozen."""
        lens = Lens(render=lambda c, z, w: None, max_zoom=3)
        with pytest.raises((AttributeError, TypeError)):
            lens.max_zoom = 5  # type: ignore

    def test_lens_default_max_zoom(self):
        """Lens has default max_zoom of 2."""
        lens = Lens(render=lambda c, z, w: None)
        assert lens.max_zoom == 2

    def test_lens_custom_max_zoom(self):
        """Lens accepts custom max_zoom."""
        lens = Lens(render=lambda c, z, w: None, max_zoom=5)
        assert lens.max_zoom == 5

    def test_lens_render_callable(self):
        """Lens stores and exposes the render function."""
        calls = []

        def my_render(content, zoom, width):
            calls.append((content, zoom, width))
            return None

        lens = Lens(render=my_render)
        lens.render("test", 1, 40)

        assert calls == [("test", 1, 40)]

    def test_shape_lens_constant(self):
        """SHAPE_LENS is a Lens with shape_lens as render."""
        assert isinstance(SHAPE_LENS, Lens)
        assert SHAPE_LENS.render is shape_lens
        assert SHAPE_LENS.max_zoom == 2


class TestShapeLensDictZoom:
    """Tests for shape_lens with dict at each zoom level."""

    def test_dict_zoom_0_shows_count(self):
        """At zoom 0, dict shows 'dict[N]' count."""
        d = {"a": 1, "b": 2, "c": 3}
        block = shape_lens(d, 0, 40)

        # Extract text from block
        text = _block_to_text(block)
        assert "dict[3]" in text

    def test_dict_zoom_1_shows_keys(self):
        """At zoom 1, dict shows comma-separated keys."""
        d = {"name": "Alice", "age": 30}
        block = shape_lens(d, 1, 40)

        text = _block_to_text(block)
        assert "name" in text
        assert "age" in text

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
        lst = [1, 2, 3, 4, 5]
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


class TestTreeLensConstant:
    """Tests for TREE_LENS constant."""

    def test_tree_lens_constant(self):
        """TREE_LENS is a Lens with tree_lens as render."""
        assert isinstance(TREE_LENS, Lens)
        assert TREE_LENS.render is tree_lens
        assert TREE_LENS.max_zoom == 4


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


class TestChartLensConstant:
    """Tests for CHART_LENS constant."""

    def test_chart_lens_constant(self):
        """CHART_LENS is a Lens with chart_lens as render."""
        assert isinstance(CHART_LENS, Lens)
        assert CHART_LENS.render is chart_lens
        assert CHART_LENS.max_zoom == 2


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

    def test_zoom_2_shows_bars(self):
        """At zoom 2, chart shows horizontal bars."""
        data = {"cpu": 70, "mem": 50}
        block = chart_lens(data, 2, 40)

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
        """Dict with numeric values shows labels."""
        data = {"alpha": 25, "beta": 75}
        block = chart_lens(data, 2, 40)

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
        block = chart_lens(data, 2, 40)

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
