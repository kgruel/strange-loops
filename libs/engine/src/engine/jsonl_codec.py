"""jsonl_codec — the line codec for the canonical JSONL store.

One interleaved append-only log per store (``.loops/data/<name>.jsonl``);
each line is a JSON object carrying a ``"t"`` discriminator (``"fact"`` or
``"tick"``) plus the persisted row fields, in sqlite column order.

The load-bearing invariant (design/architecture/jsonl-canonical-store):
**payload rides as the VERBATIM stored TEXT string** — a JSON string value,
never re-serialized, never parsed by this codec. Every commitment hash in
``engine.sqlite_store`` (``_fact_row_hash``, ``_fact_commitment_hash``,
``_tick_envelope``/``_tick_row_hash``) embeds payload verbatim, so a line
round-tripped through this codec re-derives byte-identical hashes and every
existing signature keeps verifying.

Era handling mirrors the era-aware hashers exactly. All commitment fields
are always present (``null`` when the row holds NULL — pre-chain ticks); the
``signature`` key is emitted only when the row carries one, which is precisely
the condition under which the hashers fold it into the envelope. A 6-tuple
fact row and a 7-tuple row with ``signature=None`` therefore hash identically
and serialize identically; deserializers return the full-arity tuple (7 fact
fields / 11 tick fields) with ``None`` filled in.

Unknown, missing, or mistyped fields are rejected loudly
(:class:`JsonlCodecError`) — explicit over implicit. A store's canonical log
is not a place for silent tolerance.
"""

from __future__ import annotations

import json
import math

__all__ = [
    "JsonlCodecError",
    "serialize_fact_row",
    "serialize_tick_row",
    "deserialize_fact_row",
    "deserialize_tick_row",
    "deserialize_row",
]


class JsonlCodecError(ValueError):
    """A JSONL line does not match the canonical schema."""


# Column order — mirrors _FACT_ROW_SQL / _TICK_ROW_SQL in sqlite_store.
_FACT_FIELDS = ("id", "kind", "ts", "observer", "origin", "payload")
_TICK_FIELDS = (
    "id", "name", "ts", "since", "origin", "payload",
    "prev_hash", "window_start", "fact_cursor", "window_hash",
)
_SIGNATURE = "signature"

_FACT_KEYS = frozenset((*_FACT_FIELDS, _SIGNATURE, "t"))
_TICK_KEYS = frozenset((*_TICK_FIELDS, _SIGNATURE, "t"))

# Nullable commitment fields, by record type.
_FACT_NULLABLE: frozenset[str] = frozenset()
_TICK_NULLABLE = frozenset(
    ("since", "prev_hash", "window_start", "fact_cursor", "window_hash")
)

_NUMERIC = ("ts", "since")

# JCS (RFC 8785) numeric domain — mirrors rfc8785._impl._INT_MIN/_INT_MAX.
# Integers outside it, and non-finite floats, are not canonicalizable, so a
# line carrying one cannot be hashed: reject at the codec gate rather than
# detonating inside the commitment hashers.
_JCS_INT_MAX = 2**53 - 1
_JCS_INT_MIN = -(2**53) + 1


def _dump(obj: dict) -> str:
    """Encode one line. ensure_ascii keeps lines 7-bit and free of raw
    U+2028/U+2029; allow_nan=False refuses non-JSON floats explicitly;
    separators drop insignificant whitespace. Key order is the dict's
    insertion order — sqlite column order — not sorted: this is a transport
    encoding, not a canonicalization (JCS lives in the hashers)."""
    return json.dumps(obj, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":"))


def _row_dict(row: tuple, fields: tuple[str, ...], t: str) -> dict:
    n = len(fields)
    if len(row) not in (n, n + 1):
        raise JsonlCodecError(
            f"{t} row must have {n} or {n + 1} fields, got {len(row)}"
        )
    obj: dict = {"t": t}
    obj.update(zip(fields, row[:n], strict=True))
    if len(row) > n and row[n] is not None:
        obj[_SIGNATURE] = row[n]
    return obj


def serialize_fact_row(row: tuple) -> str:
    """Encode a fact row ``(id, kind, ts, observer, origin, payload[, signature])``."""
    return _dump(_row_dict(row, _FACT_FIELDS, "fact"))


def serialize_tick_row(row: tuple) -> str:
    """Encode a tick row (``_TICK_ROW_SQL`` order, signature optional)."""
    return _dump(_row_dict(row, _TICK_FIELDS, "tick"))


def _reject_constant(name: str) -> None:
    """Refuse the non-JSON literals ``NaN``/``Infinity``/``-Infinity``.

    Serialization uses ``allow_nan=False``, so these can never be emitted;
    admitting them on read would let a corrupt line past the codec gate and
    detonate later inside the JCS commitment hashers (or land a NaN ``ts``
    in sqlite). Reject at the boundary — explicit over implicit.
    """
    raise JsonlCodecError(f"non-JSON literal {name!r} is not permitted")


def _load(line: str) -> dict:
    try:
        obj = json.loads(line, parse_constant=_reject_constant)
    except ValueError as exc:
        raise JsonlCodecError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise JsonlCodecError(
            f"line must be a JSON object, got {type(obj).__name__}"
        )
    return obj


def _validate(obj: dict, fields: tuple[str, ...], allowed: frozenset[str],
              nullable: frozenset[str], t: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise JsonlCodecError(f"unknown field(s) in {t} line: {unknown}")
    missing = [f for f in fields if f not in obj]
    if missing:
        raise JsonlCodecError(f"missing field(s) in {t} line: {missing}")
    for field in fields:
        value = obj[field]
        if value is None:
            if field not in nullable:
                raise JsonlCodecError(f"{t} field {field!r} must not be null")
            continue
        if field in _NUMERIC:
            # bool is an int subclass — reject it explicitly.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise JsonlCodecError(
                    f"{t} field {field!r} must be a number, got "
                    f"{type(value).__name__}"
                )
            # Standards-valid JSON can still spell a number outside the JCS
            # domain (``1e999`` overflows to inf; a 400-digit integer exceeds
            # the safe-integer bound). Range-check here — the literal parser
            # only sees the NaN/Infinity spellings.
            if isinstance(value, float):
                if not math.isfinite(value):
                    raise JsonlCodecError(
                        f"{t} field {field!r} must be a finite number, got "
                        f"{value!r}"
                    )
            elif not (_JCS_INT_MIN <= value <= _JCS_INT_MAX):
                raise JsonlCodecError(
                    f"{t} field {field!r} is outside the JCS safe-integer "
                    f"domain: {value}"
                )
        elif not isinstance(value, str):
            raise JsonlCodecError(
                f"{t} field {field!r} must be a string, got "
                f"{type(value).__name__}"
            )
    if _SIGNATURE in obj and obj[_SIGNATURE] is None:
        # Absent IS the unsigned era; an explicit null is a second spelling
        # of the same state, so serialize stays the unique canonical form.
        raise JsonlCodecError(
            f"{t} field 'signature' must be absent, not null, when unsigned"
        )
    sig = obj.get(_SIGNATURE)
    if sig is not None and not isinstance(sig, str):
        raise JsonlCodecError(
            f"{t} field 'signature' must be a string, got {type(sig).__name__}"
        )


def _row_tuple(obj: dict, fields: tuple[str, ...]) -> tuple:
    return (*(obj[f] for f in fields), obj.get(_SIGNATURE))


def deserialize_fact_row(line: str) -> tuple:
    """Decode a ``"t":"fact"`` line to a 7-field row tuple (signature last)."""
    obj = _load(line)
    if obj.get("t") != "fact":
        raise JsonlCodecError(f"expected t='fact', got {obj.get('t')!r}")
    _validate(obj, _FACT_FIELDS, _FACT_KEYS, _FACT_NULLABLE, "fact")
    return _row_tuple(obj, _FACT_FIELDS)


def deserialize_tick_row(line: str) -> tuple:
    """Decode a ``"t":"tick"`` line to an 11-field row tuple (signature last)."""
    obj = _load(line)
    if obj.get("t") != "tick":
        raise JsonlCodecError(f"expected t='tick', got {obj.get('t')!r}")
    _validate(obj, _TICK_FIELDS, _TICK_KEYS, _TICK_NULLABLE, "tick")
    return _row_tuple(obj, _TICK_FIELDS)


def deserialize_row(line: str) -> tuple[str, tuple]:
    """Decode any line, dispatching on ``"t"``. Returns ``(t, row)``."""
    obj = _load(line)
    t = obj.get("t")
    if t == "fact":
        _validate(obj, _FACT_FIELDS, _FACT_KEYS, _FACT_NULLABLE, "fact")
        return "fact", _row_tuple(obj, _FACT_FIELDS)
    if t == "tick":
        _validate(obj, _TICK_FIELDS, _TICK_KEYS, _TICK_NULLABLE, "tick")
        return "tick", _row_tuple(obj, _TICK_FIELDS)
    raise JsonlCodecError(f"unknown record discriminator t={t!r}")
