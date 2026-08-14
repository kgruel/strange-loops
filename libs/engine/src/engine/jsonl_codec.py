"""jsonl_codec — the line codec for the canonical JSONL store.

One interleaved append-only log per store (``.loops/data/<name>.jsonl``);
each line is a JSON object carrying a ``"t"`` discriminator (``"fact"``,
``"tick"``, or the ``"batch"`` envelope for multi-row ceremonies) plus the
persisted row fields, in sqlite column order.

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
is not a place for silent tolerance. So is a duplicate key: JSON's last-wins
resolution would let one line carry two ids and a reader silently pick one.

The rules run in **both** directions from one function. ``serialize`` holds
its object to the same domain ``deserialize`` enforces, so ``serialize(x)``
is always decodable — a wrongly typed field fails at the append site, where
it is attributable, rather than becoming a durable line that bricks every
later open.
"""

from __future__ import annotations

import json
import math

__all__ = [
    "FACT_FIELDS",
    "TICK_FIELDS",
    "JsonlCodecError",
    "serialize_fact_row",
    "serialize_tick_row",
    "serialize_batch",
    "deserialize_row",
    "deserialize_records",
]


class JsonlCodecError(ValueError):
    """A JSONL line does not match the canonical schema."""


# Column order — the one spelling of it. ``engine.sqlite_store`` builds its
# INSERT statements from these tuples, so a schema column and a log field can
# never drift apart.
FACT_FIELDS = ("id", "kind", "ts", "observer", "origin", "payload")
TICK_FIELDS = (
    "id", "name", "ts", "since", "origin", "payload",
    "prev_hash", "window_start", "fact_cursor", "window_hash",
)
_SIGNATURE = "signature"

_NUMERIC = ("ts", "since")


class _Spec:
    """Everything the codec knows about one record type, keyed by ``"t"``.

    Fact and tick differ only in their field tuple and which fields may be
    null; both directions of both types then run one code path, so a rule
    added here cannot apply to one type and be forgotten for the other.
    """

    __slots__ = ("t", "fields", "allowed", "nullable")

    def __init__(self, t: str, fields: tuple[str, ...], nullable: frozenset[str]):
        self.t = t
        self.fields = fields
        self.allowed = frozenset((*fields, _SIGNATURE, "t"))
        self.nullable = nullable


_SPEC = {
    "fact": _Spec("fact", FACT_FIELDS, frozenset()),
    "tick": _Spec(
        "tick",
        TICK_FIELDS,
        frozenset(("since", "prev_hash", "window_start", "fact_cursor", "window_hash")),
    ),
}

# The third record type is STRUCTURAL, not field-shaped, so it does not fit
# _Spec: a ``"t":"batch"`` envelope carries ``rows`` — an array of ≥ 2
# ordinary fact record objects, each validated against ``_SPEC["fact"]`` in
# full (verbatim payload TEXT per row, so signatures and commitment hashes
# survive round-trip unchanged). One line is the log's atomicity unit, so a
# batch is how a multi-row ceremony (absorb_edit) lands atomically.
# Structural rules (design:architecture/jsonl-declaration-ceremony-encoding):
# no ticks inside (ticks are minted one-at-a-time and chain-linked), no
# nested batches, no duplicate id within one batch (otherwise a dup only
# surfaces three layers away as a rebuild-time PK collision), no envelope
# key besides t/rows. Same-ts across rows is deliberately NOT a codec rule
# (D1): it is the declaration ceremony's invariant, enforced by absorb_edit
# and asserted by audit_deep — baking it in here would block future
# batch-emit reuse with distinct ts.
_BATCH = "batch"
_ROWS = "rows"
_BATCH_KEYS = frozenset(("t", _ROWS))
_MIN_BATCH_ROWS = 2

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


def _encode_obj(row: tuple, spec: _Spec) -> dict:
    """Build the line object for a row — and hold it to the decoder's rules.

    ``serialize(x)`` must always be decodable. Checking arity alone let a
    row with a *typed*-wrong field through: a fact carrying ``ts="1.0"``
    (a string, which sqlite's REAL affinity accepts) got a durable JSONL
    receipt, and then every subsequent open failed on decode — the store
    bricked by a line its own serializer wrote. Running the decoder's
    :func:`_validate` over the object before dumping makes the two
    directions symmetric by construction rather than by parallel
    maintenance, and puts the error at the append site, where it is
    attributable to the caller that built the row.
    """
    n = len(spec.fields)
    if len(row) not in (n, n + 1):
        raise JsonlCodecError(
            f"{spec.t} row must have {n} or {n + 1} fields, got {len(row)}"
        )
    obj: dict = {"t": spec.t}
    obj.update(zip(spec.fields, row[:n], strict=True))
    if len(row) > n and row[n] is not None:
        obj[_SIGNATURE] = row[n]
    _validate(obj, spec)
    return obj


def serialize_fact_row(row: tuple) -> str:
    """Encode a fact row ``(id, kind, ts, observer, origin, payload[, signature])``."""
    return _dump(_encode_obj(row, _SPEC["fact"]))


def serialize_tick_row(row: tuple) -> str:
    """Encode a tick row (``_TICK_ROW_SQL`` order, signature optional)."""
    return _dump(_encode_obj(row, _SPEC["tick"]))


def serialize_batch(rows: list[tuple]) -> str:
    """Encode a multi-row ceremony as ONE atomic line.

    ``rows`` are fact row tuples in emission order. One row collapses to a
    plain fact line — a 1-row batch would be a second spelling of the same
    record (the "signature must be absent, not null" ethos), so the envelope
    exists only where multi-row atomicity does. Zero rows is a caller bug.

    Same both-directions symmetry as the scalar serializers: the built
    envelope is held to :func:`_validate_batch` before dumping, so a bad row
    fails at the append site instead of bricking every later open.
    """
    if not rows:
        raise JsonlCodecError("batch requires at least one fact row")
    if len(rows) == 1:
        return serialize_fact_row(rows[0])
    obj = {"t": _BATCH, "rows": [_encode_obj(r, _SPEC["fact"]) for r in rows]}
    _validate_batch(obj)
    return _dump(obj)


def _reject_constant(name: str) -> None:
    """Refuse the non-JSON literals ``NaN``/``Infinity``/``-Infinity``.

    Serialization uses ``allow_nan=False``, so these can never be emitted;
    admitting them on read would let a corrupt line past the codec gate and
    detonate later inside the JCS commitment hashers (or land a NaN ``ts``
    in sqlite). Reject at the boundary — explicit over implicit.
    """
    raise JsonlCodecError(f"non-JSON literal {name!r} is not permitted")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """Build the object, refusing a key spelled twice.

    ``json.loads`` resolves duplicates last-wins, so ``"id":"A","id":"B"``
    decodes as ``B`` — two different lines with two different meanings that
    a reader silently collapses to one. A canonical log admits exactly one
    spelling per record; ambiguity is corruption, not a parse detail.
    """
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise JsonlCodecError(f"duplicate key {key!r} in line")
        obj[key] = value
    return obj


def _load(line: str) -> dict:
    try:
        obj = json.loads(
            line, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys
        )
    except JsonlCodecError:
        # Raised by our own hooks — already the right error, with the right
        # message. Re-wrapping it as "not valid JSON" would bury the reason.
        raise
    except ValueError as exc:
        raise JsonlCodecError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise JsonlCodecError(
            f"line must be a JSON object, got {type(obj).__name__}"
        )
    return obj


def _validate(obj: dict, spec: _Spec) -> None:
    t = spec.t
    unknown = sorted(set(obj) - spec.allowed)
    if unknown:
        raise JsonlCodecError(f"unknown field(s) in {t} line: {unknown}")
    missing = [f for f in spec.fields if f not in obj]
    if missing:
        raise JsonlCodecError(f"missing field(s) in {t} line: {missing}")
    for field in spec.fields:
        value = obj[field]
        if value is None:
            if field not in spec.nullable:
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


def _validate_batch(obj: dict) -> None:
    """Hold a batch envelope to the structural rules — both directions."""
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
    seen_ids: set = set()
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
        _validate(elem, _SPEC["fact"])
        row_id = elem["id"]
        if row_id in seen_ids:
            raise JsonlCodecError(f"duplicate id {row_id!r} within one batch")
        seen_ids.add(row_id)


def _row_of(obj: dict, spec: _Spec) -> tuple:
    """A VALIDATED record object as its full-arity row tuple."""
    return (*(obj[f] for f in spec.fields), obj.get(_SIGNATURE))


def deserialize_row(line: str) -> tuple[str, tuple]:
    """Decode a SINGLE-record line, dispatching on ``"t"``. Returns
    ``(t, row)`` with the row at full arity (7 fact fields / 11 tick fields,
    signature last). A ``"t":"batch"`` line carries several records and is
    refused here — decode it with :func:`deserialize_records`.

    Defined AS :func:`deserialize_records` plus the multi-record refusal
    (a valid batch always expands to ≥ 2 rows), so decoding has exactly
    one dispatch."""
    records = deserialize_records(line)
    if len(records) > 1:
        raise JsonlCodecError(
            "batch line carries multiple records — decode with "
            "deserialize_records, not deserialize_row"
        )
    return records[0]


def deserialize_records(line: str) -> list[tuple[str, tuple]]:
    """Decode ANY line into its record sequence, in on-the-wire order.

    A plain fact/tick line yields one ``(t, row)``; a batch line yields its
    inner rows expanded in array order (always ≥ 2 — so ``len > 1`` is
    exactly "this line was a batch"). This is the decode every log consumer
    (replay, catch-up, rebuild, audit) reads through, so batch expansion has
    one spelling.
    """
    obj = _load(line)
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
