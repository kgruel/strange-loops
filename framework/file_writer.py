"""FileWriter: Consumer that serializes events to JSONL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class FileWriter(Generic[T]):
    """Consumer that appends serialized events to a JSONL file.

    Takes a path and a serialize function. Each consume() call
    writes one JSON line and flushes.
    """

    def __init__(self, path: Path, serialize: Callable[[T], Any]) -> None:
        self._path = path
        self._serialize = serialize
        self._file = path.open("a")

    async def consume(self, event: T) -> None:
        """Serialize and append event as one JSONL line."""
        self._file.write(json.dumps(self._serialize(event)) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "FileWriter[T]":
        return self

    def __exit__(self, *args) -> None:
        self.close()
