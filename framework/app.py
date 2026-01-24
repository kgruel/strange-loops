"""Base app scaffold: signals, render effect, and main loop pattern."""

from __future__ import annotations

import asyncio
import time
from enum import Enum, auto
from typing import Any, Callable, TYPE_CHECKING

from reaktiv import Signal, Effect, batch
from rich.console import Console
from rich.live import Live

from .instrument import metrics

if TYPE_CHECKING:
    from .projection import Projection
    from .store import EventStore


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
        self._filter_history: Signal[list[str]] = Signal([])

        self._render_effect: Effect | None = None
        self._render_dirty = False
        self._dirty_event: asyncio.Event = asyncio.Event()

        # Projection support
        self._projections: list[Projection] = []
        self._projection_store: EventStore | None = None
        self._retention_enabled: bool = False

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
        self._filter_history()

        # Subclass dependencies
        self._render_dependencies()

        self._render_dirty = True
        self._dirty_event.set()
        metrics.count("effect_fires")

    def set_live(self, live: Live) -> None:
        self._live = live
        self._live.update(self.render())
        if not self._render_effect:
            self._render_effect = Effect(lambda: self._do_render())

    def _handle_filter_key(
        self,
        key: str,
        parse_fn: Callable[[str], Any],
        filter_signal: Signal,
        view_mode: Any = None,
    ) -> bool:
        """Default filter-mode key handler.

        Handles Enter (apply), Escape (cancel), Backspace, Up (history cycle),
        and printable chars. Subclasses call this from handle_key() when in
        filter mode.

        Args:
            key: The key event string.
            parse_fn: Converts raw input string into domain filter object.
            filter_signal: The Signal to set with the parsed filter.
            view_mode: The mode to return to (defaults to Mode.VIEW).
        """
        if view_mode is None:
            view_mode = Mode.VIEW

        if key == "\r" or key == "\n":
            raw = self._input_buffer()
            if raw.strip():
                self._filter_history.update(
                    lambda h: ([raw] + [x for x in h if x != raw])[:5]
                )
            with batch():
                filter_signal.set(parse_fn(raw))
                self._mode.set(view_mode)
                self._input_buffer.set("")
        elif key == "\x1b":  # Escape
            with batch():
                self._mode.set(view_mode)
                self._input_buffer.set("")
        elif key == "\x7f":  # Backspace
            self._input_buffer.update(lambda s: s[:-1])
        elif key == "\x1b[A":  # Up arrow — cycle history
            history = self._filter_history()
            if history:
                current = self._input_buffer()
                try:
                    idx = history.index(current)
                    next_idx = (idx + 1) % len(history)
                except ValueError:
                    next_idx = 0
                self._input_buffer.set(history[next_idx])
        elif key.isprintable():
            self._input_buffer.update(lambda s: s + key)
        return True

    def _available_rows(self) -> int:
        """Usable rows for content, accounting for chrome (status + help + borders)."""
        height = self._console.size.height
        return max(5, height - 8)

    @property
    def running(self) -> bool:
        return self._running()

    def register_projection(self, projection: Projection, store: EventStore | None = None) -> None:
        """Register a projection to be advanced each frame tick.

        Args:
            projection: The Projection instance to register.
            store: EventStore to advance against. If None, uses self._projection_store
                   (which must be set before the first frame tick).
        """
        self._projections.append(projection)
        if store is not None:
            self._projection_store = store

    def enable_retention(self, store: EventStore | None = None) -> None:
        """Enable retention: evict events below the min projection cursor each frame."""
        self._retention_enabled = True
        if store is not None:
            self._projection_store = store

    def _advance_projections(self) -> None:
        """Advance all registered projections, then apply retention if enabled."""
        store = self._projection_store
        if not store or not self._projections:
            return

        for proj in self._projections:
            proj.advance(store)

        if self._retention_enabled:
            watermark = min(p.cursor for p in self._projections)
            if watermark > 0:
                store.evict_below(watermark)

    def render(self):
        """Override in subclass. Return a Rich renderable."""
        raise NotImplementedError

    def handle_key(self, key: str) -> bool:
        """Override in subclass. Return False to quit."""
        raise NotImplementedError

    async def run(self, duration: float | None = None) -> None:
        """Main loop: keyboard → handle_key → sleep. Runs until quit or duration."""
        from render.keyboard import KeyboardInput

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

                    # Advance projections before render
                    self._advance_projections()

                    if self._render_dirty:
                        self._render_dirty = False
                        self._dirty_event.clear()
                        with metrics.time("render"):
                            live.update(self.render())
                        metrics.count("frames_rendered")

                    # Wait for dirty signal or timeout (keeps keyboard polling alive)
                    try:
                        await asyncio.wait_for(self._dirty_event.wait(), timeout=0.05)
                    except asyncio.TimeoutError:
                        pass
