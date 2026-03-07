"""Store abstraction and EventStore implementation.

Store is the protocol — append, since, close.
EventStore is the in-memory implementation with optional JSONL persistence.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Generic, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")
T_contra = TypeVar("T_contra", contravariant=True)


@runtime_checkable
class Store(Protocol[T_contra]):
    """Append-only event log interface.

    Three operations: append events, read since cursor, close resources.
    Implementations: EventStore (in-memory), FileStore (JSONL files).

    Optional: between() for time-range queries (fidelity traversal).
    """

    def append(self, event: T_contra) -> None:
        """Append one event to the log."""
        ...

    def since(self, cursor: int) -> list:
        """Return events from logical index `cursor` onward."""
        ...

    def between(self, start: datetime | float, end: datetime | float) -> list:
        """Return events in the time range [start, end].

        Used for fidelity traversal: given a Tick with since/ts,
        retrieve the facts that were folded to produce it.

        Args:
            start: Period start (datetime or epoch float)
            end: Period end (datetime or epoch float)

        Returns:
            Events where start <= event.ts <= end
        """
        ...

    def close(self) -> None:
        """Release resources."""
        ...


class EventStore(Generic[T]):
    """Append-only in-memory event store with version counter.

    The version bumps on each append — consumers check it to detect new events.

    Optional persistence: pass path, serialize, and deserialize to enable
    JSON Lines append-only file storage. Events are loaded on init and
    appended on each append(). The file handle is kept open for the lifetime
    of the store — call close() when done, or use as a context manager.
    """

    def __init__(
        self,
        *,
        path: Path | None = None,
        serialize: Callable[[T], dict] | None = None,
        deserialize: Callable[[dict], T] | None = None,
    ):
        self._events: list[T] = []
        self._offset: int = 0  # logical index of _events[0] after eviction
        self._version: int = 0
        self._path = path
        self._serialize = serialize
        self._deserialize = deserialize
        self._file = None

        if path is not None:
            if serialize is None or deserialize is None:
                raise ValueError("path requires both serialize and deserialize")
            self._load()
            self._version = len(self._events)
            self._file = path.open("a")

    def _load(self) -> None:
        """Load events from file on init."""
        if self._path is None or not self._path.exists():
            return
        with self._path.open("r") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._events.append(self._deserialize(json.loads(line)))

    async def consume(self, event: T) -> None:
        """Consumer protocol: append event to store."""
        self.append(event)

    @property
    def version(self) -> int:
        """Bumped on each append. Use to detect new events."""
        return self._version

    def append(self, event: T) -> None:
        self._events.append(event)
        if self._file is not None:
            self._file.write(json.dumps(self._serialize(event)) + "\n")
            self._file.flush()
        self._version += 1

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "EventStore[T]":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    @property
    def events(self) -> list[T]:
        return self._events

    @property
    def total(self) -> int:
        return self._offset + len(self._events)

    def since(self, cursor: int) -> list[T]:
        """Return events from logical index `cursor` onward.

        Raises IndexError if cursor is below the eviction watermark.
        """
        if cursor < self._offset:
            raise IndexError(
                f"Cursor {cursor} is below eviction watermark {self._offset}. "
                f"Events before index {self._offset} have been evicted."
            )
        physical = cursor - self._offset
        return self._events[physical:]

    def evict_below(self, n: int) -> None:
        """Evict events below logical index n.

        After eviction, since() still works with cursors >= n.
        Cursors < n will raise IndexError.
        """
        if n <= self._offset:
            return  # nothing to evict
        physical = n - self._offset
        if physical >= len(self._events):
            physical = len(self._events)
        self._events = self._events[physical:]
        self._offset = n

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
        # Normalize to epoch floats
        start_ts = start.timestamp() if isinstance(start, datetime) else start
        end_ts = end.timestamp() if isinstance(end, datetime) else end

        return [e for e in self._events if start_ts <= e.ts <= end_ts]

    def latest_by_kind(self, kind: str) -> T | None:
        """Return the most recent fact of a given kind, or None."""
        for e in reversed(self._events):
            if e.kind == kind:
                return e
        return None

    def latest_by_kind_where(self, kind: str, key: str, value: Any) -> T | None:
        """Return the most recent fact of kind where payload[key] == value."""
        for e in reversed(self._events):
            if e.kind == kind and e.payload.get(key) == value:
                return e
        return None

    def has_kind_since(self, kind: str, ts: float) -> bool:
        """True if any fact of kind exists with ts > the given timestamp."""
        for e in reversed(self._events):
            if e.ts <= ts:
                break
            if e.kind == kind:
                return True
        return False
