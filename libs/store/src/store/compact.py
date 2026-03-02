"""Compact a store — VACUUM + PRAGMA optimize.

Reclaims space from deleted rows and WAL fragments,
then runs SQLite's optimize pragma for index statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._conn import _open


@dataclass(frozen=True)
class CompactResult:
    """Size change from a compact operation."""

    before_bytes: int
    after_bytes: int
    saved_bytes: int


def compact_store(path: Path) -> CompactResult:
    """VACUUM + PRAGMA optimize a store database.

    Args:
        path: Path to the store database.

    Returns:
        CompactResult with size before, after, and bytes saved.

    Raises:
        FileNotFoundError: If the database does not exist.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Store not found: {path}")

    before_bytes = _total_size(path)

    conn = _open(path)
    try:
        conn.execute("VACUUM")
        conn.execute("PRAGMA optimize")
    finally:
        conn.close()

    after_bytes = _total_size(path)

    return CompactResult(
        before_bytes=before_bytes,
        after_bytes=after_bytes,
        saved_bytes=before_bytes - after_bytes,
    )


def _total_size(path: Path) -> int:
    """Sum the size of the DB file plus any WAL/SHM sidecars."""
    total = path.stat().st_size
    for suffix in ("-wal", "-shm"):
        sidecar = path.parent / (path.name + suffix)
        if sidecar.exists():
            total += sidecar.stat().st_size
    return total
