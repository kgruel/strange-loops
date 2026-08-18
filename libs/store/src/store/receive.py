"""Receive a store — create-or-merge with SQLite validation.

The "other end" of push: validates the source is a SQLite database,
then either copies it as a new store or merges into an existing one.

The merge arm delegates to :func:`store.merge_store`, so it inherits that
function's dispatch on the target's custody for free. The CREATE arm refuses
when the target's ``.arrival`` sibling exists: copying a ``.db`` over a live
arrival log's index would mint a second custody holder beside it — the one
hazard the half-migrated shape names. Everything else is unchanged, because
transport slices produce plain ``.db`` files and receiving one into a
non-existent target still creates a plain sqlite store.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._conn import refuse_create_over_arrival_custody
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
    If the target exists, the source is merged into it (id-PK dedup).

    Validates source has SQLite magic bytes before operating.

    Args:
        target: Path where the store should end up.
        source: Path to the incoming store (e.g. a temp file from transport).

    Returns:
        ReceiveResult with status ("created" or "merged") and counts.

    Raises:
        FileNotFoundError: If source does not exist.
        ValueError: If source is not a valid SQLite database.
        engine.arrival_store.ArrivalCanonicalUnsupported: If the target does
            not exist but its ``.arrival`` sibling does.
    """
    source = Path(source)
    target = Path(target)

    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")

    _validate_sqlite(source)

    if not target.exists():
        refuse_create_over_arrival_custody(target, "copying a foreign db")

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
