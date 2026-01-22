"""
Event bridge utilities.

Event bridges connect reaktiv signals to ev events. The primary bridge methods
are on ReactiveEmitter:

- watch_signal: Emit on every change
- watch_notable: Emit only when value is notable (e.g., errors)
- watch_transition: Emit on specific state transitions
- watch_lifecycle: Emit started/completed events for async operations
- watch_each: Emit for each new/changed item in a collection

This module provides standalone utilities that work without ReactiveEmitter,
useful for testing or when you only need event emission without UI.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar, TYPE_CHECKING

from reaktiv import Effect

if TYPE_CHECKING:
    from ev import Emitter

T = TypeVar("T")


def create_notable_watcher(
    emitter: "Emitter",
    signal_fn: Callable[[], T],
    signal_name: str,
    *,
    is_notable: Callable[[T], bool],
    to_data: Callable[[T], dict[str, Any]] | None = None,
    level: str = "info",
) -> Effect:
    """
    Create an Effect that emits events only when signal value is notable.

    Standalone version of ReactiveEmitter.watch_notable().
    """
    from ev import Event

    to_data = to_data or (lambda v: {"value": v})
    prev_notable = [False]
    prev_value: list[T | None] = [None]

    def watcher():
        value = signal_fn()
        notable = is_notable(value)

        if notable and (not prev_notable[0] or value != prev_value[0]):
            emitter.emit(Event.log_signal(signal_name, level=level, **to_data(value)))

        prev_notable[0] = notable
        prev_value[0] = value

    return Effect(watcher)


def create_each_watcher(
    emitter: "Emitter",
    collection_fn: Callable[[], dict[str, T]],
    signal_name: str,
    *,
    to_data: Callable[[str, T], dict[str, Any]],
    level: str = "info",
) -> Effect:
    """
    Create an Effect that emits events for each new/changed item in a collection.

    Standalone version of ReactiveEmitter.watch_each().
    """
    from ev import Event

    prev_items: dict[str, T] = {}

    def watcher():
        nonlocal prev_items
        items = collection_fn()

        for key, value in items.items():
            if key not in prev_items or prev_items[key] != value:
                emitter.emit(Event.log_signal(signal_name, level=level, **to_data(key, value)))

        prev_items = dict(items)

    return Effect(watcher)
