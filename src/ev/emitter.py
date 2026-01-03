"""Emitter protocol and reference implementations.

The Emitter protocol defines the interface for receiving events and results.
ListEmitter and NullEmitter are reference implementations for testing and no-op use cases.
"""

from typing import Protocol

from ev.types import Event, Result


class Emitter(Protocol):
    """Protocol for receiving events and results from a CLI run.

    Invariants:
    - emit() may be called zero or more times
    - finish() must be called exactly once
    - emit() must not be called after finish()

    Implementations may enforce these invariants or ignore them.
    """

    def emit(self, event: Event) -> None:
        """Emit an event during the run."""
        ...

    def finish(self, result: Result) -> None:
        """Finalize the run with a result."""
        ...


class ListEmitter:
    """Reference emitter that collects events and result.

    Useful for testing and inspection. Enforces emitter invariants.

    Attributes:
        events: List of emitted events in order.
        result: The final result, or None if not yet finished.
    """

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.result: Result | None = None
        self._finished: bool = False

    def emit(self, event: Event) -> None:
        """Emit an event. Raises if already finished."""
        if self._finished:
            raise RuntimeError("Cannot emit after finish()")
        self.events.append(event)

    def finish(self, result: Result) -> None:
        """Finalize with a result. Raises if already finished."""
        if self._finished:
            raise RuntimeError("finish() already called")
        self._finished = True
        self.result = result


class NullEmitter:
    """No-op emitter for when you don't care about events.

    Does not enforce any invariants. Silently accepts all calls.
    """

    def emit(self, event: Event) -> None:
        """Accept and discard event."""
        pass

    def finish(self, result: Result) -> None:
        """Accept and discard result."""
        pass
