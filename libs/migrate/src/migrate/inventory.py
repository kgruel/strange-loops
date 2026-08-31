"""Source inventory pass for pre-Arrival legacy stores.

Performs a strictly read-only inspection of a legacy store (jsonl-canonical or
sqlite-canonical), computing:
- Source format and line/row metrics;
- Per-kind row counts;
- Tick count and batch line count;
- Observer census (observer -> row count);
- Witness-order content hash (verifiable identity);
- Forensic file hash (raw byte sha256);
- ID era census across historical eras (canonical ULID, lowercase ULID, other);
- GF-3 mixed-observer batch line refusal, absent-observer batch line refusal,
  and codec-invalid line detection.

The inventory pass READS ONLY: it never creates files, never writes target
bytes, and never mutates the source.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .legacy_ids import classify_id_era
from .legacy_source import BatchUnit, FlatFactUnit, LegacySource, TickUnit

__all__ = [
    "SourceInventory",
    "inventory",
]


@dataclass(frozen=True)
class SourceInventory:
    """Census and forensic identity of a legacy store.

    Attributes:
        source_format: 'jsonl-canonical' or 'sqlite-canonical'.
        total_rows: Total committed fact and tick rows across all lines/tables.
        total_lines: Total lines in source (JSONL only; None for SQLite because
            lines are not a concept SQLite format has — absent-is-not-zero).
        per_kind_counts: Map from kind string to row count.
        tick_count: Total tick rows.
        batch_line_count: Count of batch lines (JSONL only; None for SQLite
            because legacy SQLite cannot represent batch envelopes — absent-is-not-zero).
        observer_census: Map from observer string to row count.
        content_hash: SAME-FORMAT row-content identity only (verifiable witness-order SHA-256).
            JSONL arm hashes rows in line order (facts, ticks, and batch rows in envelope order).
            It does NOT witness batch grouping (a 2-row batch and the same rows
            flat hash identically) and is NOT comparable across formats. Migration
            equivalence rests on the re-run diff (WP3), never on comparing these
            hashes across a format change.
        file_hash: Forensic raw file byte SHA-256.
        id_era_census: Census across ID eras ('canonical-ulid', 'lowercase-ulid', 'other').
    """

    source_format: str
    total_rows: int
    total_lines: int | None
    per_kind_counts: dict[str, int]
    tick_count: int
    batch_line_count: int | None
    observer_census: dict[str, int]
    content_hash: str
    file_hash: str
    id_era_census: dict[str, int]

    @property
    def source_content_sha256(self) -> str:
        """Alias for verifiable witness-order content hash."""
        return self.content_hash

    @property
    def source_file_sha256(self) -> str:
        """Alias for forensic file hash."""
        return self.file_hash

    @property
    def per_kind_row_counts(self) -> dict[str, int]:
        """Alias for per-kind counts."""
        return self.per_kind_counts


def inventory(source: Path | str) -> SourceInventory:
    """Perform a read-only inventory pass over a legacy source store.

    Args:
        source: Path to legacy .jsonl or .sqlite store.

    Returns:
        SourceInventory with counts, censuses, and cryptographic hashes.

    Raises:
        FileNotFoundError: If the source does not exist.
        MigrationRefused: If the source contains codec-invalid lines, GF-3 mixed-observer
            batch lines, or absent/empty-observer lines.
    """
    src = LegacySource.read(source)

    per_kind_counts: dict[str, int] = defaultdict(int)
    observer_census: dict[str, int] = defaultdict(int)
    id_era_census: dict[str, int] = {
        "canonical-ulid": 0,
        "lowercase-ulid": 0,
        "other": 0,
    }
    total_rows = 0
    tick_count = 0

    for unit in src.units:
        if isinstance(unit, FlatFactUnit):
            total_rows += 1
            per_kind_counts[unit.row.kind] += 1
            observer_census[unit.row.observer] += 1
            era = classify_id_era(unit.row.id)
            id_era_census[era] += 1
        elif isinstance(unit, BatchUnit):
            total_rows += len(unit.rows)
            for row in unit.rows:
                per_kind_counts[row.kind] += 1
                observer_census[row.observer] += 1
                era = classify_id_era(row.id)
                id_era_census[era] += 1
        elif isinstance(unit, TickUnit):
            total_rows += 1
            tick_count += 1

    return SourceInventory(
        source_format=src.source_format,
        total_rows=total_rows,
        total_lines=src.total_lines,
        per_kind_counts=dict(per_kind_counts),
        tick_count=tick_count,
        batch_line_count=src.batch_line_count,
        observer_census=dict(observer_census),
        content_hash=src.content_hash,
        file_hash=src.file_hash,
        id_era_census=id_era_census,
    )
