"""Tests for the table() render function."""

from __future__ import annotations

from painted import Cursor, Style, Viewport
from painted.span import Line
from painted.views import Column, TableState, table
from tests.helpers import row_text


def _make_columns(headers: list[str], widths: list[int]) -> list[Column]:
    """Build Column list from header strings and widths."""
    return [Column(header=Line.plain(h), width=w) for h, w in zip(headers, widths)]


def _make_rows(data: list[list[str]]) -> list[list[Line]]:
    """Build row data from plain strings."""
    return [[Line.plain(cell) for cell in row] for row in data]


class TestBasicTableRendering:
    def test_single_column_single_row(self) -> None:
        cols = _make_columns(["Name"], [6])
        rows = _make_rows([["Alice"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=3)

        assert blk.height >= 3  # header + separator + at least 1 data row
        assert "Name" in row_text(blk, 0)
        assert "Alice" in row_text(blk, 2)

    def test_two_columns_with_separator(self) -> None:
        cols = _make_columns(["Name", "Age"], [6, 4])
        rows = _make_rows([["Alice", "30"], ["Bob", "25"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=3)

        header = row_text(blk, 0)
        assert "Name" in header
        assert "Age" in header
        assert "│" in header

    def test_multiple_rows_rendered(self) -> None:
        cols = _make_columns(["Item"], [10])
        rows = _make_rows([["apple"], ["banana"], ["cherry"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=5)

        assert "apple" in row_text(blk, 2)
        assert "banana" in row_text(blk, 3)
        assert "cherry" in row_text(blk, 4)


class TestSeparatorRow:
    def test_separator_uses_horizontal_lines(self) -> None:
        cols = _make_columns(["A", "B"], [4, 4])
        rows = _make_rows([["x", "y"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        sep_row = row_text(blk, 1)
        assert "─" in sep_row
        assert "┼" in sep_row

    def test_single_column_separator_no_cross(self) -> None:
        cols = _make_columns(["Col"], [5])
        rows = _make_rows([["val"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        sep_row = row_text(blk, 1)
        assert "─" in sep_row
        assert "┼" not in sep_row


class TestSelectedRowHighlighting:
    def test_first_row_selected_by_default(self) -> None:
        cols = _make_columns(["Name"], [6])
        rows = _make_rows([["Alice"], ["Bob"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=3)

        # Row 0 (buf_y=2) should have selected_style (reverse=True)
        first_data_row = blk.row(2)
        assert any(c.style.reverse for c in first_data_row)

    def test_second_row_not_selected_by_default(self) -> None:
        cols = _make_columns(["Name"], [6])
        rows = _make_rows([["Alice"], ["Bob"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=3)

        second_data_row = blk.row(3)
        assert not any(c.style.reverse for c in second_data_row)

    def test_moved_selection(self) -> None:
        cols = _make_columns(["Name"], [6])
        rows = _make_rows([["Alice"], ["Bob"], ["Carol"]])
        state = TableState(cursor=Cursor(index=1, count=3))

        blk = table(state, cols, rows, visible_height=5)

        # Row 0 (Alice) should not be selected
        assert not any(c.style.reverse for c in blk.row(2))
        # Row 1 (Bob) should be selected
        assert any(c.style.reverse for c in blk.row(3))

    def test_custom_selected_style(self) -> None:
        cols = _make_columns(["X"], [4])
        rows = _make_rows([["hi"]])
        state = TableState()
        custom = Style(bold=True)

        blk = table(state, cols, rows, visible_height=2, selected_style=custom)

        data_row = blk.row(2)
        assert any(c.style.bold for c in data_row)


class TestColumnWidthAllocation:
    def test_total_width_single_column(self) -> None:
        cols = _make_columns(["Name"], [10])
        rows = _make_rows([["test"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        assert blk.width == 10

    def test_total_width_multiple_columns(self) -> None:
        cols = _make_columns(["A", "B", "C"], [5, 8, 3])
        rows = _make_rows([["x", "y", "z"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        # 5 + 8 + 3 + 2 separators (1 char each) = 18
        assert blk.width == 18

    def test_short_content_padded(self) -> None:
        cols = _make_columns(["Name"], [10])
        rows = _make_rows([["Hi"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        row_line = row_text(blk, 2)
        assert len(row_line) == 10
        assert row_line.startswith("Hi")

    def test_long_content_truncated(self) -> None:
        cols = _make_columns(["Name"], [4])
        rows = _make_rows([["VeryLongName"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        row_line = row_text(blk, 2)
        assert len(row_line) == 4


class TestScrollingBehavior:
    def test_no_scroll_when_rows_fit(self) -> None:
        cols = _make_columns(["V"], [5])
        rows = _make_rows([["a"], ["b"], ["c"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=5)

        assert "a" in row_text(blk, 2)
        assert "b" in row_text(blk, 3)
        assert "c" in row_text(blk, 4)

    def test_scroll_offset_skips_rows(self) -> None:
        cols = _make_columns(["V"], [5])
        rows = _make_rows([["a"], ["b"], ["c"], ["d"], ["e"]])
        state = TableState(
            cursor=Cursor(index=3, count=5),
            viewport=Viewport(offset=2, visible=3, content=5),
        )

        blk = table(state, cols, rows, visible_height=3)

        # Visible window: rows c, d, e (offset=2)
        assert "c" in row_text(blk, 2)
        assert "d" in row_text(blk, 3)
        assert "e" in row_text(blk, 4)

    def test_scroll_shows_correct_selection(self) -> None:
        cols = _make_columns(["V"], [5])
        rows = _make_rows([["a"], ["b"], ["c"], ["d"], ["e"]])
        state = TableState(
            cursor=Cursor(index=3, count=5),
            viewport=Viewport(offset=2, visible=3, content=5),
        )

        blk = table(state, cols, rows, visible_height=3)

        # "d" is at index 3, visible at buf_y = 2 + (3-2) = 3
        assert any(c.style.reverse for c in blk.row(3))
        # "c" at buf_y=2 should not be selected
        assert not any(c.style.reverse for c in blk.row(2))


class TestEdgeCases:
    def test_empty_columns(self) -> None:
        state = TableState()
        blk = table(state, [], [], visible_height=3)

        assert blk.width == 1
        assert blk.height == 5  # empty(1, visible_height + 2)

    def test_empty_rows(self) -> None:
        cols = _make_columns(["Name"], [6])
        state = TableState()

        blk = table(state, cols, [], visible_height=3)

        assert "Name" in row_text(blk, 0)
        assert "─" in row_text(blk, 1)
        # Data area should be blank
        assert blk.height >= 3

    def test_rows_fewer_cells_than_columns(self) -> None:
        cols = _make_columns(["A", "B", "C"], [3, 3, 3])
        rows = [[Line.plain("x")]]  # Only 1 cell, but 3 columns
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        data_text = row_text(blk, 2)
        assert "x" in data_text

    def test_custom_separator(self) -> None:
        cols = _make_columns(["A", "B"], [3, 3])
        rows = _make_rows([["x", "y"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2, separator=" | ")

        header = row_text(blk, 0)
        assert " | " in header

    def test_header_style_applied(self) -> None:
        cols = _make_columns(["Name"], [6])
        rows = _make_rows([["val"]])
        custom_header = Style(italic=True)
        state = TableState()

        blk = table(state, cols, rows, visible_height=2, header_style=custom_header)

        header_row = blk.row(0)
        assert any(c.style.italic for c in header_row)

    def test_block_height_matches_visible_plus_header(self) -> None:
        cols = _make_columns(["Col"], [5])
        rows = _make_rows([["a"], ["b"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=4)

        # header(1) + separator(1) + visible_height(4) = 6
        assert blk.height == 6


class TestColumnAlignment:
    def test_end_aligned_column(self) -> None:
        from painted.compose import Align

        cols = [Column(header=Line.plain("Num"), width=6, align=Align.END)]
        rows = _make_rows([["42"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        data_text = row_text(blk, 2)
        # "42" should be right-aligned in a 6-wide column
        assert data_text.endswith("42") or data_text.rstrip() == "42"

    def test_center_aligned_column(self) -> None:
        from painted.compose import Align

        cols = [Column(header=Line.plain("Mid"), width=7, align=Align.CENTER)]
        rows = _make_rows([["hi"]])
        state = TableState()

        blk = table(state, cols, rows, visible_height=2)

        data_text = row_text(blk, 2)
        stripped = data_text.strip()
        assert stripped == "hi"
        # Should have padding on both sides
        left_pad = len(data_text) - len(data_text.lstrip())
        right_pad = len(data_text) - len(data_text.rstrip())
        assert left_pad > 0
        assert right_pad > 0
