"""PollSource: runs a poll collector on an interval.

Implements Source[dict] by calling a collector function periodically
and yielding the returned events.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable

if TYPE_CHECKING:
    from ..ssh_session import SSHSession

logger = logging.getLogger(__name__)

# Collector type: takes SSHSession, returns list of events
PollCollector = Callable[["SSHSession"], Awaitable[list[dict]]]


class PollSource:
    """Source that runs a poll collector at an interval.

    Calls collector(ssh) every interval seconds and yields the events.
    On error, emits source.error event and continues polling.

    Usage:
        async with SSHSession(host, user, key) as ssh:
            source = PollSource(
                ssh, docker.containers, interval=5,
                host="docker-1", collector_name="docker.containers"
            )
            async for event in source:
                process(event)
    """

    def __init__(
        self,
        ssh: "SSHSession",
        collector: PollCollector,
        interval: float = 10.0,
        *,
        host: str = "",
        collector_name: str = "",
    ) -> None:
        self._ssh = ssh
        self._collector = collector
        self._interval = interval
        self._closed = False
        self._buffer: list[dict] = []
        self._last_poll: float = 0.0
        self._host = host
        self._collector_name = collector_name

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
            except Exception as e:
                # Emit error event and continue
                error_event = self._make_error_event(e)
                logger.warning(
                    f"Collector {self._collector_name} on {self._host} failed: {e}"
                )
                return error_event

            # Wait for next poll interval
            await asyncio.sleep(self._interval)

        raise StopAsyncIteration

    def _make_error_event(self, error: Exception) -> dict:
        """Create a source.error event."""
        return {
            "type": "source.error",
            "host": self._host,
            "collector": self._collector_name,
            "error": str(error),
            "timestamp": time.time(),
        }

    async def close(self) -> None:
        """Stop polling."""
        self._closed = True
