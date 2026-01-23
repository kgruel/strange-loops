"""Append-only event store with reaktiv Signal integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Generic, TypeVar

from reaktiv import Signal

from .instrument import metrics

T = TypeVar("T")


class EventStore(Generic[T]):
    """Append-only event store with version signal for reaktiv integration.

    The version Signal bumps on each add, so Computed/Effect can depend on it
    without O(n) list copying.

    Optional persistence: pass path, serialize, and deserialize to enable
    JSON Lines append-only file storage. Events are loaded on init and
    appended on each add(). The file handle is kept open for the lifetime
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
        self._path = path
        self._serialize = serialize
        self._deserialize = deserialize
        self._file = None

        if path is not None:
            if serialize is None or deserialize is None:
                raise ValueError("path requires both serialize and deserialize")
            self._load()
            self._file = path.open("a")

        self.version = Signal(len(self._events))

    def _load(self) -> None:
        """Load events from file on init."""
        if self._path is None or not self._path.exists():
            return
        with self._path.open("r") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._events.append(self._deserialize(json.loads(line)))

    def add(self, event: T) -> None:
        self._events.append(event)
        if self._file is not None:
            with metrics.time("store_write"):
                self._file.write(json.dumps(self._serialize(event)) + "\n")
                self._file.flush()
        metrics.count("events_added")
        metrics.gauge("store_size", len(self._events))
        self.version.update(lambda v: v + 1)

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
        return len(self._events)
