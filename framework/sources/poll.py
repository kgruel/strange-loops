"""PollSource: runs a poll collector on an interval.

Implements Source[dict] by calling a collector function periodically
and yielding the returned events.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable

if TYPE_CHECKING:
    from ..ssh_session import SSHSession


# Collector type: takes SSHSession, returns list of events
PollCollector = Callable[["SSHSession"], Awaitable[list[dict]]]


class PollSource:
    """Source that runs a poll collector at an interval.

    Calls collector(ssh) every interval seconds and yields the events.
    Stops when closed or when the SSH session fails.

    Usage:
        async with SSHSession(host, user, key) as ssh:
            source = PollSource(ssh, docker.containers, interval=5)
            async for event in source:
                process(event)
    """

    def __init__(
        self,
        ssh: "SSHSession",
        collector: PollCollector,
        interval: float = 10.0,
    ) -> None:
        self._ssh = ssh
        self._collector = collector
        self._interval = interval
        self._closed = False
        self._buffer: list[dict] = []
        self._last_poll: float = 0.0

    def __aiter__(self) -> AsyncIterator[dict]:
        return self

    async def __anext__(self) -> dict:
        while not self._closed:
            # Return buffered events first
            if self._buffer:
                return self._buffer.pop(0)

            # Poll for new events
            try:
                events = await self._collector(self._ssh)
                if events:
                    self._buffer.extend(events[1:])
                    return events[0]
            except Exception:
                # On error, stop iteration
                raise StopAsyncIteration

            # Wait for next poll interval
            await asyncio.sleep(self._interval)

        raise StopAsyncIteration

    async def close(self) -> None:
        """Stop polling."""
        self._closed = True
