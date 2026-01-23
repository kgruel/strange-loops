"""Base app scaffold: signals, render effect, and main loop pattern."""

from __future__ import annotations

import asyncio
import time
from enum import Enum, auto

from reaktiv import Signal, Effect
from rich.console import Console
from rich.live import Live

from .instrument import metrics


class Mode(Enum):
    """Base mode enum. Subclass to add domain-specific modes."""
    VIEW = auto()
    FILTER = auto()


class BaseApp:
    """Common app scaffold providing UI state signals, render wiring, and main loop.

    Subclass and override:
      - render() -> Layout/RenderableType
      - handle_key(key: str) -> bool (False to quit)
      - _render_dependencies() -> read additional signals to track
    """

    def __init__(self, console: Console):
        self._console = console
        self._live: Live | None = None

        # UI state signals (same across all apps)
        self._running = Signal(True)
        self._mode = Signal(Mode.VIEW)
        self._input_buffer = Signal("")
        self._focused_pane = Signal("")

        self._render_effect: Effect | None = None
        self._render_dirty = False

    def _render_dependencies(self) -> None:
        """Override to read Signals that should trigger re-render.

        Called inside the render Effect body. Read Signals here to establish
        them as dependencies (e.g., self.store.version()).

        IMPORTANT: Only read Signals here, not Computeds. Computeds should
        evaluate lazily when render() reads them. Reading Computeds here
        forces re-evaluation on every Signal change (per-event), defeating
        the debounced render.
        """
        pass

    def _do_render(self) -> None:
        """Effect body: read all dependencies, mark dirty for next loop tick."""
        # Base signal dependencies
        self._running()
        self._mode()
        self._input_buffer()
        self._focused_pane()

        # Subclass dependencies
        self._render_dependencies()

        self._render_dirty = True
        metrics.count("effect_fires")

    def set_live(self, live: Live) -> None:
        self._live = live
        self._live.update(self.render())
        if not self._render_effect:
            self._render_effect = Effect(lambda: self._do_render())

    def _available_rows(self) -> int:
        """Usable rows for content, accounting for chrome (status + help + borders)."""
        height = self._console.size.height
        return max(5, height - 8)

    @property
    def running(self) -> bool:
        return self._running()

    def render(self):
        """Override in subclass. Return a Rich renderable."""
        raise NotImplementedError

    def handle_key(self, key: str) -> bool:
        """Override in subclass. Return False to quit."""
        raise NotImplementedError

    async def run(self, duration: float | None = None) -> None:
        """Main loop: keyboard → handle_key → sleep. Runs until quit or duration."""
        from .keyboard import KeyboardInput

        start_time = time.time()

        with KeyboardInput() as keyboard:
            with Live(console=self._console, refresh_per_second=10) as live:
                self.set_live(live)

                while self.running:
                    if duration and (time.time() - start_time) > duration:
                        break

                    key = keyboard.get_key()
                    if key:
                        self.handle_key(key)

                    if self._render_dirty:
                        self._render_dirty = False
                        with metrics.time("render"):
                            live.update(self.render())
                        metrics.count("frames_rendered")

                    await asyncio.sleep(0.05)
