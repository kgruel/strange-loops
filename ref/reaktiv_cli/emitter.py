"""Reactive Emitter - bridges reaktiv signals to Rich Live rendering + ev events."""

from __future__ import annotations

from typing import Any, Callable, TypeVar, TYPE_CHECKING

from reaktiv import Effect

if TYPE_CHECKING:
    from rich.console import Console
    from rich.live import Live
    from ev import Emitter, Event, Result


T = TypeVar("T")


class ReactiveEmitter:
    """
    Bridges reaktiv signals to Rich Live rendering + ev events.

    Combines:
    1. Reactive rendering (Signal -> UI) via Rich Live
    2. ev event emission (Signal changes -> Events)
    3. ev result handling (final state -> Result)

    Features:
    - Lazy set_ui(): can call before or after entering context
    - Optional constructor ui_fn for immediate setup
    - Event bridge methods: watch_signal, watch_notable, watch_transition, watch_lifecycle, watch_each
    - Clean context manager lifecycle
    """

    def __init__(
        self,
        inner: "Emitter",
        ui_fn: Callable[[], Any] | None = None,
        console: "Console | None" = None,
        refresh_per_second: int = 12,
    ):
        self._inner = inner
        self._ui_fn = ui_fn
        self._refresh_per_second = refresh_per_second

        # Lazy import to avoid hard dependency
        if console is None:
            from rich.console import Console

            console = Console(stderr=True)
        self._console = console

        self._live: "Live | None" = None
        self._render_effect: Effect | None = None
        self._watchers: list[Effect] = []
        self._in_context = False

    def set_ui(self, ui_fn: Callable[[], Any]) -> None:
        """
        Set the UI function (returns Rich renderable).

        Can be called before or after entering context.
        If already in context and Live not started, starts it now.
        """
        self._ui_fn = ui_fn
        if self._in_context and self._live is None:
            self._start_live()

    def _start_live(self) -> None:
        """Start the Live display and render Effect."""
        if self._ui_fn is None:
            return

        from rich.live import Live

        self._live = Live(
            console=self._console,
            refresh_per_second=self._refresh_per_second,
            transient=True,
        )
        self._live.__enter__()

        def render():
            renderable = self._ui_fn()
            self._live.update(renderable)

        self._render_effect = Effect(render)

    def __enter__(self) -> "ReactiveEmitter":
        self._inner.__enter__()
        self._in_context = True

        if self._ui_fn is not None:
            self._start_live()

        return self

    def __exit__(self, *args):
        self._in_context = False

        for w in self._watchers:
            w.dispose()
        self._watchers.clear()

        if self._render_effect:
            self._render_effect.dispose()
        if self._live:
            self._live.__exit__(*args)
        # Don't exit inner emitter - caller handles finish()

    def emit(self, event: "Event") -> None:
        """Pass-through to inner emitter."""
        self._inner.emit(event)

    def finish(self, result: "Result") -> None:
        """Pass-through to inner emitter."""
        self._inner.finish(result)

    # =========================================================================
    # EVENT BRIDGES: Connect signals to ev events
    # =========================================================================

    def watch_signal(
        self,
        signal_fn: Callable[[], T],
        signal_name: str,
        *,
        to_data: Callable[[T], dict[str, Any]] | None = None,
        level: str = "info",
    ) -> Effect:
        """
        Emit an ev Event whenever a signal changes.

        Every change emits an event. Use watch_notable for filtered emission.
        """
        from ev import Event

        to_data = to_data or (lambda v: {"value": v})

        def watcher():
            value = signal_fn()
            self._inner.emit(Event.log_signal(signal_name, level=level, **to_data(value)))

        effect = Effect(watcher)
        self._watchers.append(effect)
        return effect

    def watch_notable(
        self,
        signal_fn: Callable[[], T],
        signal_name: str,
        *,
        is_notable: Callable[[T], bool],
        to_data: Callable[[T], dict[str, Any]] | None = None,
        level: str = "info",
    ) -> Effect:
        """
        Emit an ev Event only when signal value is notable.

        Emits when:
        - Value becomes notable (transition to notable)
        - Value changes while notable

        Does NOT emit when:
        - Value is not notable
        - Value becomes not-notable
        """
        from ev import Event

        to_data = to_data or (lambda v: {"value": v})
        prev_notable = [False]
        prev_value: list[T | None] = [None]

        def watcher():
            value = signal_fn()
            notable = is_notable(value)

            if notable and (not prev_notable[0] or value != prev_value[0]):
                self._inner.emit(Event.log_signal(signal_name, level=level, **to_data(value)))

            prev_notable[0] = notable
            prev_value[0] = value

        effect = Effect(watcher)
        self._watchers.append(effect)
        return effect

    def watch_transition(
        self,
        signal_fn: Callable[[], T],
        signal_name: str,
        *,
        from_state: T | None = None,
        to_state: T,
        to_data: Callable[[T], dict[str, Any]] | None = None,
        level: str = "info",
    ) -> Effect:
        """
        Emit an ev Event when signal transitions to a specific state.

        Useful for lifecycle events: idle -> loading, loading -> loaded, etc.
        """
        from ev import Event

        to_data = to_data or (lambda v: {"state": v})
        prev_value: list[T | None] = [None]
        first_run = [True]

        def watcher():
            value = signal_fn()

            if first_run[0]:
                first_run[0] = False
                prev_value[0] = value
                return

            matches_from = from_state is None or prev_value[0] == from_state
            matches_to = value == to_state

            if matches_from and matches_to:
                self._inner.emit(Event.log_signal(signal_name, level=level, **to_data(value)))

            prev_value[0] = value

        effect = Effect(watcher)
        self._watchers.append(effect)
        return effect

    def watch_lifecycle(
        self,
        signal_fn: Callable[[], T],
        *,
        started_name: str,
        completed_name: str,
        is_started: Callable[[T], bool],
        is_completed: Callable[[T], bool],
        to_started_data: Callable[[T], dict[str, Any]] | None = None,
        to_completed_data: Callable[[T], dict[str, Any]] | None = None,
    ) -> Effect:
        """
        Emit lifecycle events (started/completed) based on signal state.

        Common pattern for async operations:
        - started: when loading begins
        - completed: when loading finishes (success or error)
        """
        from ev import Event

        to_started_data = to_started_data or (lambda v: {})
        to_completed_data = to_completed_data or (lambda v: {})
        emitted_started = [False]

        def watcher():
            value = signal_fn()

            if is_started(value) and not emitted_started[0]:
                self._inner.emit(Event.log_signal(started_name, **to_started_data(value)))
                emitted_started[0] = True

            if is_completed(value) and emitted_started[0]:
                self._inner.emit(Event.log_signal(completed_name, **to_completed_data(value)))
                emitted_started[0] = False  # Reset for potential retry

        effect = Effect(watcher)
        self._watchers.append(effect)
        return effect

    def watch_each(
        self,
        collection_fn: Callable[[], dict[str, T]],
        signal_name: str,
        *,
        to_data: Callable[[str, T], dict[str, Any]],
        level: str = "info",
    ) -> Effect:
        """
        Emit ev Event for each new/changed item in a collection.

        Useful for tracking items in a dict keyed by ID.
        """
        from ev import Event

        prev_items: dict[str, T] = {}

        def watcher():
            nonlocal prev_items
            items = collection_fn()

            for key, value in items.items():
                if key not in prev_items or prev_items[key] != value:
                    self._inner.emit(Event.log_signal(signal_name, level=level, **to_data(key, value)))

            prev_items = dict(items)

        effect = Effect(watcher)
        self._watchers.append(effect)
        return effect
