"""StreamSource: wraps a streaming collector.

Implements Source[dict] by iterating over a collector's async iterator
and yielding events as they arrive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Callable

if TYPE_CHECKING:
    from ..ssh_session import SSHSession


# Collector type: takes SSHSession, returns async iterator of events
StreamCollector = Callable[["SSHSession"], AsyncIterator[dict]]


class StreamSource:
    """Source that wraps a streaming collector.

    Iterates over collector(ssh) and yields events as they arrive.
    Stops when the collector stops or when closed.

    Usage:
        async with SSHSession(host, user, key) as ssh:
            source = StreamSource(ssh, docker.events)
            async for event in source:
                process(event)
    """

    def __init__(
        self,
        ssh: "SSHSession",
        collector: StreamCollector,
    ) -> None:
        self._ssh = ssh
        self._collector = collector
        self._closed = False
        self._iter: AsyncIterator[dict] | None = None

    def __aiter__(self) -> AsyncIterator[dict]:
        return self

    async def __anext__(self) -> dict:
        if self._closed:
            raise StopAsyncIteration

        # Lazily start the collector iterator
        if self._iter is None:
            self._iter = self._collector(self._ssh)

        try:
            return await self._iter.__anext__()
        except StopAsyncIteration:
            raise

    async def close(self) -> None:
        """Stop streaming."""
        self._closed = True
