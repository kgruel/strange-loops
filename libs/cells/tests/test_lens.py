"""Tests for Lens primitive and shape_lens function."""

import pytest

from cells import Lens, shape_lens, SHAPE_LENS


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
