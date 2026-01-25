"""Tests for cells.span: Span and Line primitives."""

from cells import Buffer, Style, Line, Span


class TestSpanWidth:
    def test_ascii(self):
        assert Span("hello").width == 5

    def test_empty(self):
        assert Span("").width == 0

    def test_wide_chars(self):
        # CJK characters are 2 columns wide
        assert Span("\u4e16\u754c").width == 4  # "世界"

    def test_mixed_ascii_and_wide(self):
        assert Span("A\u4e16B").width == 4  # 1 + 2 + 1


class TestLineWidth:
    def test_empty(self):
        assert Line().width == 0

    def test_single_span(self):
        line = Line(spans=(Span("hello"),))
        assert line.width == 5

    def test_multiple_spans(self):
        line = Line(spans=(Span("ab"), Span("cde")))
        assert line.width == 5

    def test_wide_chars(self):
        line = Line(spans=(Span("A"), Span("\u4e16\u754c")))
        assert line.width == 5  # 1 + 4


class TestLineTruncate:
    def test_no_truncation_needed(self):
        line = Line(spans=(Span("abc"),))
        result = line.truncate(10)
        assert result.width == 3

    def test_truncate_single_span(self):
        line = Line(spans=(Span("hello"),))
        result = line.truncate(3)
        assert result.width == 3
        assert result.spans[0].text == "hel"

    def test_truncate_across_spans(self):
        line = Line(spans=(Span("ab"), Span("cde")))
        result = line.truncate(4)
        assert result.width == 4
        assert len(result.spans) == 2
        assert result.spans[0].text == "ab"
        assert result.spans[1].text == "cd"

    def test_truncate_preserves_style(self):
        base = Style(fg="red")
        span_style = Style(bold=True)
        line = Line(spans=(Span("hello", span_style),), style=base)
        result = line.truncate(3)
        assert result.style == base
        assert result.spans[0].style == span_style

    def test_truncate_wide_char_boundary(self):
        # Wide char at boundary shouldn't be included if it doesn't fit
        line = Line(spans=(Span("A\u4e16B"),))  # widths: 1, 2, 1 = 4
        result = line.truncate(2)
        # Only 'A' fits (width 1), '\u4e16' needs 2 more but budget is only 1
        assert result.width == 1
        assert result.spans[0].text == "A"

    def test_truncate_to_zero(self):
        line = Line(spans=(Span("hello"),))
        result = line.truncate(0)
        assert result.width == 0
        assert result.spans == ()


class TestLinePaint:
    def test_paint_single_span(self):
        buf = Buffer(10, 1)
        view = buf.region(0, 0, 10, 1)
        line = Line(spans=(Span("hi"),))
        line.paint(view, 0, 0)
        assert buf.get(0, 0).char == "h"
        assert buf.get(1, 0).char == "i"
        assert buf.get(2, 0).char == " "  # untouched

    def test_paint_with_offset(self):
        buf = Buffer(10, 1)
        view = buf.region(0, 0, 10, 1)
        line = Line(spans=(Span("ab"),))
        line.paint(view, 3, 0)
        assert buf.get(2, 0).char == " "
        assert buf.get(3, 0).char == "a"
        assert buf.get(4, 0).char == "b"

    def test_paint_multiple_spans(self):
        buf = Buffer(10, 1)
        view = buf.region(0, 0, 10, 1)
        line = Line(spans=(Span("ab"), Span("cd")))
        line.paint(view, 0, 0)
        assert buf.get(0, 0).char == "a"
        assert buf.get(1, 0).char == "b"
        assert buf.get(2, 0).char == "c"
        assert buf.get(3, 0).char == "d"


class TestStyleInheritance:
    def test_line_style_merges_onto_span(self):
        base = Style(fg="red")
        span_style = Style(bold=True)
        buf = Buffer(10, 1)
        view = buf.region(0, 0, 10, 1)
        line = Line(spans=(Span("x", span_style),), style=base)
        line.paint(view, 0, 0)
        cell = buf.get(0, 0)
        # Merged: fg from base, bold from span
        assert cell.style.fg == "red"
        assert cell.style.bold is True

    def test_span_style_overrides_line_style(self):
        base = Style(fg="red")
        span_style = Style(fg="blue")
        buf = Buffer(10, 1)
        view = buf.region(0, 0, 10, 1)
        line = Line(spans=(Span("x", span_style),), style=base)
        line.paint(view, 0, 0)
        cell = buf.get(0, 0)
        # Span fg overrides line fg
        assert cell.style.fg == "blue"

    def test_default_span_inherits_line_style(self):
        base = Style(fg="green", bold=True)
        buf = Buffer(10, 1)
        view = buf.region(0, 0, 10, 1)
        line = Line(spans=(Span("y"),), style=base)
        line.paint(view, 0, 0)
        cell = buf.get(0, 0)
        assert cell.style.fg == "green"
        assert cell.style.bold is True
