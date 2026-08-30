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

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .legacy_ids import classify_id_era
from .legacy_jsonl import (
    _BATCH,
    _BATCH_KEYS,
    _JCS_INT_MAX,
    _JCS_INT_MIN,
    _MIN_BATCH_ROWS,
    _ROWS,
    _SPEC,
    FACT_FIELDS,
    FACT_NULLABLE,
    SIGNATURE_FIELD,
    TICK_FIELDS,
    TICK_NULLABLE,
    JsonlCodecError,
    _load,
    _row_of,
    row_object_fault,
)
from .legacy_sqlite import (
    _content_sha256,
    _facts_have_signature,
    _tick_columns,
    open_legacy_sqlite,
)
from .refusals import (
    LegacySourceRefused,
    MigrationRefused,
)

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
            SQLite arm hashes all facts in rowid order, then all ticks in rowid order.
            It does NOT witness batch grouping (a 2-row batch and the same rows flat hash identically)
            and is NOT comparable across formats. Migration equivalence rests on the re-run diff
            (WP3), never on comparing these hashes across a format change.
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
            batch lines, or absent-observer batch lines.
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
            "other": 0,
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

        total_rows = total_facts + tick_count

        return SourceInventory(
            source_format="sqlite-canonical",
            total_rows=total_rows,
            total_lines=None,
            per_kind_counts=dict(per_kind_counts),
            tick_count=tick_count,
            batch_line_count=None,
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
        "other": 0,
    }

    total_rows = 0
    total_lines = 0
    tick_count = 0
    batch_line_count = 0
    hasher = hashlib.sha256()

    codec_invalid_lines: list[tuple[int, str]] = []
    mixed_observer_lines: list[tuple[int, tuple[str, ...], int]] = []
    absent_observer_lines: list[tuple[int, int, tuple[str, ...]]] = []

    with source_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            total_lines += 1
            try:
                obj = _load(line)
            except JsonlCodecError as exc:
                codec_invalid_lines.append((lineno, str(exc)))
                continue

            t = obj.get("t")

            if t == "fact":
                fault = row_object_fault(
                    obj,
                    t="fact",
                    frame="line",
                    fields=FACT_FIELDS,
                    allowed=_SPEC["fact"].allowed,
                    nullable=FACT_NULLABLE,
                )
                if fault is not None:
                    codec_invalid_lines.append((lineno, fault))
                    continue

                row = _row_of(obj, _SPEC["fact"])
                row_for_hash = row if row[6] is not None else row[:6]
                hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())

                per_kind_counts[obj["kind"]] += 1
                if obj.get("observer") is not None:
                    observer_census[obj["observer"]] += 1
                era = classify_id_era(obj["id"])
                id_era_census[era] += 1
                total_rows += 1

            elif t == "tick":
                fault = row_object_fault(
                    obj,
                    t="tick",
                    frame="line",
                    fields=TICK_FIELDS,
                    allowed=_SPEC["tick"].allowed,
                    nullable=TICK_NULLABLE,
                )
                if fault is not None:
                    codec_invalid_lines.append((lineno, fault))
                    continue

                row = _row_of(obj, _SPEC["tick"])
                hasher.update(json.dumps(list(row), separators=(",", ":")).encode())
                tick_count += 1
                total_rows += 1

            elif t == _BATCH:
                batch_line_count += 1

                # 1. Validate envelope
                unknown_env = sorted(set(obj) - _BATCH_KEYS)
                if unknown_env:
                    codec_invalid_lines.append((lineno, f"unknown field(s) in batch line: {unknown_env}"))
                    continue

                rows = obj.get(_ROWS)
                if not isinstance(rows, list):
                    codec_invalid_lines.append(
                        (
                            lineno,
                            f"batch field 'rows' must be an array of fact records, got {type(rows).__name__}",
                        )
                    )
                    continue

                if len(rows) < _MIN_BATCH_ROWS:
                    codec_invalid_lines.append(
                        (
                            lineno,
                            f"batch must carry at least {_MIN_BATCH_ROWS} rows, got {len(rows)} — "
                            "a 1-row batch is a second spelling of a plain fact line, and an empty one encodes nothing",
                        )
                    )
                    continue

                # 2. Validate batch rows FIRST (precondition for observer decisions)
                batch_fault: str | None = None
                seen_ids: set[str] = set()
                absent_count = 0
                present_observers: set[str] = set()

                for i, elem in enumerate(rows):
                    if not isinstance(elem, dict):
                        batch_fault = f"batch row {i} must be a JSON object, got {type(elem).__name__}"
                        break

                    elem_t = elem.get("t")
                    if elem_t == _BATCH:
                        batch_fault = f"batch row {i} is a nested batch — batches do not nest"
                        break
                    if elem_t == "tick":
                        batch_fault = (
                            f"batch row {i} is a tick record — ticks are minted "
                            "one-at-a-time and chain-linked, never batched"
                        )
                        break
                    if elem_t != "fact":
                        batch_fault = f"batch row {i} has unknown record discriminator t={elem_t!r}"
                        break

                    elem_unknown = sorted(set(elem) - _SPEC["fact"].allowed)
                    if elem_unknown:
                        batch_fault = f"unknown field(s) in fact line: {elem_unknown}"
                        break

                    req_fields = ("id", "kind", "ts", "origin", "payload")
                    missing_req = [f for f in req_fields if f not in elem]
                    if missing_req:
                        batch_fault = f"missing field(s) in fact line: {missing_req}"
                        break

                    if not isinstance(elem["id"], str):
                        batch_fault = f"fact field 'id' must be a string, got {type(elem['id']).__name__}"
                        break
                    if not isinstance(elem["kind"], str):
                        batch_fault = f"fact field 'kind' must be a string, got {type(elem['kind']).__name__}"
                        break

                    ts_val = elem["ts"]
                    if isinstance(ts_val, bool) or not isinstance(ts_val, (int, float)):
                        batch_fault = f"fact field 'ts' must be a number, got {type(ts_val).__name__}"
                        break
                    if isinstance(ts_val, float):
                        if not math.isfinite(ts_val):
                            batch_fault = f"fact field 'ts' must be a finite number, got {ts_val!r}"
                            break
                    elif not (_JCS_INT_MIN <= ts_val <= _JCS_INT_MAX):
                        batch_fault = f"fact field 'ts' is outside the JCS safe-integer domain: {ts_val}"
                        break

                    if not isinstance(elem["origin"], str):
                        batch_fault = f"fact field 'origin' must be a string, got {type(elem['origin']).__name__}"
                        break
                    if not isinstance(elem["payload"], str):
                        batch_fault = f"fact field 'payload' must be a string, got {type(elem['payload']).__name__}"
                        break

                    if SIGNATURE_FIELD in elem:
                        sig_val = elem[SIGNATURE_FIELD]
                        if sig_val is None:
                            batch_fault = "fact field 'signature' must be absent, not null, when unsigned"
                            break
                        if not isinstance(sig_val, str):
                            batch_fault = f"fact field 'signature' must be a string, got {type(sig_val).__name__}"
                            break

                    # Observer field checking: missing vs typed string
                    if "observer" not in elem or elem["observer"] is None:
                        absent_count += 1
                    else:
                        obs_val = elem["observer"]
                        if not isinstance(obs_val, str):
                            batch_fault = f"fact field 'observer' must be a string, got {type(obs_val).__name__}"
                            break
                        present_observers.add(obs_val)

                    row_id = elem["id"]
                    if row_id in seen_ids:
                        batch_fault = f"duplicate id {row_id!r} within one batch"
                        break
                    seen_ids.add(row_id)

                if batch_fault is not None:
                    codec_invalid_lines.append((lineno, batch_fault))
                    continue

                # 3. Classify observer condition classes
                if len(present_observers) > 1:
                    mixed_observer_lines.append(
                        (lineno, tuple(sorted(present_observers)), absent_count)
                    )
                    continue

                if absent_count > 0:
                    absent_observer_lines.append(
                        (lineno, absent_count, tuple(sorted(present_observers)))
                    )
                    continue

                # 4. Valid single-observer batch line
                for elem in rows:
                    row = _row_of(elem, _SPEC["fact"])
                    row_for_hash = row if row[6] is not None else row[:6]
                    hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())

                    per_kind_counts[elem["kind"]] += 1
                    if "observer" in elem and elem["observer"] is not None:
                        observer_census[elem["observer"]] += 1
                    era = classify_id_era(elem["id"])
                    id_era_census[era] += 1
                    total_rows += 1

            else:
                codec_invalid_lines.append((lineno, f"unknown record discriminator t={t!r}"))
                continue

    # Refusals fire after full scan across all 3 classes:
    if codec_invalid_lines or mixed_observer_lines or absent_observer_lines:
        raise LegacySourceRefused(
            codec_invalid_lines=codec_invalid_lines,
            mixed_observer_lines=mixed_observer_lines,
            absent_observer_lines=absent_observer_lines,
            source=str(source_path),
        )

    content_hash = hasher.hexdigest()

    return SourceInventory(
        source_format="jsonl-canonical",
        total_rows=total_rows,
        total_lines=total_lines,
        per_kind_counts=dict(per_kind_counts),
        tick_count=tick_count,
        batch_line_count=batch_line_count,
        observer_census=dict(observer_census),
        content_hash=content_hash,
        file_hash=file_hash,
        id_era_census=id_era_census,
    )
