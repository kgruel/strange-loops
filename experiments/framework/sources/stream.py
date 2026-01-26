"""StreamSource: wraps a streaming collector.

Implements Source[dict] by iterating over a collector's async iterator
and yielding events as they arrive.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, AsyncIterator, Callable

if TYPE_CHECKING:
    from ..ssh_session import SSHSession

logger = logging.getLogger(__name__)

# Collector type: takes SSHSession, returns async iterator of events
StreamCollector = Callable[["SSHSession"], AsyncIterator[dict]]


class StreamSource:
    """Source that wraps a streaming collector.

    Iterates over collector(ssh) and yields events as they arrive.
    On error, emits source.error event and stops.

    Usage:
        async with SSHSession(host, user, key) as ssh:
            source = StreamSource(
                ssh, docker.events,
                host="docker-1", collector_name="docker.events"
            )
            async for event in source:
                process(event)
    """

    def __init__(
        self,
        ssh: "SSHSession",
        collector: StreamCollector,
        *,
        host: str = "",
        collector_name: str = "",
    ) -> None:
        self._ssh = ssh
        self._collector = collector
        self._closed = False
        self._iter: AsyncIterator[dict] | None = None
        self._host = host
        self._collector_name = collector_name
        self._error_emitted = False

    def __aiter__(self) -> AsyncIterator[dict]:
        return self

    async def __anext__(self) -> dict:
        if self._closed:
            raise StopAsyncIteration

        # Lazily start the collector iterator
        if self._iter is None:
            try:
                self._iter = self._collector(self._ssh)
            except Exception as e:
                # Error starting the stream
                if not self._error_emitted:
                    self._error_emitted = True
                    logger.warning(
                        f"Collector {self._collector_name} on {self._host} failed to start: {e}"
                    )
                    return self._make_error_event(e)
                raise StopAsyncIteration

        try:
            return await self._iter.__anext__()
        except StopAsyncIteration:
            raise
        except Exception as e:
            # Error during streaming — emit error and stop
            if not self._error_emitted:
                self._error_emitted = True
                logger.warning(
                    f"Collector {self._collector_name} on {self._host} failed: {e}"
                )
                return self._make_error_event(e)
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
        """Stop streaming."""
        self._closed = True
