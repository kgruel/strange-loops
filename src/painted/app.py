"""Surface — base class for buffer-rendered terminal applications."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from typing import Any

from ._mouse import MouseEvent
from .buffer import Buffer, CellWrite
from .keyboard import KeyboardInput
from .layer import Layer
from .layer import process_key as _process_key
from .writer import ScrollOp, Writer

Emit = Callable[[str, dict[str, Any]], None]
LifecycleHook = Callable[[], Awaitable[None]]


class Surface:
    """Base class for buffer-rendered applications.

    Subclasses override layout(), render(), and on_key() to build interactive
    terminal UIs using the cell-buffer rendering system.
    """

    def __init__(
        self,
        *,
        fps_cap: int = 60,
        enable_mouse: bool = False,
        mouse_all_motion: bool = False,
        scroll_optimization: bool | None = None,
        scroll_optimization_emit: bool = False,
        on_emit: Emit | None = None,
        on_start: LifecycleHook | None = None,
        on_stop: LifecycleHook | None = None,
    ):
        self._writer = Writer()
        self._fps_cap = fps_cap
        self._buf: Buffer | None = None
        self._prev: Buffer | None = None
        self._keyboard = KeyboardInput()
        self._running = False
        self._dirty = True
        self._enable_mouse = enable_mouse
        self._mouse_all_motion = mouse_all_motion
        if scroll_optimization is None:
            env = os.environ.get("FIDELIS_SCROLL_OPTIM", "").strip().lower()
            scroll_optimization = env in {"1", "true", "yes", "on"}
        self._scroll_optimization = bool(scroll_optimization)
        self._scroll_optimization_emit = scroll_optimization_emit
        self._on_emit = on_emit
        self._on_start = on_start
        self._on_stop = on_stop

    async def run(self) -> None:
        """Enter alt screen, run main loop, restore terminal on exit."""
        self._running = True
        self._writer.enter_alt_screen()
        self._writer.hide_cursor()
        if self._enable_mouse:
            self._writer.enable_mouse(all_motion=self._mouse_all_motion)

        # Initial sizing
        width, height = self._writer.size()
        self._buf = Buffer(width, height)
        self._prev = Buffer(width, height)
        self.layout(width, height)

        # Handle terminal resize
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGWINCH, self._on_resize)

        try:
            with self._keyboard:
                if self._on_start is not None:
                    await self._on_start()

                while self._running:
                    # Drain all available input before rendering
                    had_input = False
                    while True:
                        inp = self._keyboard.get_input()
                        if inp is None:
                            break
                        if isinstance(inp, MouseEvent):
                            self.on_mouse(inp)
                            self.emit(
                                "ui.mouse",
                                action=inp.action.name,
                                button=inp.button.name,
                                x=inp.x,
                                y=inp.y,
                                shift=inp.shift,
                                meta=inp.meta,
                                ctrl=inp.ctrl,
                            )
                        else:
                            self.on_key(inp)
                            self.emit("ui.key", key=inp)
                        self._dirty = True
                        had_input = True

                    # Advance state (animations, timers)
                    self.update()

                    # Render if dirty
                    if self._dirty:
                        self._dirty = False
                        self.render()
                        self._flush()

                    # Adaptive sleep: short yield when active, full frame sleep when idle
                    if had_input or self._dirty:
                        await asyncio.sleep(0.001)
                    else:
                        await asyncio.sleep(1.0 / self._fps_cap)
        finally:
            if self._on_stop is not None:
                await self._on_stop()
            loop.remove_signal_handler(signal.SIGWINCH)
            if self._enable_mouse:
                self._writer.disable_mouse()
            self._writer.show_cursor()
            self._writer.exit_alt_screen()

    def layout(self, width: int, height: int) -> None:
        """Called on resize. Override to recalculate regions."""

    def update(self) -> None:
        """Called every iteration. Override to advance animations/timers.

        Call mark_dirty() if state changed and a re-render is needed.
        """

    def render(self) -> None:
        """Called each frame when dirty. Override to paint into self._buf."""

    def on_key(self, key: str) -> None:
        """Called on keypress. Override to dispatch to focused component."""

    def on_mouse(self, event: MouseEvent) -> None:
        """Called on mouse event. Override to handle clicks, drags, scrolls."""

    def hit(self, x: int, y: int) -> str | None:
        """Return the semantic id at a screen coordinate, if any.

        Useful for mapping MouseEvent coordinates to rendered regions.
        """
        if self._buf is None:
            return None
        return self._buf.hit(x, y)

    def emit(self, kind: str, **data: Any) -> None:
        """Emit an observation. No-op if no callback registered."""
        if self._on_emit is not None:
            self._on_emit(kind, data)

    def handle_key(
        self,
        key: str,
        state: Any,
        get_layers: Callable[[Any], tuple[Layer, ...]],
        set_layers: Callable[[Any, tuple[Layer, ...]], Any],
    ) -> tuple[Any, bool, Any]:
        """Delegate to process_key() and auto-emit an action fact.

        Returns the same (new_state, should_quit, pop_result) tuple as
        process_key().  After processing, emits one of:
          - ui.action action="quit"   when should_quit is True
          - ui.action action="pop"    when pop_result is not None
          - ui.action action="stay"   otherwise
        """
        new_state, should_quit, pop_result = _process_key(
            key,
            state,
            get_layers,
            set_layers,
        )
        if should_quit:
            self.emit("ui.action", action="quit")
        elif pop_result is not None:
            self.emit("ui.action", action="pop", result=str(pop_result))
        else:
            self.emit("ui.action", action="stay")
        return new_state, should_quit, pop_result

    def mark_dirty(self) -> None:
        """Mark the display as needing a re-render."""
        self._dirty = True

    def quit(self) -> None:
        """Signal the run loop to exit."""
        self._running = False

    def _on_resize(self) -> None:
        """Handle SIGWINCH: resize buffers and recalculate layout."""
        width, height = self._writer.size()
        self._buf = Buffer(width, height)
        self._prev = Buffer(width, height)
        self.layout(width, height)
        self._dirty = True
        self.emit("ui.resize", width=width, height=height)

    def _flush(self) -> None:
        """Diff current vs previous buffer and write changes to terminal."""
        if self._buf is None or self._prev is None:
            return

        if self._scroll_optimization and self._try_flush_scroll_optimized():
            self._prev = self._buf.clone()
            return

        writes = self._buf.diff(self._prev)
        if writes:
            self._writer.write_frame(writes)
        # Swap: current becomes previous for next frame
        self._prev = self._buf.clone()

    def _try_flush_scroll_optimized(self) -> bool:
        if self._buf is None or self._prev is None:
            return False

        cur = self._buf
        prev = self._prev
        if cur.width != prev.width or cur.height != prev.height:
            return False

        width, height = cur.width, cur.height
        if height < 3 or width < 1:
            return False

        max_n = min(3, height - 1)
        if max_n <= 0:
            return False

        old_content = prev.line_hashes(include_style=False)
        new_content = cur.line_hashes(include_style=False)
        old_full = prev.line_hashes(include_style=True)
        new_full = cur.line_hashes(include_style=True)

        cand = self._detect_vertical_scroll(old_content, new_content, max_n=max_n)
        if cand is None:
            return False
        top, bottom, n, overlap_start, overlap_end, match_ratio = cand

        region_height = bottom - top + 1
        if region_height < 6:
            return False

        repaint_lines: set[int] = set()

        # Inserted lines created by the scroll.
        if n > 0:
            for y in range(bottom - n + 1, bottom + 1):
                repaint_lines.add(y)
        else:
            m = -n
            for y in range(top, top + m):
                repaint_lines.add(y)

        # Overlap region: if the scrolled-in line differs (including style), repaint.
        for y in range(overlap_start, overlap_end + 1):
            if new_full[y] != old_full[y + n]:
                repaint_lines.add(y)

        # Outside region: repaint changed lines.
        for y in range(0, top):
            if new_full[y] != old_full[y]:
                repaint_lines.add(y)
        for y in range(bottom + 1, height):
            if new_full[y] != old_full[y]:
                repaint_lines.add(y)

        repaint_in_region = sum(1 for y in repaint_lines if top <= y <= bottom)
        if repaint_in_region >= int(region_height * 0.7):
            return False

        cell_ops: list[ScrollOp | CellWrite] = [ScrollOp(top=top, bottom=bottom, n=n)]
        cells = cur._cells
        for y in sorted(repaint_lines):
            row_start = y * width
            for x in range(width):
                cell_ops.append(CellWrite(x, y, cells[row_start + x]))

        self._writer.write_ops(cell_ops)

        if self._scroll_optimization_emit:
            self.emit(
                "ui.scroll_optim",
                top=top,
                bottom=bottom,
                n=n,
                overlap_start=overlap_start,
                overlap_end=overlap_end,
                match_ratio=match_ratio,
                repainted_lines=len(repaint_lines),
            )

        return True

    @staticmethod
    def _detect_vertical_scroll(
        old_hashes: list[int],
        new_hashes: list[int],
        *,
        max_n: int,
        min_overlap: int = 6,
        min_match_ratio: float = 0.8,
    ) -> tuple[int, int, int, int, int, float] | None:
        """Detect a vertical scroll region.

        Returns (top, bottom, n, overlap_start, overlap_end, match_ratio) where
        n>0 scrolls up and overlap_start..overlap_end are the new-buffer lines
        that are expected to match old[y+n].
        """
        height = len(new_hashes)
        if height != len(old_hashes):
            return None

        best: tuple[int, float, int, int, int, int, int, int] | None = None
        # tuple: (match_count, match_ratio, -mismatch_count, overlap_len, -abs(n), top, bottom, n)

        for step in range(1, max_n + 1):
            for n in (step, -step):
                y0 = max(0, -n)
                y1 = min(height - 1, height - 1 - n)
                if y1 - y0 + 1 < min_overlap:
                    continue

                for a in range(y0, y1 + 1):
                    matches = 0
                    distinct: set[int] = set()
                    for b in range(a, y1 + 1):
                        if new_hashes[b] == old_hashes[b + n]:
                            matches += 1
                        distinct.add(new_hashes[b])

                        overlap_len = b - a + 1
                        if overlap_len < min_overlap:
                            continue

                        ratio = matches / overlap_len
                        if ratio < min_match_ratio:
                            continue

                        if len(distinct) < max(3, overlap_len // 3):
                            continue

                        if n > 0:
                            top = a
                            bottom = b + n
                            overlap_start = a
                            overlap_end = b
                        else:
                            top = a + n
                            bottom = b
                            overlap_start = a
                            overlap_end = b

                        if top < 0 or bottom >= height or top >= bottom:
                            continue

                        mismatches = overlap_len - matches
                        key = (matches, ratio, -mismatches, overlap_len, -abs(n), top, bottom, n)
                        if best is None or key > best:
                            best = key

        if best is None:
            return None

        _, ratio, _, overlap_len, _, top, bottom, n = best
        abs_n = abs(n)
        overlap_start = top if n > 0 else top + abs_n
        overlap_end = bottom - abs_n if n > 0 else bottom
        if overlap_end - overlap_start + 1 != overlap_len:
            overlap_start = max(0, overlap_start)
            overlap_end = min(height - 1, overlap_end)
        return (top, bottom, n, overlap_start, overlap_end, ratio)
