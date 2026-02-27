"""Extended tests for painted._text_width: fallback paths, edge cases."""

from __future__ import annotations

from painted._text_width import (
    char_width,
    display_width,
    index_for_col,
    take_prefix,
    truncate,
    truncate_ellipsis,
)


# =============================================================================
# display_width
# =============================================================================


class TestDisplayWidth:
    def test_ascii(self):
        assert display_width("hello") == 5

    def test_empty(self):
        assert display_width("") == 0

    def test_wide_char(self):
        # CJK character is 2 columns wide
        assert display_width("\u4e16") == 2

    def test_fallback_on_control_chars(self):
        # wcswidth returns -1 for strings containing control characters,
        # so display_width falls back to len().
        assert display_width("\x01\x02") == 2


# =============================================================================
# char_width
# =============================================================================


class TestCharWidth:
    def test_ascii_char(self):
        assert char_width("a") == 1

    def test_wide_char(self):
        assert char_width("\u4e16") == 2

    def test_control_char_fallback(self):
        # wcwidth returns -1 for certain control chars; char_width falls back to 1.
        # \x01 (SOH) is a true control char that wcwidth returns -1 for.
        assert char_width("\x01") == 1

    def test_zero_width_combining(self):
        # U+0301 is a combining acute accent (zero width).
        assert char_width("\u0301") == 0


# =============================================================================
# take_prefix
# =============================================================================


class TestTakePrefix:
    def test_empty_string(self):
        assert take_prefix("", 5) == ("", 0)

    def test_zero_width(self):
        assert take_prefix("hello", 0) == ("", 0)

    def test_negative_width(self):
        assert take_prefix("hello", -1) == ("", 0)

    def test_exact_fit(self):
        assert take_prefix("abc", 3) == ("abc", 3)

    def test_truncated(self):
        assert take_prefix("abcde", 3) == ("abc", 3)

    def test_wide_char_boundary(self):
        # Wide char (2 cols) doesn't fit in remaining 1 col.
        prefix, consumed = take_prefix("a\u4e16b", 2)
        assert prefix == "a"
        assert consumed == 1

    def test_zero_width_combining_marks_kept(self):
        # Combining mark after a base char should be included when there's room.
        # "a" + combining acute accent (U+0301) + "b" = 2 display cols.
        # With max_width=2, "a" uses 1 col, "\u0301" is zero-width (kept),
        # "b" uses 1 col => all fit.
        text = "a\u0301b"
        prefix, consumed = take_prefix(text, 2)
        assert prefix == "a\u0301b"
        assert consumed == 3

    def test_max_width_exact_match_breaks(self):
        # When used == max_width, loop breaks.
        prefix, consumed = take_prefix("ab", 1)
        assert prefix == "a"
        assert consumed == 1


# =============================================================================
# truncate
# =============================================================================


class TestTruncate:
    def test_within_limit(self):
        assert truncate("hi", 5) == "hi"

    def test_at_limit(self):
        assert truncate("hello", 5) == "hello"

    def test_over_limit(self):
        assert truncate("hello world", 5) == "hello"


# =============================================================================
# truncate_ellipsis
# =============================================================================


class TestTruncateEllipsis:
    def test_fits(self):
        assert truncate_ellipsis("hi", 10) == "hi"

    def test_truncated_with_ellipsis(self):
        result = truncate_ellipsis("hello world", 6)
        assert result == "hello\u2026"

    def test_zero_width_returns_empty(self):
        assert truncate_ellipsis("hello", 0) == ""

    def test_negative_width_returns_empty(self):
        assert truncate_ellipsis("hello", -1) == ""

    def test_ellipsis_wider_than_max(self):
        # ellipsis itself takes 1 col but max_width is 1, so ell_w >= max_width.
        # Falls back to plain truncate.
        result = truncate_ellipsis("hello world", 1, ellipsis="\u2026")
        assert len(result) == 1

    def test_custom_ellipsis(self):
        result = truncate_ellipsis("hello world", 8, ellipsis="...")
        assert result.endswith("...")
        assert display_width(result) <= 8

    def test_empty_ellipsis_string(self):
        # Empty ellipsis has display_width 0 => ell_w <= 0.
        result = truncate_ellipsis("hello world", 5, ellipsis="")
        assert display_width(result) <= 5


# =============================================================================
# index_for_col
# =============================================================================


class TestIndexForCol:
    def test_empty_string(self):
        assert index_for_col("", 5) == 0

    def test_zero_col(self):
        assert index_for_col("hello", 0) == 0

    def test_negative_col(self):
        assert index_for_col("hello", -1) == 0

    def test_col_within_string(self):
        assert index_for_col("abcde", 3) == 3

    def test_col_beyond_string(self):
        # col exceeds string width => returns len(text).
        assert index_for_col("ab", 10) == 2

    def test_zero_width_chars_skipped(self):
        # U+0301 combining accent is zero-width and should be skipped.
        text = "a\u0301b"
        # col=1 means first display column; "a" takes col 0, "\u0301" is 0-width,
        # "b" starts at col 1.
        idx = index_for_col(text, 1)
        assert idx == 2  # index of "b"

    def test_wide_char_boundary(self):
        # Wide char takes 2 cols.
        text = "\u4e16b"  # 2 cols + 1 col
        idx = index_for_col(text, 1)
        # col=1, but wide char needs 2 cols (0+2=2 > 1), so index stays at 0.
        assert idx == 0
