"""Resize handling tests: terminal clear + diff robustness."""

from __future__ import annotations

import io

from painted import Style
from painted.buffer import Buffer, CellWrite
from painted.cell import Cell
from painted.tui import Surface, TestSurface
from painted.writer import ColorDepth, Writer


class FillSurface(Surface):
    def __init__(self, *, ch: str = "X", on_emit=None):
        super().__init__(on_emit=on_emit, scroll_optimization=False)
        self.ch = ch
        self.layout_calls: list[tuple[int, int]] = []

    def layout(self, width: int, height: int) -> None:
        self.layout_calls.append((width, height))

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, self.ch, Style())


class NoopRenderSurface(Surface):
    def __init__(self):
        super().__init__(scroll_optimization=False)

    def render(self) -> None:
        # Intentionally render nothing (buffer remains EMPTY_CELL everywhere).
        return


def _sync_begin() -> str:
    return "\x1b[?2026h"


def _sync_end() -> str:
    return "\x1b[?2026l"


def _clear() -> str:
    return "\x1b[2J"


class TestBufferDiffDimensionMismatch:
    def test_dimension_mismatch_full_repaint_and_coordinates(self):
        buf = Buffer(4, 1)
        for x, ch in enumerate("ABCD"):
            buf.put(x, 0, ch, Style())

        # Same total cell count but different dimensions.
        other = Buffer(2, 2)
        writes = buf.diff(other)

        assert len(writes) == 4
        assert [(w.x, w.y, w.cell.char) for w in writes] == [
            (0, 0, "A"),
            (1, 0, "B"),
            (2, 0, "C"),
            (3, 0, "D"),
        ]

    def test_normal_diff_still_works(self):
        a = Buffer(3, 2)
        b = Buffer(3, 2)
        a.put(2, 1, "Z", Style())
        writes = a.diff(b)
        assert writes == [CellWrite(2, 1, Cell("Z", Style()))]


class TestWriterClearFirst:
    def test_write_frame_clear_first_with_no_writes(self):
        stream = io.StringIO()
        w = Writer(stream, color_depth=ColorDepth.BASIC)
        w.write_frame([], clear_first=True)
        out = stream.getvalue()

        assert out.startswith(_sync_begin() + _clear())
        assert _sync_end() in out

    def test_write_frame_clear_first_is_inside_sync_block(self):
        stream = io.StringIO()
        w = Writer(stream, color_depth=ColorDepth.BASIC)
        writes = [CellWrite(0, 0, Cell("A", Style()))]
        w.write_frame(writes, clear_first=True)
        out = stream.getvalue()

        start = out.index(_sync_begin())
        clear = out.index(_clear())
        end = out.index(_sync_end())
        assert start < clear < end
        assert clear == start + len(_sync_begin())


class TestSurfaceNeedsClear:
    def test_needs_clear_set_on_resize_and_consumed_on_flush(self):
        stream = io.StringIO()
        surface = FillSurface()
        surface._writer = Writer(stream, color_depth=ColorDepth.BASIC)

        surface._buf = Buffer(3, 2)
        surface._prev = Buffer(3, 2)
        surface.layout(3, 2)

        surface._resize(5, 1)
        assert surface._needs_clear is True

        surface.render()
        surface._flush()
        assert surface._needs_clear is False
        assert _clear() in stream.getvalue()

    def test_clear_frame_emitted_even_when_no_cell_writes(self):
        stream = io.StringIO()
        surface = NoopRenderSurface()
        surface._writer = Writer(stream, color_depth=ColorDepth.BASIC)

        surface._buf = Buffer(2, 1)
        surface._prev = Buffer(2, 1)
        surface.layout(2, 1)

        surface._resize(2, 1)
        surface.render()
        surface._flush()

        out = stream.getvalue()
        assert out.startswith(_sync_begin() + _clear())

    def test_multiple_rapid_resizes_last_wins_single_clear(self):
        stream = io.StringIO()
        surface = FillSurface()
        surface._writer = Writer(stream, color_depth=ColorDepth.BASIC)

        surface._buf = Buffer(2, 1)
        surface._prev = Buffer(2, 1)
        surface.layout(2, 1)

        surface._resize(10, 3)
        surface._resize(7, 2)
        assert surface._buf.width == 7
        assert surface._buf.height == 2

        surface.render()
        surface._flush()

        out = stream.getvalue()
        assert out.count(_clear()) == 1


class TestHarnessResizeIntegration:
    def test_test_surface_resize_updates_dimensions_layout_and_emits(self):
        app = FillSurface()
        harness = TestSurface(app, width=4, height=2)

        harness.resize(6, 3)
        assert harness.width == 6
        assert harness.height == 3
        assert app._buf.width == 6
        assert app._buf.height == 3
        assert app.layout_calls[-1] == (6, 3)
        assert harness.emissions[-1] == ("ui.resize", {"width": 6, "height": 3})

    def test_resize_frame_emits_clear_and_normal_frames_do_not(self):
        app = FillSurface()
        stream = io.StringIO()
        harness = TestSurface(
            app,
            width=4,
            height=2,
            stream=stream,
            write_ansi=True,
            color_depth=ColorDepth.BASIC,
        )

        harness.run_to_completion()
        initial_out = stream.getvalue()
        assert _sync_begin() in initial_out
        assert _clear() not in initial_out

        harness.resize(5, 2)

        frames: list = []
        before = len(stream.getvalue())
        harness.surface.update()
        harness._render_and_capture(frames)
        after_resize = stream.getvalue()[before:]

        assert _clear() in after_resize
        start = after_resize.index(_sync_begin())
        clear = after_resize.index(_clear())
        end = after_resize.index(_sync_end())
        assert start < clear < end

        # Next frame should not clear again.
        app.ch = "Y"
        harness.surface._dirty = True
        before = len(stream.getvalue())
        harness.surface.update()
        harness._render_and_capture(frames)
        next_frame = stream.getvalue()[before:]
        assert _clear() not in next_frame
