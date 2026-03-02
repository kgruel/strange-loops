"""Extended Writer tests: color depth detection, mouse, alt screen, scroll ops, styles, colors."""

from __future__ import annotations

import io
import re

import pytest

from painted.buffer import CellWrite
from painted.cell import Cell, Style
from painted.writer import ColorDepth, ScrollOp, Writer, print_block
from painted.block import Block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture(ops, color_depth: ColorDepth = ColorDepth.TRUECOLOR) -> str:
    buf = io.StringIO()
    w = Writer(buf, color_depth=color_depth)
    w.write_ops(ops)
    return buf.getvalue()


def _cell(ch: str, style: Style = Style()) -> Cell:
    return Cell(ch, style)


def _writer_with_buf(color_depth: ColorDepth = ColorDepth.TRUECOLOR) -> tuple[Writer, io.StringIO]:
    buf = io.StringIO()
    return Writer(buf, color_depth=color_depth), buf


# ---------------------------------------------------------------------------
# ColorDepth detection (lines 118-145)
# ---------------------------------------------------------------------------


class TestColorDepthDetection:
    def test_explicit_depth_returned_immediately(self):
        """When color_depth is set in constructor, detect returns it."""
        buf = io.StringIO()
        w = Writer(buf, color_depth=ColorDepth.EIGHT_BIT)
        assert w.detect_color_depth() == ColorDepth.EIGHT_BIT

    def test_non_tty_returns_none_depth(self):
        """Non-TTY stream gets ColorDepth.NONE."""
        buf = io.StringIO()  # not a TTY
        w = Writer(buf)
        assert w.detect_color_depth() == ColorDepth.NONE

    def test_non_tty_caches_result(self):
        """Second call returns cached value without re-detecting."""
        buf = io.StringIO()
        w = Writer(buf)
        first = w.detect_color_depth()
        second = w.detect_color_depth()
        assert first == second == ColorDepth.NONE

    def test_tty_truecolor_env(self, monkeypatch):
        """TTY with COLORTERM=truecolor -> TRUECOLOR."""

        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setenv("COLORTERM", "truecolor")
        w = Writer(FakeTTY())
        assert w.detect_color_depth() == ColorDepth.TRUECOLOR

    def test_tty_24bit_env(self, monkeypatch):
        """TTY with COLORTERM=24bit -> TRUECOLOR."""

        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setenv("COLORTERM", "24bit")
        w = Writer(FakeTTY())
        assert w.detect_color_depth() == ColorDepth.TRUECOLOR

    def test_tty_256color_term(self, monkeypatch):
        """TTY with TERM containing '256color' -> EIGHT_BIT."""

        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setenv("COLORTERM", "")
        monkeypatch.setenv("TERM", "xterm-256color")
        w = Writer(FakeTTY())
        assert w.detect_color_depth() == ColorDepth.EIGHT_BIT

    def test_tty_basic_term(self, monkeypatch):
        """TTY with TERM set but not 256color -> BASIC."""

        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setenv("COLORTERM", "")
        monkeypatch.setenv("TERM", "xterm")
        w = Writer(FakeTTY())
        assert w.detect_color_depth() == ColorDepth.BASIC

    def test_tty_no_term_env(self, monkeypatch):
        """TTY with no TERM env -> BASIC."""

        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setenv("COLORTERM", "")
        monkeypatch.delenv("TERM", raising=False)
        w = Writer(FakeTTY())
        assert w.detect_color_depth() == ColorDepth.BASIC


# ---------------------------------------------------------------------------
# Alt screen enter/exit (lines 306-311)
# ---------------------------------------------------------------------------


class TestAltScreen:
    def test_enter_alt_screen(self):
        w, buf = _writer_with_buf()
        w.enter_alt_screen()
        assert buf.getvalue() == "\x1b[?1049h"

    def test_exit_alt_screen(self):
        w, buf = _writer_with_buf()
        w.exit_alt_screen()
        assert buf.getvalue() == "\x1b[?1049l"


# ---------------------------------------------------------------------------
# Mouse enable/disable (lines 330-340)
# ---------------------------------------------------------------------------


class TestMouseTracking:
    def test_enable_mouse_button_events(self):
        """Default enable_mouse uses mode 1002 (button-event tracking)."""
        w, buf = _writer_with_buf()
        w.enable_mouse()
        output = buf.getvalue()
        assert "\x1b[?1002h" in output  # button-event tracking
        assert "\x1b[?1006h" in output  # SGR encoding

    def test_enable_mouse_all_motion(self):
        """all_motion=True uses mode 1003."""
        w, buf = _writer_with_buf()
        w.enable_mouse(all_motion=True)
        output = buf.getvalue()
        assert "\x1b[?1003h" in output  # any-event tracking
        assert "\x1b[?1006h" in output  # SGR encoding

    def test_disable_mouse(self):
        w, buf = _writer_with_buf()
        w.disable_mouse()
        output = buf.getvalue()
        assert "\x1b[?1002l" in output
        assert "\x1b[?1003l" in output
        assert "\x1b[?1006l" in output


# ---------------------------------------------------------------------------
# Style rendering (lines 152-160)
# ---------------------------------------------------------------------------


class TestApplyStyle:
    def test_empty_style_returns_empty(self):
        w, _ = _writer_with_buf()
        assert w.apply_style(Style()) == ""

    def test_bold(self):
        w, _ = _writer_with_buf()
        assert "\x1b[1m" == w.apply_style(Style(bold=True))

    def test_dim(self):
        w, _ = _writer_with_buf()
        assert "\x1b[2m" == w.apply_style(Style(dim=True))

    def test_italic(self):
        w, _ = _writer_with_buf()
        assert "\x1b[3m" == w.apply_style(Style(italic=True))

    def test_underline(self):
        w, _ = _writer_with_buf()
        assert "\x1b[4m" == w.apply_style(Style(underline=True))

    def test_reverse(self):
        w, _ = _writer_with_buf()
        assert "\x1b[7m" == w.apply_style(Style(reverse=True))

    def test_combined_attributes(self):
        w, _ = _writer_with_buf()
        result = w.apply_style(Style(bold=True, italic=True, underline=True))
        # codes should be 1, 3, 4 in order
        assert result == "\x1b[1;3;4m"

    def test_fg_named_color(self):
        w, _ = _writer_with_buf()
        result = w.apply_style(Style(fg="red"))
        # named red -> base 30 + 1 = 31
        assert "31" in result

    def test_bg_named_color(self):
        w, _ = _writer_with_buf()
        result = w.apply_style(Style(bg="blue"))
        # named blue -> base 40 + 4 = 44
        assert "44" in result

    def test_bold_and_fg(self):
        w, _ = _writer_with_buf()
        result = w.apply_style(Style(bold=True, fg="green"))
        assert result.startswith("\x1b[")
        assert "1" in result  # bold
        assert "32" in result  # green fg


# ---------------------------------------------------------------------------
# Color rendering: named, 256, hex RGB (lines 182-205)
# ---------------------------------------------------------------------------


class TestColorCodes:
    def test_256_color_fg_truecolor_depth(self):
        """256-color index emitted as 38;5;N at TRUECOLOR depth."""
        w, _ = _writer_with_buf(ColorDepth.TRUECOLOR)
        codes = w._color_codes(100, foreground=True)
        assert codes == ["38", "5", "100"]

    def test_256_color_bg_truecolor_depth(self):
        w, _ = _writer_with_buf(ColorDepth.TRUECOLOR)
        codes = w._color_codes(200, foreground=False)
        assert codes == ["48", "5", "200"]

    def test_256_color_downgrade_to_basic(self):
        """256-color index downgrades to basic 16 at BASIC depth."""
        w, _ = _writer_with_buf(ColorDepth.BASIC)
        codes = w._color_codes(100, foreground=True)
        # Should be a single code in the 30-47 range
        assert len(codes) == 1
        code = int(codes[0])
        assert 30 <= code <= 47

    def test_hex_rgb_truecolor(self):
        """Hex RGB emits 38;2;r;g;b at TRUECOLOR depth."""
        w, _ = _writer_with_buf(ColorDepth.TRUECOLOR)
        codes = w._color_codes("#ff8040", foreground=True)
        assert codes == ["38", "2", "255", "128", "64"]

    def test_hex_rgb_bg_truecolor(self):
        w, _ = _writer_with_buf(ColorDepth.TRUECOLOR)
        codes = w._color_codes("#ff8040", foreground=False)
        assert codes == ["48", "2", "255", "128", "64"]

    def test_hex_rgb_downgrade_to_256(self):
        """Hex RGB downgrades to 256-color at EIGHT_BIT depth."""
        w, _ = _writer_with_buf(ColorDepth.EIGHT_BIT)
        codes = w._color_codes("#ff0000", foreground=True)
        assert codes[0] == "38"
        assert codes[1] == "5"
        # Should be a valid 256-color index
        idx = int(codes[2])
        assert 0 <= idx <= 255

    def test_hex_rgb_downgrade_to_basic(self):
        """Hex RGB downgrades to basic 16 at BASIC depth."""
        w, _ = _writer_with_buf(ColorDepth.BASIC)
        codes = w._color_codes("#ff0000", foreground=True)
        assert len(codes) == 1
        code = int(codes[0])
        assert 30 <= code <= 47

    def test_named_color_fg(self):
        w, _ = _writer_with_buf(ColorDepth.TRUECOLOR)
        codes = w._color_codes("red", foreground=True)
        assert codes == ["31"]  # 30 + 1

    def test_named_color_bg(self):
        w, _ = _writer_with_buf(ColorDepth.TRUECOLOR)
        codes = w._color_codes("cyan", foreground=False)
        assert codes == ["46"]  # 40 + 6

    def test_unknown_color_returns_empty(self):
        """Unknown color string returns empty list (line 205)."""
        w, _ = _writer_with_buf(ColorDepth.TRUECOLOR)
        codes = w._color_codes("not_a_color", foreground=True)
        assert codes == []


# ---------------------------------------------------------------------------
# write_ops with ScrollOp (lines 234, 247, 272)
# ---------------------------------------------------------------------------


class TestWriteOpsScroll:
    def test_empty_ops_no_output(self):
        """Empty ops list produces no output (line 234)."""
        buf = io.StringIO()
        w = Writer(buf, color_depth=ColorDepth.TRUECOLOR)
        w.write_ops([])
        assert buf.getvalue() == ""

    def test_scroll_up_positive_n(self):
        """ScrollOp with positive n scrolls up."""
        output = _capture([ScrollOp(top=2, bottom=10, n=3)])
        # Should contain: set scroll region, move to bottom, scroll up, reset region
        assert "\x1b[3;11r" in output  # set_scroll_region(2, 10) -> 3;11r
        assert "\x1b[11;1H" in output  # move_cursor(0, 10) -> row 11, col 1
        assert "\x1b[3S" in output  # scroll_up(3)
        assert "\x1b[r" in output  # reset_scroll_region

    def test_scroll_down_negative_n(self):
        """ScrollOp with negative n scrolls down."""
        output = _capture([ScrollOp(top=2, bottom=10, n=-3)])
        assert "\x1b[3;11r" in output  # set_scroll_region(2, 10)
        assert "\x1b[3;1H" in output  # move_cursor(0, 2) -> row 3, col 1
        assert "\x1b[3T" in output  # scroll_down(3)
        assert "\x1b[r" in output

    def test_scroll_op_with_zero_n_skipped(self):
        """ScrollOp with n=0 is skipped (line 247)."""
        output = _capture([ScrollOp(top=0, bottom=10, n=0)])
        # Only synced output markers, no scroll sequences
        assert "S" not in output.replace("\x1b[?2026h", "").replace("\x1b[?2026l", "").replace(
            "\x1b[0m", ""
        )

    def test_scroll_op_inverted_range_skipped(self):
        """ScrollOp where top > bottom is skipped (line 247)."""
        output = _capture([ScrollOp(top=10, bottom=5, n=1)])
        assert "S" not in output.replace("\x1b[?2026h", "").replace("\x1b[?2026l", "").replace(
            "\x1b[0m", ""
        )

    def test_covered_trailing_cell_of_wide_char_skipped(self):
        """Trailing cell of a wide character is skipped in output (line 272)."""
        ops = [
            CellWrite(0, 0, _cell("\uff21")),  # fullwidth A (width 2), occupies x=0,1
            CellWrite(1, 0, _cell(" ")),  # x=1 is covered by the wide char
        ]
        output = _capture(ops)
        # The space at x=1 should be skipped; only the wide char should appear
        # Count actual character output (not escape sequences)
        chars = re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", output)
        assert chars.count(" ") == 0  # the space was skipped


# ---------------------------------------------------------------------------
# Terminal size (line 118-119)
# ---------------------------------------------------------------------------


class TestWriterSize:
    def test_size_returns_tuple(self):
        """size() returns (columns, rows) tuple."""
        w, _ = _writer_with_buf()
        cols, rows = w.size()
        assert isinstance(cols, int)
        assert isinstance(rows, int)
        assert cols > 0
        assert rows > 0


# ---------------------------------------------------------------------------
# print_block plain text (lines 366-372)
# ---------------------------------------------------------------------------


class TestPrintBlock:
    def test_print_block_plain(self):
        """print_block with use_ansi=False outputs plain text."""
        block = Block.text("hello", Style())
        buf = io.StringIO()
        print_block(block, buf, use_ansi=False)
        output = buf.getvalue()
        assert "hello" in output
        # No escape sequences
        assert "\x1b" not in output

    def test_print_block_ansi(self):
        """print_block with use_ansi=True outputs ANSI sequences."""
        block = Block.text("hi", style=Style(bold=True))
        buf = io.StringIO()
        print_block(block, buf, use_ansi=True)
        output = buf.getvalue()
        assert "hi" in output
        assert "\x1b[" in output  # has escape sequences

    def test_print_block_auto_non_tty(self):
        """print_block auto-detects non-TTY -> plain text."""
        block = Block.text("test", Style())
        buf = io.StringIO()
        print_block(block, buf)  # use_ansi=None (auto)
        output = buf.getvalue()
        assert "\x1b" not in output
