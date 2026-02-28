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


class TestWriterClearScreen:
    def test_clear_screen_emits_ed2(self):
        stream = io.StringIO()
        w = Writer(stream, color_depth=ColorDepth.BASIC)
        w.clear_screen()
        assert stream.getvalue() == "\x1b[2J"


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


class TestResizeHandling:
    """End-to-end resize behavior via TestSurface harness."""

    def test_resize_produces_correct_dimensions(self):
        """Buffer dimensions match new terminal size after resize."""
        app = FillSurface()
        harness = TestSurface(app, width=80, height=24)

        harness.resize(60, 20)
        assert app._buf.width == 60
        assert app._buf.height == 20
        assert harness.width == 60
        assert harness.height == 20

    def test_no_stale_content_after_resize(self):
        """Every cell in the post-resize buffer is the expected content.

        Renders 'A' at 6x3, resizes to 4x2 with 'B', verifies no 'A' remains.
        """
        app = FillSurface(ch="A")
        harness = TestSurface(app, width=6, height=3)
        frames = harness.run_to_completion()

        # Pre-resize: every cell is 'A'.
        pre = frames[0]
        assert all(ch == "A" for line in pre.lines for ch in line)

        # Resize and render with 'B'.
        app.ch = "B"
        harness.resize(4, 2)
        post_frames: list = []
        harness.surface.update()
        harness._render_and_capture(post_frames)

        post = post_frames[0]
        assert post.buffer.width == 4
        assert post.buffer.height == 2
        # Every cell must be 'B' -- no 'A' from the old frame.
        for y, line in enumerate(post.lines):
            for x, ch in enumerate(line):
                assert ch == "B", f"Stale content at ({x}, {y}): got {ch!r}, expected 'B'"

    def test_ansi_clear_sequence_on_resize_frame(self):
        """ANSI clear screen sequence appears in output on resize frame."""
        app = FillSurface()
        stream = io.StringIO()
        harness = TestSurface(
            app, width=10, height=5, stream=stream, write_ansi=True, color_depth=ColorDepth.BASIC
        )
        harness.run_to_completion()

        # Normal frame: no clear.
        assert _clear() not in stream.getvalue()

        before = len(stream.getvalue())
        harness.resize(8, 4)
        post_frames: list = []
        harness.surface.update()
        harness._render_and_capture(post_frames)
        resize_output = stream.getvalue()[before:]

        assert _clear() in resize_output

    def test_post_resize_diff_covers_all_cells(self):
        """Post-resize diff produces a write for every cell (full repaint)."""
        app = FillSurface(ch="Z")
        harness = TestSurface(app, width=5, height=3)
        harness.run_to_completion()

        harness.resize(4, 2)
        post_frames: list = []
        harness.surface.update()
        harness._render_and_capture(post_frames)

        frame = post_frames[0]
        total_cells = 4 * 2
        assert len(frame.writes) == total_cells, (
            f"Expected {total_cells} writes (full repaint), got {len(frame.writes)}"
        )

    def test_multiple_rapid_resizes_correct_final_state(self):
        """Multiple resizes between renders produce correct final dimensions and content."""
        app = FillSurface(ch="R")
        harness = TestSurface(app, width=20, height=10)
        harness.run_to_completion()

        # Fire three resizes without rendering in between.
        harness.resize(15, 8)
        harness.resize(10, 5)
        harness.resize(6, 3)

        post_frames: list = []
        harness.surface.update()
        harness._render_and_capture(post_frames)

        frame = post_frames[0]
        assert frame.buffer.width == 6
        assert frame.buffer.height == 3
        for line in frame.lines:
            assert all(ch == "R" for ch in line)

    def test_buffer_diff_dimension_mismatch_full_repaint(self):
        """Buffer.diff() with dimension mismatch returns writes for all cells."""
        a = Buffer(5, 2)
        for x in range(5):
            for y in range(2):
                a.put(x, y, "X", Style())

        b = Buffer(3, 3)

        writes = a.diff(b)
        assert len(writes) == 10  # 5 * 2 = all cells in `a`
        coords = {(w.x, w.y) for w in writes}
        expected = {(x, y) for x in range(5) for y in range(2)}
        assert coords == expected


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
