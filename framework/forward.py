"""Forward: Consumer that bridges events between typed Streams."""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

from .stream import Stream

T = TypeVar("T")
U = TypeVar("U")


class Forward(Generic[T, U]):
    """Consumer that transforms events from one Stream and emits to another.

    Bridges typed streams: consume T, transform to U, emit on target Stream[U].
    """

    def __init__(self, target: Stream[U], transform: Callable[[T], U]) -> None:
        self._target = target
        self._transform = transform

    async def consume(self, event: T) -> None:
        """Transform and forward to target stream."""
        transformed = self._transform(event)
        await self._target.emit(transformed)
