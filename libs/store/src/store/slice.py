"""Filtered store export — extract a subset of facts/ticks into a standalone DB.

Uses ATTACH DATABASE for efficient cross-DB INSERT...SELECT without
round-tripping through Python. ULIDs are preserved — same fact keeps
same identity across slices.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._conn import _create, _open


@dataclass(frozen=True)
class SliceResult:
    """Counts from a slice operation."""

    facts: int
    ticks: int
    size_bytes: int


def slice_store(
    source: Path,
    target: Path,
    *,
    since: float | None = None,
    before: float | None = None,
    kinds: list[str] | None = None,
    observers: list[str] | None = None,
    origins: list[str] | None = None,
) -> SliceResult:
    """Export filtered facts/ticks into a standalone store.

    Uses ATTACH DATABASE for efficient cross-DB INSERT...SELECT.
    ULIDs are preserved — same fact keeps same identity across slices.

    Args:
        source: Path to the source store database.
        target: Path to write the sliced database.
        since: Include facts/ticks with ts >= since.
        before: Include facts/ticks with ts < before.
        kinds: Include facts matching these kinds (exact or prefix).
            e.g. kinds=["ui"] matches "ui", "ui.key", "ui.action".
        observers: Include facts from these observers.
        origins: Include facts from these origins.

    Returns:
        SliceResult with counts and size.

    Raises:
        FileNotFoundError: If source database does not exist.
        FileExistsError: If target already exists.
    """
    source = Path(source)
    target = Path(target)

    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")

    # Create target with canonical schema
    target_conn = _create(target)
    target_conn.close()

    # Open source, attach target, copy
    conn = _open(source)
    try:
        conn.execute("ATTACH DATABASE ? AS slice", (str(target),))

        where, params = _build_where(since=since, before=before, kinds=kinds,
                                     observers=observers, origins=origins)

        # Copy facts
        fact_sql = f"INSERT INTO slice.facts SELECT * FROM facts{where}"
        conn.execute(fact_sql, params)
        fact_count = conn.execute(
            f"SELECT COUNT(*) FROM slice.facts"
        ).fetchone()[0]

        # Copy ticks — filtered by time range only (kinds/observers don't apply)
        tick_where, tick_params = _build_where(since=since, before=before)
        tick_sql = f"INSERT INTO slice.ticks SELECT * FROM ticks{tick_where}"
        conn.execute(tick_sql, tick_params)
        tick_count = conn.execute(
            f"SELECT COUNT(*) FROM slice.ticks"
        ).fetchone()[0]

        conn.commit()
        conn.execute("DETACH DATABASE slice")
    finally:
        conn.close()

    size_bytes = target.stat().st_size
    return SliceResult(facts=fact_count, ticks=tick_count, size_bytes=size_bytes)


def _build_where(
    *,
    since: float | None = None,
    before: float | None = None,
    kinds: list[str] | None = None,
    observers: list[str] | None = None,
    origins: list[str] | None = None,
) -> tuple[str, list]:
    """Build WHERE clause and params from filter arguments.

    Kind matching supports both exact and prefix: kinds=["ui"] matches
    "ui" exactly and anything starting with "ui." (e.g. "ui.key").
    """
    clauses: list[str] = []
    params: list = []

    if since is not None:
        clauses.append("ts >= ?")
        params.append(since)

    if before is not None:
        clauses.append("ts < ?")
        params.append(before)

    if kinds:
        kind_clauses = []
        for kind in kinds:
            kind_clauses.append("(kind = ? OR kind LIKE ? || '.%')")
            params.extend([kind, kind])
        clauses.append("(" + " OR ".join(kind_clauses) + ")")

    if observers:
        placeholders = ", ".join(["?"] * len(observers))
        clauses.append(f"observer IN ({placeholders})")
        params.extend(observers)

    if origins:
        placeholders = ", ".join(["?"] * len(origins))
        clauses.append(f"origin IN ({placeholders})")
        params.extend(origins)

    if not clauses:
        return "", []

    return " WHERE " + " AND ".join(clauses), params
