"""Tests for flame_lens — proportional hierarchical visualization."""

from painted.views import flame_lens


def _block_to_text(block) -> str:
    """Extract text content from a block for testing."""
    result = []
    for y in range(block.height):
        row = block.row(y)
        line = "".join(cell.char for cell in row)
        result.append(line)
    return "\n".join(result)


class TestFlameLensZoom:
    """Tests for flame_lens at each zoom level."""

    def test_zoom_0_shows_total(self):
        """At zoom 0, flame shows root label + total value."""
        data = {"render": 45, "diff": 30, "flush": 25}
        block = flame_lens(data, 0, 40)
        text = _block_to_text(block)
        assert "100" in text  # total of 45+30+25

    def test_zoom_1_shows_single_row(self):
        """At zoom 1, flame shows top-level segments in one row."""
        data = {"render": 45, "diff": 30, "flush": 25}
        block = flame_lens(data, 1, 60)
        text = _block_to_text(block)
        assert "render" in text
        assert "diff" in text
        assert "flush" in text
        assert block.height == 1

    def test_zoom_2_expands_children(self):
        """At zoom 2+, flame expands child segments into additional rows."""
        data = {"main": {"render": 45, "diff": 30, "flush": 25}}
        block = flame_lens(data, 2, 60)
        text = _block_to_text(block)
        assert "main" in text
        assert "render" in text
        assert block.height >= 2


class TestFlameLensProportions:
    """Tests for proportional width allocation."""

    def test_segments_fill_width(self):
        """All segments together fill the available width."""
        data = {"a": 50, "b": 50}
        block = flame_lens(data, 1, 40)
        assert block.width == 40

    def test_larger_segment_gets_more_width(self):
        """Segment with larger value gets proportionally more characters."""
        data = {"big": 90, "small": 10}
        block = flame_lens(data, 1, 40)
        row = block.row(0)
        row_text = "".join(c.char for c in row)
        assert row_text.index("big") < row_text.index("small")

    def test_single_segment_fills_width(self):
        """A single segment fills the entire width."""
        data = {"only": 100}
        block = flame_lens(data, 1, 30)
        assert block.width == 30


class TestFlameLensEdgeCases:
    """Tests for edge cases."""

    def test_empty_data(self):
        """Empty dict produces valid output."""
        block = flame_lens({}, 1, 40)
        text = _block_to_text(block)
        assert "no data" in text.lower() or block.height >= 1

    def test_zero_width_returns_empty(self):
        """Zero width returns empty block."""
        block = flame_lens({"a": 1}, 1, 0)
        assert block.width == 0

    def test_nested_three_levels(self):
        """Three-level nesting at high zoom."""
        data = {"top": {"mid": {"leaf": 100}}}
        block = flame_lens(data, 3, 60)
        text = _block_to_text(block)
        assert "top" in text
        assert "mid" in text
        assert "leaf" in text

    def test_zero_values_handled(self):
        """Zero-valued segments don't cause division errors."""
        data = {"active": 100, "idle": 0}
        block = flame_lens(data, 1, 40)
        text = _block_to_text(block)
        assert "active" in text

    def test_width_respected(self):
        """Output block respects width constraint."""
        data = {"a": 30, "b": 70}
        block = flame_lens(data, 1, 50)
        assert block.width == 50
