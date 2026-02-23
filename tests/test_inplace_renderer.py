import io

import pytest

from fidelis import Block, Cell, Style
from fidelis.inplace import InPlaceRenderer


def _block(rows: list[list[Cell]]) -> Block:
    width = len(rows[0]) if rows else 0
    return Block(rows, width)


class TestInPlaceRenderer:
    def test_render_writes_ansi_sequences(self):
        stream = io.StringIO()
        red = Style(fg="red")
        default = Style()
        block = _block([[Cell("A", red), Cell("B", red), Cell("C", default)]])

        with InPlaceRenderer(stream) as renderer:
            renderer.render(block)
            renderer.finalize()

        out = stream.getvalue()
        assert "\x1b[?25l" in out  # hide cursor on enter
        assert "\x1b[?25h" in out  # show cursor on finalize
        assert "\x1b[0m\x1b[31mAB\x1b[0mC\x1b[0m\n" in out

    def test_render_second_call_moves_up_and_clears(self):
        stream = io.StringIO()
        s = Style()
        block1 = _block([[Cell("A", s)], [Cell("B", s)]])  # height 2
        block2 = _block([[Cell("C", s)], [Cell("D", s)]])  # height 2

        with InPlaceRenderer(stream) as renderer:
            renderer.render(block1)
            renderer.render(block2)
            renderer.finalize()

        out = stream.getvalue()
        first_frame = "\x1b[0mA\x1b[0m\n\x1b[0mB\x1b[0m\n"
        second_frame = "\x1b[0mC\x1b[0m\n\x1b[0mD\x1b[0m\n"
        clear_seq = "\x1b[2A\x1b[2K\n\x1b[2K\n\x1b[2A"

        assert first_frame in out
        assert second_frame in out
        assert clear_seq in out
        assert out.index(first_frame) < out.index(clear_seq) < out.index(second_frame)

    def test_render_outside_context_raises(self):
        stream = io.StringIO()
        block = Block.text("hi", Style())
        renderer = InPlaceRenderer(stream)

        with pytest.raises(RuntimeError, match="outside of a context manager"):
            renderer.render(block)

    def test_finalize_shows_cursor_and_deactivates(self):
        stream = io.StringIO()
        block = Block.text("ok", Style())

        with InPlaceRenderer(stream) as renderer:
            renderer.render(block)
            renderer.finalize()
            assert renderer._active is False

        out = stream.getvalue()
        assert "\x1b[?25h" in out

    def test_exit_after_finalize_does_not_double_show_cursor(self):
        stream = io.StringIO()

        with InPlaceRenderer(stream) as renderer:
            renderer.finalize()

        out = stream.getvalue()
        assert out.count("\x1b[?25h") == 1

    def test_clear_clears_content_and_resets_height(self):
        stream = io.StringIO()
        s = Style()
        block2 = _block([[Cell("A", s)], [Cell("B", s)]])  # height 2
        block1 = _block([[Cell("C", s)]])  # height 1
        clear_seq = "\x1b[2A\x1b[2K\n\x1b[2K\n\x1b[2A"

        with InPlaceRenderer(stream) as renderer:
            renderer.render(block2)
            renderer.clear()
            assert renderer._height == 0
            renderer.render(block1)
            renderer.finalize()

        out = stream.getvalue()
        assert out.count(clear_seq) == 1

    def test_height_tracking_across_different_sized_blocks(self):
        stream = io.StringIO()
        s = Style()
        block3 = _block([[Cell("A", s)], [Cell("B", s)], [Cell("C", s)]])  # height 3
        block1 = _block([[Cell("D", s)]])  # height 1
        clear_seq = "\x1b[3A\x1b[2K\n\x1b[2K\n\x1b[2K\n\x1b[3A"

        with InPlaceRenderer(stream) as renderer:
            renderer.render(block3)
            assert renderer._height == 3
            renderer.render(block1)
            assert renderer._height == 1
            renderer.finalize()

        assert clear_seq in stream.getvalue()

    def test_clear_outside_context_raises(self):
        stream = io.StringIO()
        renderer = InPlaceRenderer(stream)

        with pytest.raises(RuntimeError, match="outside of a context manager"):
            renderer.clear()

