"""RenderApp — base class for buffer-rendered terminal applications."""

from __future__ import annotations

import asyncio
import signal

from .buffer import Buffer
from .writer import Writer
from framework.keyboard import KeyboardInput


class RenderApp:
    """Base class for buffer-rendered applications.

    Subclasses override layout(), render(), and on_key() to build interactive
    terminal UIs using the cell-buffer rendering system.
    """

    def __init__(self, *, fps_cap: int = 60):
        self._writer = Writer()
        self._fps_cap = fps_cap
        self._buf: Buffer | None = None
        self._prev: Buffer | None = None
        self._keyboard = KeyboardInput()
        self._running = False
        self._dirty = True

    async def run(self) -> None:
        """Enter alt screen, run main loop, restore terminal on exit."""
        self._running = True
        self._writer.enter_alt_screen()
        self._writer.hide_cursor()

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
                while self._running:
                    # Poll keyboard
                    key = self._keyboard.get_key()
                    if key is not None:
                        self.on_key(key)
                        self._dirty = True

                    # Render if dirty
                    if self._dirty:
                        self._dirty = False
                        self.render()
                        self._flush()

                    await asyncio.sleep(1.0 / self._fps_cap)
        finally:
            loop.remove_signal_handler(signal.SIGWINCH)
            self._writer.show_cursor()
            self._writer.exit_alt_screen()

    def layout(self, width: int, height: int) -> None:
        """Called on resize. Override to recalculate regions."""

    def render(self) -> None:
        """Called each frame when dirty. Override to paint into self._buf."""

    def on_key(self, key: str) -> None:
        """Called on keypress. Override to dispatch to focused component."""

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

    def _flush(self) -> None:
        """Diff current vs previous buffer and write changes to terminal."""
        if self._buf is None or self._prev is None:
            return
        writes = self._prev.diff(self._buf)
        if writes:
            self._writer.write_frame(writes)
        # Swap: current becomes previous for next frame
        self._prev = self._buf.clone()
