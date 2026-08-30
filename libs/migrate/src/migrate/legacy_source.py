"""Validated row-stream layer for pre-Arrival legacy stores.

Consolidates legacy store reading and validation into ONE shared stream layer
consumed by both :func:`migrate.inventory.inventory` and
:func:`migrate.transform.transform`.

Ruled Source Order:
- JSONL arm (``jsonl-canonical``): yields units in source line order (1..N).
- SQLite arm (``sqlite-canonical``): yields all fact units in witness (rowid) order,
  followed by all tick units in witness (rowid) order.

Validation Guarantees:
- Every yielded unit (:class:`FlatFactUnit`, :class:`BatchUnit`, :class:`TickUnit`)
  is structurally and semantically valid per the frozen legacy grammar.
- Defective legacy sources (codec violations, mixed-observer batch envelopes [GF-3],
  or absent/empty observer cohorts) are accumulated across the entire source and
  refused with :class:`LegacySourceRefused`.
- No raw exceptions (:class:`engine.arrival_body.ArrivalBodyError`,
  :class:`migrate.legacy_jsonl.JsonlCodecError`, :class:`KeyError`, :class:`TypeError`)
  escape the public inventory/transform surfaces.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .legacy_ids import FactRow
from .legacy_jsonl import (
    _BATCH,
    _BATCH_KEYS,
    _MIN_BATCH_ROWS,
    _ROWS,
    _SPEC,
    FACT_FIELDS,
    FACT_NULLABLE,
    TICK_FIELDS,
    TICK_NULLABLE,
    JsonlCodecError,
    _load,
    _row_of,
    row_object_fault,
)
from .legacy_sqlite import (
    _facts_have_signature,
    _tick_columns,
    open_legacy_sqlite,
)
from .refusals import LegacySourceRefused

__all__ = [
    "FlatFactUnit",
    "BatchUnit",
    "TickUnit",
    "LegacyUnit",
    "LegacySource",
]


@dataclass(frozen=True)
class FlatFactUnit:
    """One validated flat fact row."""

    coordinate: int
    row: FactRow


@dataclass(frozen=True)
class BatchUnit:
    """One validated single-observer batch group (intact, in intra-group source order)."""

    coordinate: int
    rows: tuple[FactRow, ...]
    observer: str


@dataclass(frozen=True)
class TickUnit:
    """One validated tick record."""

    coordinate: int
    id: str
    name: str
    ts: float
    since: float | None
    origin: str
    payload: str
    prev_hash: str | None = None
    window_start: str | None = None
    fact_cursor: str | None = None
    window_hash: str | None = None
    signature: str | None = None

    @property
    def tuple_form(self) -> tuple:
        """11-element tuple representation matching body_of_tick_row expectations."""
        return (
            self.id,
            self.name,
            self.ts,
            self.since,
            self.origin,
            self.payload,
            self.prev_hash,
            self.window_start,
            self.fact_cursor,
            self.window_hash,
            self.signature,
        )


LegacyUnit = FlatFactUnit | BatchUnit | TickUnit


@dataclass(frozen=True)
class LegacySource:
    """A validated legacy source stream."""

    source_path: Path
    source_format: str
    total_lines: int | None
    batch_line_count: int | None
    file_hash: str
    content_hash: str
    units: tuple[LegacyUnit, ...]

    @classmethod
    def read(cls, source: Path | str) -> LegacySource:
        """Open, validate, and parse a legacy source store.

        Raises:
            FileNotFoundError: If source does not exist.
            LegacySourceRefused: If source contains any defects across codec,
                mixed-observer, or absent-or-empty observer classes.
        """
        source_path = Path(source).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Legacy source not found: {source_path}")

        file_bytes = source_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        if file_bytes.startswith(b"SQLite format 3\x00"):
            return cls._read_sqlite(source_path, file_hash)
        return cls._read_jsonl(source_path, file_hash)

    @classmethod
    def _read_jsonl(cls, source_path: Path, file_hash: str) -> LegacySource:
        codec_invalid_lines: list[tuple[int, str]] = []
        mixed_observer_lines: list[tuple[int, tuple[str, ...], int]] = []
        absent_observer_lines: list[tuple[int, int, tuple[str, ...], dict[str, int]]] = []
        units: list[LegacyUnit] = []
        content_hasher = hashlib.sha256()

        total_lines = 0
        batch_line_count = 0

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
                        skip_fields=frozenset({"observer"}),
                    )
                    if fault is not None:
                        codec_invalid_lines.append((lineno, fault))
                        continue

                    if "observer" not in obj or obj["observer"] is None or obj["observer"] == "":
                        spelling = "empty" if obj.get("observer") == "" else "missing"
                        absent_observer_lines.append((lineno, 1, (), {spelling: 1}))
                        continue

                    obs = obj["observer"]
                    if not isinstance(obs, str):
                        codec_invalid_lines.append(
                            (lineno, f"fact field 'observer' must be a string, got {type(obs).__name__}")
                        )
                        continue

                    row = _row_of(obj, _SPEC["fact"])
                    row_for_hash = row if row[6] is not None else row[:6]
                    content_hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())

                    fr = FactRow(
                        id=obj["id"],
                        kind=obj["kind"],
                        ts=obj["ts"],
                        observer=obs,
                        origin=obj["origin"],
                        payload=obj["payload"],
                        signature=obj.get("signature"),
                    )
                    units.append(FlatFactUnit(coordinate=lineno, row=fr))

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
                    content_hasher.update(json.dumps(list(row), separators=(",", ":")).encode())

                    tu = TickUnit(
                        coordinate=lineno,
                        id=obj["id"],
                        name=obj["name"],
                        ts=obj["ts"],
                        since=obj.get("since"),
                        origin=obj["origin"],
                        payload=obj["payload"],
                        prev_hash=obj.get("prev_hash"),
                        window_start=obj.get("window_start"),
                        fact_cursor=obj.get("fact_cursor"),
                        window_hash=obj.get("window_hash"),
                        signature=obj.get("signature"),
                    )
                    units.append(tu)

                elif t == _BATCH:
                    batch_line_count += 1

                    unknown_env = sorted(set(obj) - _BATCH_KEYS)
                    if unknown_env:
                        codec_invalid_lines.append((lineno, f"unknown field(s) in batch line: {unknown_env}"))
                        continue

                    rows = obj.get(_ROWS)
                    if not isinstance(rows, list):
                        codec_invalid_lines.append(
                            (lineno, f"batch field 'rows' must be an array of fact records, got {type(rows).__name__}")
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

                    batch_fault: str | None = None
                    seen_ids: set[str] = set()
                    absent_count = 0
                    spelling_counts: dict[str, int] = {"empty": 0, "missing": 0}
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

                        fault = row_object_fault(
                            elem,
                            t="fact",
                            frame="line",
                            fields=FACT_FIELDS,
                            allowed=_SPEC["fact"].allowed,
                            nullable=FACT_NULLABLE,
                            skip_fields=frozenset({"observer"}),
                        )
                        if fault is not None:
                            batch_fault = fault
                            break

                        if "observer" not in elem or elem["observer"] is None or elem["observer"] == "":
                            absent_count += 1
                            spelling = "empty" if elem.get("observer") == "" else "missing"
                            spelling_counts[spelling] += 1
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

                    if len(present_observers) > 1:
                        mixed_observer_lines.append(
                            (lineno, tuple(sorted(present_observers)), absent_count)
                        )
                        continue

                    if absent_count > 0:
                        non_zero_spellings = {k: v for k, v in spelling_counts.items() if v > 0}
                        absent_observer_lines.append(
                            (lineno, absent_count, tuple(sorted(present_observers)), non_zero_spellings)
                        )
                        continue

                    batch_obs = next(iter(present_observers))
                    batch_rows: list[FactRow] = []
                    for elem in rows:
                        row = _row_of(elem, _SPEC["fact"])
                        row_for_hash = row if row[6] is not None else row[:6]
                        content_hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())
                        batch_rows.append(
                            FactRow(
                                id=elem["id"],
                                kind=elem["kind"],
                                ts=elem["ts"],
                                observer=elem["observer"],
                                origin=elem["origin"],
                                payload=elem["payload"],
                                signature=elem.get("signature"),
                            )
                        )
                    units.append(BatchUnit(coordinate=lineno, rows=tuple(batch_rows), observer=batch_obs))

                else:
                    codec_invalid_lines.append((lineno, f"unknown record discriminator t={t!r}"))
                    continue

        if codec_invalid_lines or mixed_observer_lines or absent_observer_lines:
            raise LegacySourceRefused(
                codec_invalid_lines=codec_invalid_lines,
                mixed_observer_lines=mixed_observer_lines,
                absent_observer_lines=absent_observer_lines,
                source=str(source_path),
            )

        return cls(
            source_path=source_path,
            source_format="jsonl-canonical",
            total_lines=total_lines,
            batch_line_count=batch_line_count,
            file_hash=file_hash,
            content_hash=content_hasher.hexdigest(),
            units=tuple(units),
        )

    @classmethod
    def _read_sqlite(cls, source_path: Path, file_hash: str) -> LegacySource:
        conn = open_legacy_sqlite(source_path)
        try:
            codec_invalid_lines: list[tuple[int, str]] = []
            mixed_observer_lines: list[tuple[int, tuple[str, ...], int]] = []
            absent_observer_lines: list[tuple[int, int, tuple[str, ...], dict[str, int]]] = []
            units: list[LegacyUnit] = []
            content_hasher = hashlib.sha256()

            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "facts" in tables:
                sig_col = _facts_have_signature(conn)
                query_facts = (
                    "SELECT rowid, id, kind, ts, observer, origin, payload"
                    + (", signature" if sig_col else "")
                    + " FROM facts ORDER BY rowid"
                )
                for raw in conn.execute(query_facts):
                    rowid = raw[0]
                    fact_id, kind, ts, observer, origin, payload = raw[1:7]
                    sig = raw[7] if sig_col else None

                    obj = {
                        "id": fact_id,
                        "kind": kind,
                        "ts": ts,
                        "origin": origin,
                        "payload": payload,
                    }
                    if sig is not None:
                        obj["signature"] = sig

                    fault = row_object_fault(
                        obj,
                        t="fact",
                        frame="row",
                        fields=FACT_FIELDS,
                        allowed=_SPEC["fact"].allowed,
                        nullable=FACT_NULLABLE,
                        skip_fields=frozenset({"observer"}),
                    )

                    if fault is not None:
                        codec_invalid_lines.append((rowid, fault))
                        continue

                    if observer is None or observer == "":
                        spelling = "empty" if observer == "" else "missing"
                        absent_observer_lines.append((rowid, 1, (), {spelling: 1}))
                        continue

                    if not isinstance(observer, str):
                        codec_invalid_lines.append(
                            (rowid, f"fact field 'observer' must be a string, got {type(observer).__name__}")
                        )
                        continue

                    row_tuple = (fact_id, kind, ts, observer, origin, payload, sig)
                    row_for_hash = row_tuple if (sig_col and sig is not None) else row_tuple[:6]
                    content_hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())

                    fr = FactRow(
                        id=fact_id,
                        kind=kind,
                        ts=ts,
                        observer=observer,
                        origin=origin,
                        payload=payload,
                        signature=sig,
                    )
                    units.append(FlatFactUnit(coordinate=rowid, row=fr))

            if "ticks" in tables:
                cols = _tick_columns(conn)
                if cols:
                    query_ticks = f"SELECT rowid, {', '.join(cols)} FROM ticks ORDER BY rowid"
                    for raw in conn.execute(query_ticks):
                        rowid = raw[0]
                        t_dict = dict(zip(cols, raw[1:], strict=True))
                        obj = {f: t_dict.get(f) for f in TICK_FIELDS}
                        if t_dict.get("signature") is not None:
                            obj["signature"] = t_dict["signature"]

                        fault = row_object_fault(
                            obj,
                            t="tick",
                            frame="row",
                            fields=TICK_FIELDS,
                            allowed=_SPEC["tick"].allowed,
                            nullable=TICK_NULLABLE,
                        )

                        if fault is not None:
                            codec_invalid_lines.append((rowid, fault))
                            continue

                        row_for_hash = tuple(raw[1:])
                        content_hasher.update(json.dumps(list(row_for_hash), separators=(",", ":")).encode())

                        tu = TickUnit(
                            coordinate=rowid,
                            id=t_dict["id"],
                            name=t_dict["name"],
                            ts=t_dict["ts"],
                            since=t_dict.get("since"),
                            origin=t_dict["origin"],
                            payload=t_dict["payload"],
                            prev_hash=t_dict.get("prev_hash"),
                            window_start=t_dict.get("window_start"),
                            fact_cursor=t_dict.get("fact_cursor"),
                            window_hash=t_dict.get("window_hash"),
                            signature=t_dict.get("signature"),
                        )
                        units.append(tu)

            if codec_invalid_lines or mixed_observer_lines or absent_observer_lines:
                raise LegacySourceRefused(
                    codec_invalid_lines=codec_invalid_lines,
                    mixed_observer_lines=mixed_observer_lines,
                    absent_observer_lines=absent_observer_lines,
                    source=str(source_path),
                )

            return cls(
                source_path=source_path,
                source_format="sqlite-canonical",
                total_lines=None,
                batch_line_count=None,
                file_hash=file_hash,
                content_hash=content_hasher.hexdigest(),
                units=tuple(units),
            )
        finally:
            conn.close()
