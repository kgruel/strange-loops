"""Projection: incremental fold over events.

A Projection maintains a `.state` Signal that is advanced incrementally
by processing new events. Unlike Computed (which re-derives from scratch),
Projection accumulates state — O(new events) per update rather than O(all).

Works in two modes:
  1. Stream consumer: tap a Projection onto a Stream, events arrive via consume()
  2. Store-driven: call advance(store) to pull new events since last cursor

Subclass and override `apply()` to define how each event updates state.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from reaktiv import Signal

from .instrument import metrics
from .store import EventStore

S = TypeVar("S")  # State type
T = TypeVar("T")  # Event type


class Projection(Generic[S, T]):
    """Incremental fold over events.

    Maintains a `.state` Signal updated on each event.
    Implements the Consumer protocol so it can be tapped onto a Stream.

    Subclass and override `apply(state, event)` to define the fold.
    """

    def __init__(self, initial: S):
        self.state: Signal[S] = Signal(initial)
        self.cursor: int = 0

    @property
    def name(self) -> str:
        return type(self).__name__

    def apply(self, state: S, event: T) -> S:
        """Process one event, return new state.

        Override in subclass. Called once per event during advance()/consume().
        """
        raise NotImplementedError

    async def consume(self, event: T) -> None:
        """Consumer protocol: fold a single event into state."""
        current = self.state()
        new_state = self.apply(current, event)
        self.state.set(new_state)
        self.cursor += 1
        metrics.count(f"proj.{self.name}.events_folded")

    def advance(self, store: EventStore[T]) -> None:
        """Process all new events since last cursor, update .state once."""
        new_events = store.since(self.cursor)
        if not new_events:
            return
        with metrics.time(f"proj.{self.name}.advance"):
            current = self.state()
            for event in new_events:
                current = self.apply(current, event)
                self.cursor += 1
            self.state.set(current)
        metrics.count(f"proj.{self.name}.events_folded", len(new_events))
