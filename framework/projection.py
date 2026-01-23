"""Projection: incremental fold over an EventStore.

A Projection maintains a `.state` Signal that is advanced incrementally
by processing new events since its last cursor position. Unlike Computed
(which re-derives from scratch), Projection accumulates state — O(new events)
per frame tick rather than O(all events).

Subclass and override `apply()` to define how each event updates state.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from reaktiv import Signal

from .store import EventStore

S = TypeVar("S")  # State type
T = TypeVar("T")  # Event type


class Projection(Generic[S, T]):
    """Incremental fold over an EventStore.

    Maintains a `.state` Signal advanced by the app frame loop.
    NOT a Computed — it's honest about being mutable state.

    Subclass and override `apply(state, event)` to define the fold.
    """

    def __init__(self, initial: S):
        self.state: Signal[S] = Signal(initial)
        self.cursor: int = 0

    def apply(self, state: S, event: T) -> S:
        """Process one event, return new state.

        Override in subclass. Called once per event during advance().
        """
        raise NotImplementedError

    def advance(self, store: EventStore[T]) -> None:
        """Process all new events since last cursor, update .state once."""
        new_events = store.since(self.cursor)
        if not new_events:
            return
        current = self.state()
        for event in new_events:
            current = self.apply(current, event)
            self.cursor += 1
        self.state.set(current)
