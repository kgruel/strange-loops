"""Merge stores with ULID-based deduplication.

Uses ATTACH DATABASE + INSERT OR IGNORE for efficient cross-DB merge.
The ULID primary key is the globally unique identity — same fact in
two stores has the same ULID, so INSERT OR IGNORE skips duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._conn import _open


@dataclass(frozen=True)
class MergeResult:
    """Counts from a merge operation."""

    facts_added: int
    facts_skipped: int
    ticks_added: int
    ticks_skipped: int


def merge_store(
    target: Path,
    source: Path,
    *,
    dry_run: bool = False,
) -> MergeResult:
    """Merge source facts/ticks into target with deduplication.

    Dedup is INSERT OR IGNORE on ULID primary key.
    Same fact (same ULID) is silently skipped.
    New facts are appended.

    Args:
        target: Path to the target store database (receives new facts).
        source: Path to the source store database (provides facts).
        dry_run: If True, compute counts but roll back all changes.

    Returns:
        MergeResult with counts of added and skipped facts/ticks.

    Raises:
        FileNotFoundError: If either database does not exist.
    """
    target = Path(target)
    source = Path(source)

    if not target.exists():
        raise FileNotFoundError(f"Target store not found: {target}")
    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")

    conn = _open(target)
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))

        src_facts = conn.execute("SELECT COUNT(*) FROM src.facts").fetchone()[0]
        src_ticks = conn.execute("SELECT COUNT(*) FROM src.ticks").fetchone()[0]

        if dry_run:
            conn.execute("SAVEPOINT merge_dry_run")

        # Merge facts — INSERT OR IGNORE dedup on ULID PK
        conn.execute("""
            INSERT OR IGNORE INTO facts (id, kind, ts, observer, origin, payload)
            SELECT id, kind, ts, observer, origin, payload
            FROM src.facts
        """)
        facts_added = conn.execute("SELECT changes()").fetchone()[0]

        # Merge ticks — same pattern
        conn.execute("""
            INSERT OR IGNORE INTO ticks (id, name, ts, since, origin, payload)
            SELECT id, name, ts, since, origin, payload
            FROM src.ticks
        """)
        ticks_added = conn.execute("SELECT changes()").fetchone()[0]

        if dry_run:
            conn.execute("ROLLBACK TO merge_dry_run")
            conn.execute("RELEASE merge_dry_run")
        else:
            conn.commit()

        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()

    return MergeResult(
        facts_added=facts_added,
        facts_skipped=src_facts - facts_added,
        ticks_added=ticks_added,
        ticks_skipped=src_ticks - ticks_added,
    )
