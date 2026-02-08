"""FileStore: JSONL-backed Store implementation.

Wraps FileWriter (append) and Tailer (read) into a single Store interface.
Events are serialized to a JSONL file on append and deserialized on read.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class FileStore(Generic[T]):
    """JSONL-backed append-only store.

    Combines write (FileWriter pattern) and read (Tailer pattern) into
    a unified Store interface. Maintains an in-memory buffer of events
    appended during this session for cursor-based reads.

    On construction, loads existing events from the file if it exists.
    New events are appended to both the file and in-memory buffer.
    """

    def __init__(
        self,
        path: Path,
        serialize: Callable[[T], dict],
        deserialize: Callable[[dict], T],
    ) -> None:
        self._path = path
        self._serialize = serialize
        self._deserialize = deserialize
        self._events: list[T] = []
        self._file = None

        self._load()
        self._file = path.open("a")

    def _load(self) -> None:
        """Load existing events from file."""
        if not self._path.exists():
            return
        with self._path.open("r") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._events.append(self._deserialize(json.loads(line)))

    def append(self, event: T) -> None:
        """Append one event to the file and in-memory buffer."""
        self._events.append(event)
        if self._file is not None:
            self._file.write(json.dumps(self._serialize(event)) + "\n")
            self._file.flush()

    async def consume(self, event: T) -> None:
        """Consumer protocol: append event."""
        self.append(event)

    def since(self, cursor: int) -> list[T]:
        """Return events from logical index `cursor` onward."""
        return self._events[cursor:]

    def between(self, start: datetime | float, end: datetime | float) -> list[T]:
        """Return events in the time range [start, end].

        Used for fidelity traversal: given a Tick with since/ts,
        retrieve the facts that were folded to produce it.

        Args:
            start: Period start (datetime or epoch float)
            end: Period end (datetime or epoch float)

        Returns:
            Events where start <= event.ts <= end

        Note: Events must have a `ts` attribute (epoch float).
        """
        start_ts = start.timestamp() if isinstance(start, datetime) else start
        end_ts = end.timestamp() if isinstance(end, datetime) else end
        return [e for e in self._events if start_ts <= e.ts <= end_ts]

    def close(self) -> None:
        """Close the underlying file handle."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "FileStore[T]":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    @property
    def events(self) -> list[T]:
        return self._events

    @property
    def total(self) -> int:
        return len(self._events)
