"""Receive a store — create-or-merge with SQLite validation.

The "other end" of push: validates the source is a SQLite database,
then either copies it as a new store or merges into an existing one.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .merge import merge_store

# First 16 bytes of every SQLite database file.
_SQLITE_MAGIC = b"SQLite format 3\x00"


@dataclass(frozen=True)
class ReceiveResult:
    """Outcome of a receive operation."""

    status: Literal["created", "merged"]
    facts: int
    ticks: int


def receive_store(target: Path, source: Path) -> ReceiveResult:
    """Create-or-merge: receive a source store into a target location.

    If the target doesn't exist, the source is copied as-is.
    If the target exists, the source is merged into it (ULID dedup).

    Validates source has SQLite magic bytes before operating.

    Args:
        target: Path where the store should end up.
        source: Path to the incoming store (e.g. a temp file from transport).

    Returns:
        ReceiveResult with status ("created" or "merged") and counts.

    Raises:
        FileNotFoundError: If source does not exist.
        ValueError: If source is not a valid SQLite database.
    """
    source = Path(source)
    target = Path(target)

    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")

    _validate_sqlite(source)

    if target.exists():
        result = merge_store(target, source)
        return ReceiveResult(
            status="merged",
            facts=result.facts_added,
            ticks=result.ticks_added,
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))

        # Count what was created
        from ._conn import _open

        conn = _open(target, read_only=True)
        try:
            facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            ticks = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        finally:
            conn.close()

        return ReceiveResult(status="created", facts=facts, ticks=ticks)


def _validate_sqlite(path: Path) -> None:
    """Check that a file starts with the SQLite magic bytes."""
    with open(path, "rb") as f:
        header = f.read(16)
    if header != _SQLITE_MAGIC:
        raise ValueError(f"Not a valid SQLite database: {path}")
