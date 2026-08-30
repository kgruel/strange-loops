"""Source inventory pass for pre-Arrival legacy stores.

Performs a strictly read-only inspection of a legacy store (jsonl-canonical or
sqlite-canonical), computing:
- Source format and line/row metrics;
- Per-kind row counts;
- Tick count and batch line count;
- Observer census (observer -> row count);
- Witness-order content hash (verifiable identity);
- Forensic file hash (raw byte sha256);
- ID era census across historical eras (canonical ULID, lowercase ULID, uuid4);
- GF-3 mixed-observer batch line refusal and absent-observer validation.

The inventory pass READS ONLY: it never creates files, never writes target
bytes, and never mutates the source.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .legacy_ids import classify_id_era
from .legacy_jsonl import (
    _SPEC,
    _load,
    _row_of,
    _validate,
    _validate_batch,
)
from .legacy_sqlite import (
    _content_sha256,
    _facts_have_signature,
    _tick_columns,
    open_legacy_sqlite,
)
from .refusals import AbsentObserverBatchRefused, MixedObserverBatchRefused

__all__ = [
    "SourceInventory",
    "inventory",
]


@dataclass(frozen=True)
class SourceInventory:
    """Census and forensic identity of a legacy store."""

    source_format: str
    total_lines: int
    per_kind_counts: dict[str, int]
    tick_count: int
    batch_line_count: int
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
        MixedObserverBatchRefused: If any batch line contains rows from > 1 observer (GF-3).
        AbsentObserverBatchRefused: If any batch line contains rows missing observer.
        JsonlCodecError: If a JSONL line violates codec schema.
    """
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Legacy source not found: {source_path}")

    file_bytes = source_path.read_bytes()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    if file_bytes.startswith(b"SQLite format 3\x00") or source_path.suffix in (".sqlite", ".db"):
        return _inventory_sqlite(source_path, file_hash)
    return _inventory_jsonl(source_path, file_hash)


def _inventory_sqlite(source_path: Path, file_hash: str) -> SourceInventory:
    conn = open_legacy_sqlite(source_path)
    try:
        content_hash = _content_sha256(conn)

        per_kind_counts: dict[str, int] = defaultdict(int)
        observer_census: dict[str, int] = defaultdict(int)
        id_era_census: dict[str, int] = {
            "canonical-ulid": 0,
            "lowercase-ulid": 0,
            "uuid4": 0,
        }

        sig_col = _facts_have_signature(conn)
        total_facts = 0
        for raw in conn.execute(
            "SELECT id, kind, ts, observer, origin, payload"
            + (", signature" if sig_col else "")
            + " FROM facts ORDER BY rowid"
        ):
            total_facts += 1
            fact_id = raw[0]
            kind = raw[1]
            observer = raw[3]

            per_kind_counts[kind] += 1
            if observer is not None:
                observer_census[observer] += 1
            era = classify_id_era(fact_id)
            id_era_census[era] += 1

        cols = _tick_columns(conn)
        ticks_cursor = conn.execute(
            f"SELECT {', '.join(cols)} FROM ticks ORDER BY rowid"
        )
        tick_count = len(ticks_cursor.fetchall())

        total_lines = total_facts + tick_count

        return SourceInventory(
            source_format="sqlite-canonical",
            total_lines=total_lines,
            per_kind_counts=dict(per_kind_counts),
            tick_count=tick_count,
            batch_line_count=0,
            observer_census=dict(observer_census),
            content_hash=content_hash,
            file_hash=file_hash,
            id_era_census=id_era_census,
        )
    finally:
        conn.close()


def _inventory_jsonl(source_path: Path, file_hash: str) -> SourceInventory:
    per_kind_counts: dict[str, int] = defaultdict(int)
    observer_census: dict[str, int] = defaultdict(int)
    id_era_census: dict[str, int] = {
        "canonical-ulid": 0,
        "lowercase-ulid": 0,
        "uuid4": 0,
    }

    total_lines = 0
    tick_count = 0
    batch_line_count = 0
    hasher = hashlib.sha256()

    mixed_observer_lines: list[tuple[int, tuple[str, ...]]] = []
    absent_observer_lines: list[tuple[int, tuple[str, ...]]] = []

    with source_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            total_lines += 1
            obj = _load(line)
            t = obj.get("t")

            if t == "fact":
                _validate(obj, _SPEC["fact"])
                row = _row_of(obj, _SPEC["fact"])
                row_for_hash = row if row[6] is not None else row[:6]
                hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())

                per_kind_counts[obj["kind"]] += 1
                if obj.get("observer") is not None:
                    observer_census[obj["observer"]] += 1
                era = classify_id_era(obj["id"])
                id_era_census[era] += 1

            elif t == "tick":
                _validate(obj, _SPEC["tick"])
                row = _row_of(obj, _SPEC["tick"])
                hasher.update(json.dumps(list(row), separators=(",", ":")).encode())
                tick_count += 1

            elif t == "batch":
                batch_line_count += 1
                rows = obj.get("rows")

                # GF-3 inventory pass checks:
                # Check for missing observer vs mixed observer across row bodies
                has_missing_observer = False
                observers_in_batch: set[str] = set()

                if isinstance(rows, list):
                    for r in rows:
                        if isinstance(r, dict):
                            if "observer" not in r or r["observer"] is None:
                                has_missing_observer = True
                            else:
                                observers_in_batch.add(r["observer"])

                if has_missing_observer:
                    absent_observer_lines.append((lineno, tuple(sorted(observers_in_batch))))
                    continue
                if len(observers_in_batch) > 1:
                    mixed_observer_lines.append((lineno, tuple(sorted(observers_in_batch))))
                    continue

                # Batch has single observer and valid observer fields:
                # validate structure and accumulate
                _validate_batch(obj)
                for elem in rows:
                    row = _row_of(elem, _SPEC["fact"])
                    row_for_hash = row if row[6] is not None else row[:6]
                    hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())

                    per_kind_counts[elem["kind"]] += 1
                    if "observer" in elem and elem["observer"] is not None:
                        observer_census[elem["observer"]] += 1
                    era = classify_id_era(elem["id"])
                    id_era_census[era] += 1

            else:
                from .legacy_jsonl import JsonlCodecError
                raise JsonlCodecError(f"unknown record discriminator t={t!r}")

    # Refusals fire after full source scan so every offending line is enumerated:
    if absent_observer_lines:
        raise AbsentObserverBatchRefused(
            offending_lines=absent_observer_lines,
            source=str(source_path),
        )
    if mixed_observer_lines:
        raise MixedObserverBatchRefused(
            offending_lines=mixed_observer_lines,
            source=str(source_path),
        )

    content_hash = hasher.hexdigest()

    return SourceInventory(
        source_format="jsonl-canonical",
        total_lines=total_lines,
        per_kind_counts=dict(per_kind_counts),
        tick_count=tick_count,
        batch_line_count=batch_line_count,
        observer_census=dict(observer_census),
        content_hash=content_hash,
        file_hash=file_hash,
        id_era_census=id_era_census,
    )
