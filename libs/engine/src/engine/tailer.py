"""Tailer: reads JSONL files, tracks position, returns new events on poll.

The inverse of FileWriter. FileWriter appends events to a JSONL file.
Tailer reads events from a JSONL file.

Tracks byte offset so it can:
  - Replay from beginning (or any offset) to catch up
  - Poll for new lines efficiently (seek to last position, read what's new)
  - Resume after restart (persist offset externally if needed)

Composable: poll() returns events, caller decides where they go.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Tailer(Generic[T]):
    """Reads a JSONL file incrementally, tracks byte position.

    Each poll() reads any new complete lines since the last read,
    deserializes them, and returns the list. Non-blocking — returns
    immediately with whatever's available (possibly empty).
    """

    def __init__(self, path: Path, deserialize: Callable[[dict], T]) -> None:
        self._path = path
        self._deserialize = deserialize
        self._offset: int = 0

    @property
    def offset(self) -> int:
        """Current byte position in the file."""
        return self._offset

    @offset.setter
    def offset(self, value: int) -> None:
        """Set byte position (for resume from stored checkpoint)."""
        self._offset = value

    def poll(self) -> list[T]:
        """Read new complete lines since last poll, return deserialized events.

        Seeks to current offset, reads all complete lines (ending with newline),
        advances offset past them. Incomplete trailing lines are left for next poll.
        Returns empty list if file doesn't exist yet or has no new data.
        """
        if not self._path.exists():
            return []

        events: list[T] = []
        with self._path.open("r") as f:
            f.seek(self._offset)
            data = f.read()

        if not data:
            return []

        # Only process complete lines (ending with \n).
        # An incomplete trailing line means a write is in progress — leave it.
        if data.endswith("\n"):
            lines = data.split("\n")
            lines.pop()  # trailing empty string after final \n
            self._offset += len(data.encode())
        else:
            # Split, process all but the last (incomplete) line
            lines = data.split("\n")
            incomplete = lines.pop()
            if not lines:
                return []  # only incomplete data, nothing to process
            # Advance offset past the complete lines only
            complete_data = "\n".join(lines) + "\n"
            self._offset += len(complete_data.encode())

        for line in lines:
            line = line.strip()
            if line:
                events.append(self._deserialize(json.loads(line)))

        return events

    def reset(self) -> None:
        """Reset to beginning of file. Next poll() replays everything."""
        self._offset = 0
