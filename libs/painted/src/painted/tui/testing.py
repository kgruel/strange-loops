"""Deterministic, non-TTY Surface test harness.

This module provides a small runner that exercises a Surface's render loop
without touching the real terminal (no alt screen, no cbreak/raw mode, no
signals). It is intended for pytest/CI usage.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TextIO

from .._mouse import MouseEvent
from ..app import Surface
from ..buffer import Buffer, CellWrite
from ..writer import ColorDepth, Writer

InputItem = str | MouseEvent


def buffer_to_lines(buf: Buffer) -> list[str]:
    """Return the buffer as a list of text lines (characters only)."""
    return ["".join(buf.get(x, y).char for x in range(buf.width)) for y in range(buf.height)]


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """A captured render result from a single flush."""

    buffer: Buffer
    writes: tuple[CellWrite, ...]

    @property
    def lines(self) -> list[str]:
        return buffer_to_lines(self.buffer)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class TestSurface:
    """Deterministic Surface runner for tests.

    Example:
        app = MySurface()
        harness = TestSurface(app, width=20, height=5, input_queue=["j", "q"])
        frames = harness.run_to_completion()
        assert "hello" in frames[0].text
    """

    # Prevent pytest from trying to collect this as a test case when imported.
    __test__ = False

    def __init__(
        self,
        surface: Surface,
        *,
        width: int,
        height: int,
        color_depth: ColorDepth = ColorDepth.BASIC,
        input_queue: Iterable[InputItem] = (),
        stream: TextIO | None = None,
        write_ansi: bool = False,
    ):
        self.surface = surface
        self.width = width
        self.height = height
        self.input_queue = list(input_queue)
        self.stream = stream if stream is not None else io.StringIO()
        self.write_ansi = write_ansi
        self.emissions: list[tuple[str, dict]] = []

        original_emit = self.surface._on_emit

        def _capture_emit(kind: str, data: dict) -> None:
            self.emissions.append((kind, data))
            if original_emit is not None:
                original_emit(kind, data)

        self.surface._on_emit = _capture_emit

        # Ensure the Surface has deterministic dimensions and no TTY dependency.
        self.surface._writer = Writer(self.stream, color_depth=color_depth)
        self.surface._buf = Buffer(width, height)
        self.surface._prev = Buffer(width, height)
        self.surface.layout(width, height)

    def run_to_completion(self) -> list[CapturedFrame]:
        """Run initial render + each queued input, capturing frames after flushes."""
        self.surface._running = True
        self.surface._dirty = True

        frames: list[CapturedFrame] = []

        # Initial frame (matches production loop: update() then render if dirty).
        self.surface.update()
        self._render_and_capture(frames)

        for item in self.input_queue:
            if not self.surface._running:
                break

            if isinstance(item, MouseEvent):
                self.surface.on_mouse(item)
                self.surface.emit(
                    "ui.mouse",
                    action=item.action.name,
                    button=item.button.name,
                    x=item.x,
                    y=item.y,
                    shift=item.shift,
                    meta=item.meta,
                    ctrl=item.ctrl,
                )
            else:
                self.surface.on_key(item)
                self.surface.emit("ui.key", key=item)

            # Production loop always renders after any input.
            self.surface._dirty = True

            self.surface.update()
            self._render_and_capture(frames)

        return frames

    def resize(self, width: int, height: int) -> None:
        """Simulate a terminal resize (SIGWINCH) for the harness dimensions."""
        self.width = width
        self.height = height
        self.surface._resize(width, height)

    def _render_and_capture(self, frames: list[CapturedFrame]) -> None:
        if not self.surface._dirty:
            return
        self.surface._dirty = False
        self.surface.render()

        buf = self.surface._buf
        prev = self.surface._prev
        if buf is None or prev is None:
            return

        needs_clear = getattr(self.surface, "_needs_clear", False)
        self.surface._needs_clear = False

        writes = buf.diff(prev)
        if self.write_ansi and (writes or needs_clear):
            self.surface._writer.write_frame(writes, clear_first=needs_clear)

        # Swap: current becomes previous for next frame.
        self.surface._prev = buf.clone()

        frames.append(CapturedFrame(buffer=buf.clone(), writes=tuple(writes)))
