"""Emitter protocol and reference implementations.

The Emitter protocol defines the interface for receiving events and results.
ListEmitter and NullEmitter are reference implementations for testing and no-op use cases.
"""

from typing import Protocol

from facts.types import Event, Result


class Emitter(Protocol):
    """Protocol for receiving events and results from a CLI run.

    Invariants:
    - emit() may be called zero or more times
    - finish() must be called exactly once
    - emit() must not be called after finish()

    Implementations may enforce these invariants or ignore them.

    All emitters support context manager protocol for uniform usage:
        with emitter:
            emitter.emit(...)
    """

    def emit(self, event: Event) -> None:
        """Emit an event during the run."""
        ...

    def finish(self, result: Result) -> None:
        """Finalize the run with a result."""
        ...

    def __enter__(self) -> "Emitter":
        """Enter context manager. Returns self."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager. Does not suppress exceptions."""
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

    def __enter__(self) -> "ListEmitter":
        """Enter context manager. Returns self."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager. Does not suppress exceptions."""
        pass


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

    def __enter__(self) -> "NullEmitter":
        """Enter context manager. Returns self."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager. Does not suppress exceptions."""
        pass
