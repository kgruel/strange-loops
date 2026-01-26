"""Source: async iterator protocol for event production.

Source[T] is the dual of Consumer[T]. A Consumer receives events,
a Source produces events.

This is just the type shape — no IO. Implementations live in framework.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, TypeVar, runtime_checkable

T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class Source(Protocol[T_co]):
    """Protocol for anything that produces events as an async iterator.

    Sources yield events. The caller decides what to do with them
    (emit to Stream, fold into Projection, etc.).

    Examples of concrete implementations (in framework):
      - SSHSource: runs collector over SSH, yields parsed events
      - TailerSource: wraps Tailer, yields events from JSONL
      - PollSource: runs collector on interval
      - StreamSource: runs streaming collector

    Usage:
        source: Source[dict] = SSHSource(...)
        async for event in source:
            await stream.emit(event)
    """

    def __aiter__(self) -> AsyncIterator[T_co]: ...

    async def __anext__(self) -> T_co: ...


@runtime_checkable
class ClosableSource(Protocol[T_co]):
    """Source that can be explicitly closed/stopped.

    Extends Source with lifecycle management. Use when you need
    to signal the source to stop producing events.
    """

    def __aiter__(self) -> AsyncIterator[T_co]: ...

    async def __anext__(self) -> T_co: ...

    async def close(self) -> None:
        """Stop producing events and clean up resources."""
        ...
