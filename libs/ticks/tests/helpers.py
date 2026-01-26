"""Test helpers: event types, serializers, projections.

These are building blocks for tests, not fixtures.
Fixtures in conftest.py compose these into test scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rill import Projection


# --- Sample event types ---


@dataclass
class Event:
    """Generic test event with a value."""

    value: int


@dataclass
class NamedEvent:
    """Event with name and amount, for richer test scenarios."""

    name: str
    amount: int


# --- Serialization helpers ---


def serialize_event(e: Event) -> dict[str, Any]:
    return {"value": e.value}


def deserialize_event(d: dict[str, Any]) -> Event:
    return Event(value=d["value"])


def serialize_named(e: NamedEvent) -> dict[str, Any]:
    return {"name": e.name, "amount": e.amount}


def deserialize_named(d: dict[str, Any]) -> NamedEvent:
    return NamedEvent(name=d["name"], amount=d["amount"])


# --- Projection implementations ---


class SumProjection(Projection[int, Event]):
    """Sums event values. Simple fold for testing."""

    def apply(self, state: int, event: Event) -> int:
        return state + event.value


class CountProjection(Projection[int, Event]):
    """Counts events."""

    def apply(self, state: int, event: Event) -> int:
        return state + 1


class NamedSumProjection(Projection[dict[str, int], NamedEvent]):
    """Sums amounts by name. Demonstrates dict state."""

    def apply(self, state: dict[str, int], event: NamedEvent) -> dict[str, int]:
        new_state = state.copy()
        new_state[event.name] = new_state.get(event.name, 0) + event.amount
        return new_state
