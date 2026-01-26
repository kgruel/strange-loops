"""Typed async event multiplexer.

Stream is the routing primitive. Consumers tap onto streams to receive events.
Sources emit to streams. That's it.

No operator chains. No backpressure. No main loop ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")
T_contra = TypeVar("T_contra", contravariant=True)


@runtime_checkable
class Consumer(Protocol[T_contra]):
    """Protocol for anything that consumes events from a Stream."""

    async def consume(self, event: T_contra) -> None: ...


@dataclass
class Tap(Generic[T]):
    """Handle returned from stream.tap(). Used for detach."""

    consumer: Consumer
    filter: Callable[[T], bool] | None = None
    transform: Callable[[T], Any] | None = None


class Stream(Generic[T]):
    """Typed async event multiplexer.

    Fan-out to all taps on emit(). Each tap can optionally filter and/or
    transform before delivery to its consumer.
    """

    def __init__(self) -> None:
        self._taps: list[Tap[T]] = []

    async def emit(self, event: T) -> None:
        """Fan-out event to all attached taps."""
        for tap in list(self._taps):  # snapshot to allow detach during emit
            if tap.filter is not None and not tap.filter(event):
                continue
            value = tap.transform(event) if tap.transform is not None else event
            await tap.consumer.consume(value)

    def tap(
        self,
        consumer: Consumer,
        *,
        filter: Callable[[T], bool] | None = None,
        transform: Callable[[T], Any] | None = None,
    ) -> Tap[T]:
        """Attach a consumer. Returns a Tap handle for later detach."""
        t = Tap(consumer=consumer, filter=filter, transform=transform)
        self._taps.append(t)
        return t

    def detach(self, tap: Tap[T]) -> None:
        """Remove a tap. No-op if already detached."""
        try:
            self._taps.remove(tap)
        except ValueError:
            pass

    @property
    def tap_count(self) -> int:
        return len(self._taps)
