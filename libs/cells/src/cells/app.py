"""Surface — base class for buffer-rendered terminal applications."""

from __future__ import annotations

import asyncio
import signal
from typing import Any, Callable, Awaitable

from .buffer import Buffer
from .layer import Layer, process_key as _process_key
from .writer import Writer
from .keyboard import KeyboardInput
from ._mouse import MouseEvent

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
            key, state, get_layers, set_layers,
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
        writes = self._buf.diff(self._prev)
        if writes:
            self._writer.write_frame(writes)
        # Swap: current becomes previous for next frame
        self._prev = self._buf.clone()
