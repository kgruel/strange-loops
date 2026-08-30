"""Legacy JSONL reader — frozen decode surface for canonical JSONL stores.

Historical artifact copied from ``engine.jsonl_codec`` at commit
``affe92a6fc1a034b477cbc068cc563f6e5ca69e6``.

One interleaved append-only log per legacy store (``.loops/data/<name>.jsonl``);
each line is a JSON object carrying a ``"t"`` discriminator (``"fact"``,
``"tick"``, or the ``"batch"`` envelope for multi-row ceremonies) plus the
persisted row fields, in sqlite column order.

This module provides the READ-ONLY decoding surface for migration. All encode
paths have been stripped. Legacy ``body.t`` discriminator knowledge quarantines
here.
"""

from __future__ import annotations

import json
import math

__all__ = [
    "FACT_FIELDS",
    "FACT_NULLABLE",
    "SIGNATURE_FIELD",
    "TICK_FIELDS",
    "TICK_CHAIN_FIELDS",
    "TICK_NULLABLE",
    "JsonlCodecError",
    "row_object_fault",
    "deserialize_row",
    "deserialize_records",
    "records_from_object",
    "load_line",
]


class JsonlCodecError(ValueError):
    """A JSONL line does not match the canonical schema."""


# Column order — in sqlite column order.
FACT_FIELDS = ("id", "kind", "ts", "observer", "origin", "payload")
_TICK_BASE_FIELDS = ("id", "name", "ts", "since", "origin", "payload")
TICK_CHAIN_FIELDS = ("prev_hash", "window_start", "fact_cursor", "window_hash")
TICK_FIELDS = (*_TICK_BASE_FIELDS, *TICK_CHAIN_FIELDS)
SIGNATURE_FIELD = "signature"
_SIGNATURE = SIGNATURE_FIELD

FACT_NULLABLE: frozenset[str] = frozenset()
TICK_NULLABLE: frozenset[str] = frozenset(("since", *TICK_CHAIN_FIELDS))

_NUMERIC = ("ts", "since")


class _Spec:
    """Everything the codec knows about one record type, keyed by ``"t"``.

    Fact and tick differ only in their field tuple and which fields may be
    null; both decode through the same code path.
    """

    __slots__ = ("t", "fields", "allowed", "nullable")

    def __init__(self, t: str, fields: tuple[str, ...], nullable: frozenset[str]):
        self.t = t
        self.fields = fields
        self.allowed = frozenset((*fields, _SIGNATURE, "t"))
        self.nullable = nullable


_SPEC = {
    "fact": _Spec("fact", FACT_FIELDS, FACT_NULLABLE),
    "tick": _Spec("tick", TICK_FIELDS, TICK_NULLABLE),
}

_BATCH = "batch"
_ROWS = "rows"
_BATCH_KEYS = frozenset(("t", _ROWS))
_MIN_BATCH_ROWS = 2

# JCS (RFC 8785) numeric domain
_JCS_INT_MAX = 2**53 - 1
_JCS_INT_MIN = -(2**53) + 1


def _reject_constant(name: str) -> None:
    """Refuse the non-JSON literals ``NaN``/``Infinity``/``-Infinity``."""
    raise JsonlCodecError(f"non-JSON literal {name!r} is not permitted")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """Build the object, refusing a key spelled twice."""
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise JsonlCodecError(f"duplicate key {key!r} in line")
        obj[key] = value
    return obj


def load_line(line: str) -> dict:
    """Parse a single JSONL line into a dictionary with strict validation."""
    try:
        obj = json.loads(
            line, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys
        )
    except JsonlCodecError:
        raise
    except ValueError as exc:
        raise JsonlCodecError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise JsonlCodecError(
            f"line must be a JSON object, got {type(obj).__name__}"
        )
    return obj


_load = load_line


def row_object_fault(
    obj: dict,
    *,
    t: str,
    frame: str,
    fields: tuple[str, ...],
    allowed: frozenset[str],
    nullable: frozenset[str],
) -> str | None:
    """Why ``obj`` is not a well-formed row object, or None when it is."""
    unknown = sorted(set(obj) - allowed)
    if unknown:
        return f"unknown field(s) in {t} {frame}: {unknown}"
    missing = [f for f in fields if f not in obj]
    if missing:
        return f"missing field(s) in {t} {frame}: {missing}"
    for field in fields:
        value = obj[field]
        if value is None:
            if field not in nullable:
                return f"{t} field {field!r} must not be null"
            continue
        if field in _NUMERIC:
            # bool is an int subclass — reject it explicitly.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return (
                    f"{t} field {field!r} must be a number, got "
                    f"{type(value).__name__}"
                )
            if isinstance(value, float):
                if not math.isfinite(value):
                    return (
                        f"{t} field {field!r} must be a finite number, got "
                        f"{value!r}"
                    )
            elif not (_JCS_INT_MIN <= value <= _JCS_INT_MAX):
                return (
                    f"{t} field {field!r} is outside the JCS safe-integer "
                    f"domain: {value}"
                )
        elif not isinstance(value, str):
            return (
                f"{t} field {field!r} must be a string, got "
                f"{type(value).__name__}"
            )
    if SIGNATURE_FIELD in obj and obj[SIGNATURE_FIELD] is None:
        return f"{t} field 'signature' must be absent, not null, when unsigned"
    sig = obj.get(SIGNATURE_FIELD)
    if sig is not None and not isinstance(sig, str):
        return f"{t} field 'signature' must be a string, got {type(sig).__name__}"
    return None


def _validate(obj: dict, spec: _Spec) -> None:
    fault = row_object_fault(
        obj,
        t=spec.t,
        frame="line",
        fields=spec.fields,
        allowed=spec.allowed,
        nullable=spec.nullable,
    )
    if fault is not None:
        raise JsonlCodecError(fault)


def _validate_batch(obj: dict, *, validate_rows: bool = True) -> None:
    """Hold a batch envelope to structural rules."""
    unknown = sorted(set(obj) - _BATCH_KEYS)
    if unknown:
        raise JsonlCodecError(f"unknown field(s) in batch line: {unknown}")
    rows = obj.get(_ROWS)
    if not isinstance(rows, list):
        raise JsonlCodecError(
            "batch field 'rows' must be an array of fact records, got "
            f"{type(rows).__name__}"
        )
    if len(rows) < _MIN_BATCH_ROWS:
        raise JsonlCodecError(
            f"batch must carry at least {_MIN_BATCH_ROWS} rows, got "
            f"{len(rows)} — a 1-row batch is a second spelling of a plain "
            "fact line, and an empty one encodes nothing"
        )
    seen_ids: set[str] = set()
    for i, elem in enumerate(rows):
        if not isinstance(elem, dict):
            raise JsonlCodecError(
                f"batch row {i} must be a JSON object, got {type(elem).__name__}"
            )
        t = elem.get("t")
        if t == _BATCH:
            raise JsonlCodecError(f"batch row {i} is a nested batch — batches do not nest")
        if t == "tick":
            raise JsonlCodecError(
                f"batch row {i} is a tick record — ticks are minted "
                "one-at-a-time and chain-linked, never batched"
            )
        if t != "fact":
            raise JsonlCodecError(f"batch row {i} has unknown record discriminator t={t!r}")
        if validate_rows:
            _validate(elem, _SPEC["fact"])
        row_id = elem["id"]
        if row_id in seen_ids:
            raise JsonlCodecError(f"duplicate id {row_id!r} within one batch")
        seen_ids.add(row_id)


def _row_of(obj: dict, spec: _Spec) -> tuple:
    """A validated record object as its full-arity row tuple."""
    return (*(obj[f] for f in spec.fields), obj.get(_SIGNATURE))


def deserialize_row(line: str) -> tuple[str, tuple]:
    """Decode a single-record line, dispatching on ``"t"``.

    Returns ``(t, row)`` with the row at full arity (7 fact fields / 11 tick fields,
    signature last). A ``"t":"batch"`` line carries several records and is
    refused here — decode it with :func:`deserialize_records`.
    """
    records = deserialize_records(line)
    if len(records) > 1:
        raise JsonlCodecError(
            "batch line carries multiple records — decode with "
            "deserialize_records, not deserialize_row"
        )
    return records[0]


def deserialize_records(line: str) -> list[tuple[str, tuple]]:
    """Decode any line into its record sequence, in on-the-wire order."""
    return records_from_object(load_line(line))


def records_from_object(obj: dict) -> list[tuple[str, tuple]]:
    """Decode an already-decoded record object into a sequence of ``(t, row)``."""
    if not isinstance(obj, dict):
        raise JsonlCodecError(
            f"record must be a JSON object, got {type(obj).__name__}"
        )
    t = obj.get("t")
    if t == _BATCH:
        _validate_batch(obj)
        fact = _SPEC["fact"]
        return [("fact", _row_of(elem, fact)) for elem in obj[_ROWS]]
    spec = _SPEC.get(t) if isinstance(t, str) else None
    if spec is None:
        raise JsonlCodecError(f"unknown record discriminator t={t!r}")
    _validate(obj, spec)
    return [(spec.t, _row_of(obj, spec))]
