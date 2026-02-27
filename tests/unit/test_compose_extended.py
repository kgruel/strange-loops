"""Extended tests for painted.compose — covering id propagation, alignment, edge cases."""

from painted import (
    Align,
    Block,
    Cell,
    Style,
    border,
    join_horizontal,
    join_responsive,
    join_vertical,
    pad,
    truncate,
    vslice,
)
from painted.borders import HEAVY, ROUNDED


def _text_block(lines: list[str], style: Style = Style(), *, id: str | None = None) -> Block:
    """Build a Block from lines of text."""
    width = max(len(ln) for ln in lines) if lines else 0
    rows = []
    for line in lines:
        row = [Cell(ch, style) for ch in line]
        row += [Cell(" ", style)] * (width - len(line))
        rows.append(row)
    return Block(rows, width, id=id)


def _text_block_with_ids(
    lines: list[str], ids: list[list[str | None]], style: Style = Style()
) -> Block:
    """Build a Block with per-cell id data (_ids)."""
    width = max(len(ln) for ln in lines) if lines else 0
    rows = []
    for line in lines:
        row = [Cell(ch, style) for ch in line]
        row += [Cell(" ", style)] * (width - len(line))
        rows.append(row)
    return Block(rows, width, ids=ids)


def _row_text(block: Block, row_idx: int) -> str:
    return "".join(c.char for c in block.row(row_idx))


def _row_ids(block: Block, row_idx: int) -> list[str | None]:
    if block._ids is not None:
        return list(block._ids[row_idx])
    return []


# ---------------------------------------------------------------------------
# pad() with id propagation
# ---------------------------------------------------------------------------


class TestPadIdPropagation:
    def test_pad_preserves_block_id_when_no_ids(self):
        """pad() should forward block.id when _ids is None."""
        b = _text_block(["ab"], id="box")
        result = pad(b, left=1, right=1, top=1, bottom=1)
        assert result.id == "box"
        assert result._ids is None

    def test_pad_propagates_ids_matrix(self):
        """pad() should wrap _ids with None padding cells."""
        b = _text_block_with_ids(["ab"], ids=[["x", "y"]])
        result = pad(b, left=1, right=1, top=1, bottom=1)
        assert result.width == 4
        assert result.height == 3
        # Top row: all None
        assert _row_ids(result, 0) == [None, None, None, None]
        # Content row: None + x + y + None
        assert _row_ids(result, 1) == [None, "x", "y", None]
        # Bottom row: all None
        assert _row_ids(result, 2) == [None, None, None, None]

    def test_pad_ids_left_right_only(self):
        """pad() with only left/right preserves ids correctly."""
        b = _text_block_with_ids(["ab", "cd"], ids=[["a", "b"], ["c", "d"]])
        result = pad(b, left=2, right=1)
        assert result.width == 5
        assert result.height == 2
        assert _row_ids(result, 0) == [None, None, "a", "b", None]
        assert _row_ids(result, 1) == [None, None, "c", "d", None]

    def test_pad_ids_top_bottom_only(self):
        """pad() with only top/bottom adds blank id rows."""
        b = _text_block_with_ids(["ab"], ids=[["x", "y"]])
        result = pad(b, top=2, bottom=1)
        assert result.height == 4
        assert _row_ids(result, 0) == [None, None]
        assert _row_ids(result, 1) == [None, None]
        assert _row_ids(result, 2) == ["x", "y"]
        assert _row_ids(result, 3) == [None, None]


# ---------------------------------------------------------------------------
# border() with id propagation
# ---------------------------------------------------------------------------


class TestBorderIdPropagation:
    def test_border_id_param_used(self):
        """border(id=...) wraps entire border with that id."""
        b = _text_block(["ab"])
        result = border(b, id="frame")
        assert result._ids is not None
        # Top border row: all "frame"
        assert _row_ids(result, 0) == ["frame"] * result.width
        # Content row: frame + inner + frame
        ids_row1 = _row_ids(result, 1)
        assert ids_row1[0] == "frame"
        assert ids_row1[-1] == "frame"
        # Bottom border row
        assert _row_ids(result, 2) == ["frame"] * result.width

    def test_border_inherits_block_id_when_no_ids(self):
        """border() with no id param inherits block.id for the border cells."""
        b = _text_block(["ab"], id="inner")
        result = border(b)
        # When block has id but no _ids, border_id falls through to block.id
        assert result._ids is None
        assert result.id == "inner"

    def test_border_with_block_ids_matrix(self):
        """border() preserves inner _ids and uses border_id for frame."""
        b = _text_block_with_ids(["ab"], ids=[["x", "y"]])
        result = border(b, id="fr")
        assert result._ids is not None
        # Top: fr fr fr fr
        assert _row_ids(result, 0) == ["fr", "fr", "fr", "fr"]
        # Content: fr x y fr
        assert _row_ids(result, 1) == ["fr", "x", "y", "fr"]
        # Bottom: fr fr fr fr
        assert _row_ids(result, 2) == ["fr", "fr", "fr", "fr"]

    def test_border_block_ids_no_border_id(self):
        """border() with block._ids but no id param uses None for border cells."""
        b = _text_block_with_ids(["ab"], ids=[["x", "y"]])
        result = border(b)
        assert result._ids is not None
        # border_id is None since no id param and block._ids is not None
        assert _row_ids(result, 0) == [None, None, None, None]
        assert _row_ids(result, 1) == [None, "x", "y", None]
        assert _row_ids(result, 2) == [None, None, None, None]

    def test_border_block_has_id_and_ids(self):
        """border() with block that has both .id and ._ids — _ids takes precedence for inner."""
        b = Block(
            [[Cell("a", Style()), Cell("b", Style())]],
            2,
            id="fallback",
            ids=[["x", "y"]],
        )
        result = border(b, id="fr")
        # Inner content uses _ids, not block.id
        assert _row_ids(result, 1) == ["fr", "x", "y", "fr"]

    def test_border_block_with_id_no_ids_no_border_id(self):
        """border() block.id used for content ids when _ids absent and has_ids true."""
        # has_ids is true because block.id is set (via another block in join)
        b = _text_block(["ab"], id="inner")
        # Give explicit border id to trigger has_ids
        result = border(b, id="bdr")
        assert result._ids is not None
        # Content row: border cells should be "bdr", inner should be "inner"
        assert _row_ids(result, 1) == ["bdr", "inner", "inner", "bdr"]

    def test_border_no_ids_anywhere(self):
        """border() with no ids at all returns block with no _ids."""
        b = _text_block(["ab"])
        result = border(b)
        assert result._ids is None
        assert result.id == None


# ---------------------------------------------------------------------------
# truncate() with id propagation
# ---------------------------------------------------------------------------


class TestTruncateIdPropagation:
    def test_truncate_no_truncation_returns_same(self):
        """If width >= block width, return same block."""
        b = _text_block(["abc"], id="t")
        result = truncate(b, 5)
        assert result is b

    def test_truncate_preserves_block_id(self):
        """truncate() forwards block.id when no _ids."""
        b = _text_block(["abcde"], id="row")
        result = truncate(b, 3)
        assert result.id == "row"
        assert result._ids is None
        assert result.width == 3

    def test_truncate_with_ids(self):
        """truncate() slices _ids and appends last id for ellipsis."""
        b = _text_block_with_ids(["abcde"], ids=[["a", "b", "c", "d", "e"]])
        result = truncate(b, 3)
        assert result.width == 3
        assert result._ids is not None
        # width=3: first 2 cells + ellipsis cell, ids: first 2 + id at index 2
        assert _row_ids(result, 0) == ["a", "b", "c"]

    def test_truncate_width_zero(self):
        """truncate() to width 0 produces empty rows."""
        b = _text_block_with_ids(["abc"], ids=[["x", "y", "z"]])
        result = truncate(b, 0)
        assert result.width == 0
        assert result.height == 1
        assert _row_ids(result, 0) == []

    def test_truncate_width_one(self):
        """truncate() to width 1 produces just the ellipsis."""
        b = _text_block_with_ids(["abc"], ids=[["x", "y", "z"]])
        result = truncate(b, 1)
        assert result.width == 1
        assert _row_text(result, 0) == "\u2026"
        assert _row_ids(result, 0) == ["x"]

    def test_truncate_multirow_with_ids(self):
        """truncate() handles multiple rows with _ids."""
        b = _text_block_with_ids(
            ["abcd", "efgh"],
            ids=[["a", "b", "c", "d"], ["e", "f", "g", "h"]],
        )
        result = truncate(b, 3)
        assert result.height == 2
        assert _row_ids(result, 0) == ["a", "b", "c"]
        assert _row_ids(result, 1) == ["e", "f", "g"]


# ---------------------------------------------------------------------------
# vslice() with id propagation
# ---------------------------------------------------------------------------


class TestVsliceIdPropagation:
    def test_vslice_preserves_block_id(self):
        """vslice() forwards block.id."""
        b = _text_block(["aaa", "bbb", "ccc"], id="src")
        result = vslice(b, 1, 1)
        assert result.id == "src"
        assert _row_text(result, 0) == "bbb"

    def test_vslice_with_ids(self):
        """vslice() slices _ids rows."""
        b = _text_block_with_ids(
            ["ab", "cd", "ef"],
            ids=[["a1", "a2"], ["b1", "b2"], ["c1", "c2"]],
        )
        result = vslice(b, 1, 2)
        assert result._ids is not None
        assert _row_ids(result, 0) == ["b1", "b2"]
        assert _row_ids(result, 1) == ["c1", "c2"]

    def test_vslice_empty_result_preserves_id(self):
        """vslice() returning empty block keeps block.id."""
        b = _text_block(["aaa"], id="kept")
        result = vslice(b, 5, 2)
        assert result.id == "kept"
        assert result.height == 0

    def test_vslice_zero_height(self):
        """vslice() with height=0 returns empty block."""
        b = _text_block(["abc", "def"])
        result = vslice(b, 0, 0)
        assert result.height == 0
        assert result.width == 3


# ---------------------------------------------------------------------------
# join_horizontal() with id propagation
# ---------------------------------------------------------------------------


class TestJoinHorizontalIds:
    def test_join_horizontal_empty(self):
        """join_horizontal() with no blocks returns empty."""
        result = join_horizontal()
        assert result.width == 0
        assert result.height == 0

    def test_join_horizontal_with_block_ids(self):
        """join_horizontal() propagates block.id values."""
        a = _text_block(["ab"], id="left")
        b = _text_block(["cd"], id="right")
        result = join_horizontal(a, b)
        assert result._ids is not None
        assert _row_ids(result, 0) == ["left", "left", "right", "right"]

    def test_join_horizontal_with_ids_matrix(self):
        """join_horizontal() propagates _ids matrices."""
        a = _text_block_with_ids(["ab"], ids=[["a1", "a2"]])
        b = _text_block_with_ids(["cd"], ids=[["b1", "b2"]])
        result = join_horizontal(a, b)
        assert result._ids is not None
        assert _row_ids(result, 0) == ["a1", "a2", "b1", "b2"]

    def test_join_horizontal_mixed_id_and_no_id(self):
        """When one block has id and another has neither, None fills in."""
        a = _text_block(["ab"], id="left")
        b = _text_block(["cd"])  # no id
        result = join_horizontal(a, b)
        assert result._ids is not None
        assert _row_ids(result, 0) == ["left", "left", None, None]

    def test_join_horizontal_gap_with_ids(self):
        """Gap cells get None ids."""
        a = _text_block(["a"], id="L")
        b = _text_block(["b"], id="R")
        result = join_horizontal(a, b, gap=2)
        assert result.width == 4
        assert _row_ids(result, 0) == ["L", None, None, "R"]

    def test_join_horizontal_different_heights_with_ids(self):
        """Taller alignment produces None ids in padding rows."""
        a = _text_block(["a", "a"], id="tall")
        b = _text_block(["b"], id="short")
        result = join_horizontal(a, b, align=Align.START)
        assert result.height == 2
        assert result._ids is not None
        # Row 0: tall block + short block
        assert _row_ids(result, 0) == ["tall", "short"]
        # Row 1: tall block + padding (None)
        assert _row_ids(result, 1) == ["tall", None]

    def test_join_horizontal_align_end(self):
        """END alignment shifts shorter block to bottom."""
        a = _text_block(["aa"])
        b = _text_block(["bb", "cc"])
        result = join_horizontal(a, b, align=Align.END)
        assert result.height == 2
        # Row 0: 'a' block padded (offset=1), 'b' content
        assert _row_text(result, 0) == "  bb"
        # Row 1: 'a' content, 'c' content
        assert _row_text(result, 1) == "aacc"

    def test_join_horizontal_align_center(self):
        """CENTER alignment centers shorter blocks."""
        a = _text_block(["x"])
        b = _text_block(["1", "2", "3"])
        result = join_horizontal(a, b, align=Align.CENTER)
        assert result.height == 3
        # 'x' has height 1, container height 3, offset = (3-1)//2 = 1
        assert _row_text(result, 0) == " 1"
        assert _row_text(result, 1) == "x2"
        assert _row_text(result, 2) == " 3"


# ---------------------------------------------------------------------------
# join_vertical() with id propagation
# ---------------------------------------------------------------------------


class TestJoinVerticalIds:
    def test_join_vertical_empty(self):
        """join_vertical() with no blocks returns empty."""
        result = join_vertical()
        assert result.width == 0
        assert result.height == 0

    def test_join_vertical_with_block_ids(self):
        """join_vertical() propagates block.id values."""
        a = _text_block(["ab"], id="top")
        b = _text_block(["cd"], id="bot")
        result = join_vertical(a, b)
        assert result._ids is not None
        assert _row_ids(result, 0) == ["top", "top"]
        assert _row_ids(result, 1) == ["bot", "bot"]

    def test_join_vertical_with_ids_matrix(self):
        """join_vertical() propagates _ids matrices."""
        a = _text_block_with_ids(["ab"], ids=[["a1", "a2"]])
        b = _text_block_with_ids(["cd"], ids=[["b1", "b2"]])
        result = join_vertical(a, b)
        assert result._ids is not None
        assert _row_ids(result, 0) == ["a1", "a2"]
        assert _row_ids(result, 1) == ["b1", "b2"]

    def test_join_vertical_mixed_id_and_no_id(self):
        """When one block has id and another doesn't, None fills in."""
        a = _text_block(["ab"], id="top")
        b = _text_block(["cd"])  # no id
        result = join_vertical(a, b)
        assert result._ids is not None
        assert _row_ids(result, 0) == ["top", "top"]
        assert _row_ids(result, 1) == [None, None]

    def test_join_vertical_gap_with_ids(self):
        """Gap rows get None ids."""
        a = _text_block(["a"], id="top")
        b = _text_block(["b"], id="bot")
        result = join_vertical(a, b, gap=1)
        assert result.height == 3
        assert _row_ids(result, 0) == ["top"]
        assert _row_ids(result, 1) == [None]
        assert _row_ids(result, 2) == ["bot"]

    def test_join_vertical_different_widths_with_ids(self):
        """Narrower blocks get None-padded ids."""
        a = _text_block(["ab"], id="narrow")
        b = _text_block(["cdef"], id="wide")
        result = join_vertical(a, b)
        assert result.width == 4
        assert result._ids is not None
        # Row 0: narrow + right padding
        assert _row_ids(result, 0) == ["narrow", "narrow", None, None]
        assert _row_ids(result, 1) == ["wide", "wide", "wide", "wide"]

    def test_join_vertical_align_end_with_ids(self):
        """END alignment right-aligns narrower blocks, ids padded left."""
        a = _text_block(["ab"], id="r")
        b = _text_block(["cdef"], id="w")
        result = join_vertical(a, b, align=Align.END)
        assert result.width == 4
        # "ab" right-aligned: offset = 4 - 2 = 2
        assert _row_text(result, 0) == "  ab"
        assert _row_ids(result, 0) == [None, None, "r", "r"]

    def test_join_vertical_align_center_with_ids(self):
        """CENTER alignment centers narrower blocks, ids padded."""
        a = _text_block(["ab"], id="c")
        b = _text_block(["cdef"], id="w")
        result = join_vertical(a, b, align=Align.CENTER)
        # offset = (4-2)//2 = 1
        assert _row_text(result, 0) == " ab "
        assert _row_ids(result, 0) == [None, "c", "c", None]


# ---------------------------------------------------------------------------
# join_responsive edge cases
# ---------------------------------------------------------------------------


class TestJoinResponsiveExtended:
    def test_single_block_wider_than_available(self):
        """Single block wider than available still returns it (no truncation)."""
        a = _text_block(["abcdef"])
        result = join_responsive(a, available_width=3)
        assert result.width == 6
        assert result.height == 1

    def test_three_blocks_fit(self):
        """Three blocks fitting horizontally."""
        a = _text_block(["a"])
        b = _text_block(["b"])
        c = _text_block(["c"])
        result = join_responsive(a, b, c, available_width=5, gap=1)
        # 1+1+1+1+1 = 5, fits
        assert result.height == 1
        assert _row_text(result, 0) == "a b c"

    def test_three_blocks_overflow(self):
        """Three blocks overflowing go vertical."""
        a = _text_block(["aa"])
        b = _text_block(["bb"])
        c = _text_block(["cc"])
        result = join_responsive(a, b, c, available_width=5, gap=1)
        # 2+1+2+1+2 = 8 > 5, goes vertical
        # 3 blocks with gap=1 between: 1 + 1(gap) + 1 + 1(gap) + 1 = 5
        assert result.height == 5


# ---------------------------------------------------------------------------
# border() title edge cases
# ---------------------------------------------------------------------------


class TestBorderTitle:
    def test_border_with_title(self):
        """border() renders title in top row."""
        b = _text_block(["abcdefgh"])
        result = border(b, title="Hi")
        top = _row_text(result, 0)
        assert "Hi" in top

    def test_border_title_too_wide_skipped(self):
        """border() skips title if block too narrow."""
        b = _text_block(["ab"])
        # Title "Hello" needs width + 3 = 8, block width is only 2
        result = border(b, title="Hello")
        top = _row_text(result, 0)
        # Title should not appear
        assert "Hello" not in top

    def test_border_custom_chars(self):
        """border() uses custom chars."""
        b = _text_block(["ab"])
        result = border(b, chars=HEAVY)
        assert result.width == 4
        assert result.height == 3

    def test_border_title_with_combining_char(self):
        """Zero-width combining chars in title are skipped (line 206)."""
        # U+0301 is a combining acute accent (zero-width).
        # Title "a\u0301b" has display_width 2 ("a" + combining + "b").
        # Block must be wide enough: need title_width(2) + 3 = 5.
        b = _text_block(["abcde"])
        result = border(b, title="a\u0301b")
        top = _row_text(result, 0)
        # The combining char is skipped, so "a" and "b" appear but not the accent.
        assert "a" in top
        assert "b" in top

    def test_border_title_exact_fit(self):
        """Title that exactly fits the available space."""
        # block.width=6, title "abc" (display_width=3), guard: 6 >= 3+3=6. Yes.
        # Painting: pos=2, space->3, a->4, b->5, c->6. Trailing space: 6<=6->yes.
        b = _text_block(["abcdef"])
        result = border(b, title="abc")
        top = _row_text(result, 0)
        assert "a" in top
        assert "b" in top
        assert "c" in top


# ---------------------------------------------------------------------------
# Alignment helpers (exercised via join functions)
# ---------------------------------------------------------------------------


class TestAlignment:
    def test_valign_center_via_join_horizontal(self):
        """CENTER vertical alignment offsets shorter blocks."""
        a = _text_block(["x"])
        b = _text_block(["1", "2", "3", "4", "5"])
        result = join_horizontal(a, b, align=Align.CENTER)
        assert result.height == 5
        # 'x' offset = (5-1)//2 = 2
        assert _row_text(result, 2) == "x3"

    def test_valign_end_via_join_horizontal(self):
        """END vertical alignment pushes shorter block to bottom."""
        a = _text_block(["x"])
        b = _text_block(["1", "2", "3"])
        result = join_horizontal(a, b, align=Align.END)
        assert result.height == 3
        # 'x' at row 2 (offset = 3-1 = 2)
        assert _row_text(result, 0) == " 1"
        assert _row_text(result, 1) == " 2"
        assert _row_text(result, 2) == "x3"

    def test_halign_center_via_join_vertical(self):
        """CENTER horizontal alignment centers narrower blocks."""
        a = _text_block(["ab"])
        b = _text_block(["123456"])
        result = join_vertical(a, b, align=Align.CENTER)
        assert result.width == 6
        # 'ab' offset = (6-2)//2 = 2
        assert _row_text(result, 0) == "  ab  "

    def test_halign_end_via_join_vertical(self):
        """END horizontal alignment right-aligns blocks."""
        a = _text_block(["ab"])
        b = _text_block(["cdef"])
        result = join_vertical(a, b, align=Align.END)
        assert result.width == 4
        # 'ab' offset = 4-2 = 2
        assert _row_text(result, 0) == "  ab"
        assert _row_text(result, 1) == "cdef"
