"""Append-only event store with reaktiv Signal integration."""

from __future__ import annotations

from typing import Generic, TypeVar

from reaktiv import Signal

T = TypeVar("T")


class EventStore(Generic[T]):
    """Append-only event store with version signal for reaktiv integration.

    The version Signal bumps on each add, so Computed/Effect can depend on it
    without O(n) list copying.
    """

    def __init__(self):
        self._events: list[T] = []
        self.version = Signal(0)

    def add(self, event: T) -> None:
        self._events.append(event)
        self.version.update(lambda v: v + 1)

    @property
    def events(self) -> list[T]:
        return self._events

    @property
    def total(self) -> int:
        return len(self._events)
