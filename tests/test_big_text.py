"""Tests for big text rendering."""

import pytest
from fidelis import Style
from fidelis.effects import render_big, BIG_GLYPHS, BigTextFormat


class TestRenderBig:
    """Tests for render_big function."""

    def test_single_char(self):
        """Single character renders as 3x3 block."""
        block = render_big("a")
        assert block.height == 3
        assert block.width == 3

    def test_two_chars_with_gap(self):
        """Two characters: 3 + 1 (gap) + 3 = 7 width."""
        block = render_big("ab")
        assert block.height == 3
        assert block.width == 7

    def test_word_width(self):
        """Width formula: n*3 + (n-1)*1 = n*4 - 1."""
        block = render_big("hello")
        # 5 chars: 5*3 + 4*1 = 19
        assert block.width == 19
        assert block.height == 3

    def test_empty_string(self):
        """Empty string returns 0-width, 3-height block."""
        block = render_big("")
        assert block.width == 0
        assert block.height == 3

    def test_empty_string_size_2(self):
        """Empty string with size 2 returns 0-width, 5-height block."""
        block = render_big("", size=2)
        assert block.width == 0
        assert block.height == 5

    def test_case_folding(self):
        """Uppercase folds to lowercase."""
        upper = render_big("ABC")
        lower = render_big("abc")
        # Same dimensions
        assert upper.width == lower.width
        assert upper.height == lower.height
        # Same content (compare cell chars)
        for row in range(3):
            upper_row = [c.char for c in upper.row(row)]
            lower_row = [c.char for c in lower.row(row)]
            assert upper_row == lower_row

    def test_unknown_char_renders_fallback(self):
        """Unknown characters render as box placeholder."""
        block = render_big("\u00a7")  # Section sign - not in glyph map
        assert block.height == 3
        assert block.width == 3
        # Should be the fallback box glyph
        fallback = BIG_GLYPHS['\x00']
        for row_idx in range(3):
            row_chars = ''.join(c.char for c in block.row(row_idx))
            assert row_chars == fallback[row_idx]

    def test_digits(self):
        """Digits 0-9 all render."""
        block = render_big("0123456789")
        # 10 chars: 10*3 + 9*1 = 39
        assert block.width == 39
        assert block.height == 3

    def test_punctuation(self):
        """Common punctuation renders."""
        block = render_big(".,!?-:")
        assert block.height == 3
        # 6 chars: 6*3 + 5*1 = 23
        assert block.width == 23

    def test_space(self):
        """Space renders as empty 3-wide glyph."""
        block = render_big("a b")
        # 3 chars: 3*3 + 2*1 = 11
        assert block.width == 11
        # Middle glyph (space) should be all spaces
        # Columns 4-6 are the space glyph (after 'a' glyph 0-2 and gap at 3)
        for row in range(3):
            row_cells = list(block.row(row))
            # Gap is at index 3, space glyph at 4,5,6
            assert row_cells[4].char == ' '
            assert row_cells[5].char == ' '
            assert row_cells[6].char == ' '

    def test_whitespace_normalization(self):
        """Tabs and newlines become spaces."""
        block_tab = render_big("a\tb")
        block_space = render_big("a b")
        assert block_tab.width == block_space.width

    def test_style_applied(self):
        """Style propagates to all cells."""
        style = Style(fg=(255, 0, 0), bold=True)
        block = render_big("x", style)
        for row in range(3):
            for cell in block.row(row):
                assert cell.style == style

    def test_all_glyphs_are_3x3(self):
        """Every glyph is exactly 3 rows of 3 characters."""
        for char, glyph in BIG_GLYPHS.items():
            assert len(glyph) == 3, f"Glyph '{char}' has {len(glyph)} rows"
            for i, row in enumerate(glyph):
                assert len(row) == 3, f"Glyph '{char}' row {i} has width {len(row)}"


class TestBigGlyphs:
    """Tests for the glyph dictionary."""

    def test_fallback_exists(self):
        """Fallback glyph exists at null character."""
        assert '\x00' in BIG_GLYPHS

    def test_alphabet_coverage(self):
        """All lowercase letters have glyphs."""
        for char in 'abcdefghijklmnopqrstuvwxyz':
            assert char in BIG_GLYPHS, f"Missing glyph for '{char}'"

    def test_digit_coverage(self):
        """All digits have glyphs."""
        for char in '0123456789':
            assert char in BIG_GLYPHS, f"Missing glyph for '{char}'"

    def test_common_punctuation_coverage(self):
        """Common punctuation has glyphs."""
        for char in ' .,!?-:':
            assert char in BIG_GLYPHS, f"Missing glyph for '{char}'"


class TestSize2:
    """Tests for size 2 (5-row) rendering."""

    def test_size_2_height(self):
        """Size 2 produces 5-row blocks."""
        block = render_big("a", size=2)
        assert block.height == 5
        assert block.width == 5

    def test_size_2_word_width(self):
        """Size 2 width: n*5 + (n-1)*1 = n*6 - 1."""
        block = render_big("hi", size=2)
        # 2 chars: 2*5 + 1*1 = 11
        assert block.width == 11
        assert block.height == 5

    def test_size_2_style_applied(self):
        """Style propagates in size 2."""
        style = Style(fg=(0, 255, 0))
        block = render_big("x", style, size=2)
        for row in range(5):
            for cell in block.row(row):
                assert cell.style == style


class TestBigTextFormat:
    """Tests for format options."""

    def test_filled_is_default(self):
        """Filled format is the default."""
        filled = render_big("a")
        explicit = render_big("a", format=BigTextFormat.FILLED)
        for row in range(3):
            filled_row = [c.char for c in filled.row(row)]
            explicit_row = [c.char for c in explicit.row(row)]
            assert filled_row == explicit_row

    def test_outline_produces_block(self):
        """Outline format produces valid block."""
        block = render_big("a", format=BigTextFormat.OUTLINE)
        assert block.height == 3
        assert block.width == 3

    def test_outline_size_2(self):
        """Outline works with size 2."""
        block = render_big("ab", size=2, format=BigTextFormat.OUTLINE)
        assert block.height == 5
        assert block.width == 11  # 2*5 + 1

    def test_format_enum_values(self):
        """BigTextFormat has expected values."""
        assert BigTextFormat.FILLED.value == "filled"
        assert BigTextFormat.OUTLINE.value == "outline"

    def test_outline_differs_from_filled(self):
        """Outline format renders differently than filled."""
        filled = render_big("o")
        outline = render_big("o", format=BigTextFormat.OUTLINE)
        # Both have same dimensions
        assert filled.width == outline.width
        assert filled.height == outline.height
        # But different content
        filled_chars = [c.char for row in range(3) for c in filled.row(row)]
        outline_chars = [c.char for row in range(3) for c in outline.row(row)]
        assert filled_chars != outline_chars

    def test_outline_uses_box_drawing(self):
        """Outline format uses box-drawing characters."""
        outline = render_big("o", format=BigTextFormat.OUTLINE)
        chars = set(c.char for row in range(3) for c in outline.row(row))
        # Should contain box-drawing characters
        box_chars = {'┌', '┐', '└', '┘', '│', '─'}
        assert chars & box_chars, f"Expected box-drawing chars, got {chars}"
