"""TailerSource: wraps Tailer for replay mode.

Implements Source[T] by polling a Tailer and yielding events.
Used in --source mode for replaying from JSONL files.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Callable, Generic, TypeVar

from ticks import Tailer

T = TypeVar("T")


class TailerSource(Generic[T]):
    """Source that yields events from a JSONL file via Tailer.

    Polls the Tailer at a configurable interval and yields events.
    Stops when closed.

    Usage:
        source = TailerSource(Path("/tmp/events.jsonl"), deserialize=lambda d: d)
        async for event in source:
            process(event)
    """

    def __init__(
        self,
        path: Path,
        deserialize: Callable[[dict], T],
        poll_interval: float = 0.5,
    ) -> None:
        self._tailer = Tailer(path, deserialize)
        self._poll_interval = poll_interval
        self._closed = False

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        while not self._closed:
            events = self._tailer.poll()
            if events:
                # Yield the first event, save rest for next calls
                event = events.pop(0)
                # Put remaining events back by adjusting internal state
                # Actually, we can't easily do this with the current Tailer API.
                # Instead, buffer events locally.
                if not hasattr(self, "_buffer"):
                    self._buffer: list[T] = []
                self._buffer.extend(events)
                return event
            if hasattr(self, "_buffer") and self._buffer:
                return self._buffer.pop(0)
            await asyncio.sleep(self._poll_interval)

        raise StopAsyncIteration

    async def close(self) -> None:
        """Stop yielding events."""
        self._closed = True

    def reset(self) -> None:
        """Reset to beginning of file."""
        self._tailer.reset()
        if hasattr(self, "_buffer"):
            self._buffer.clear()
