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

The ``t`` discriminator is THIS framing's, and it stays. A line has nowhere
but the object itself to say which record class it carries; an arrival
record says it in the envelope's ``k``, so wire v1 drops ``t`` from arrival
bodies and :mod:`engine.arrival_body` frames the same rows without it
(decision:design/arrival-wire-v1-seam-triage). This module keeps ``t``
because it still has live consumers that need it: the derived ``.jsonl``
projection every last-0.x reader reads, and the migration sidecar that
reads historical logs. What the two framings share is the ROW domain —
:func:`row_object_fault`, exported for exactly that — so they cannot drift
about what a well-formed row is while disagreeing about how to frame one.

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
    "FACT_NULLABLE",
    "SIGNATURE_FIELD",
    "TICK_FIELDS",
    "TICK_CHAIN_FIELDS",
    "TICK_NULLABLE",
    "JsonlCodecError",
    "row_object_fault",
    "object_of_fact_row",
    "object_of_tick_row",
    "object_of_batch",
    "serialize_fact_row",
    "serialize_tick_row",
    "serialize_batch",
    "serialize_object",
    "deserialize_row",
    "deserialize_records",
    "records_from_object",
]


class JsonlCodecError(ValueError):
    """A JSONL line does not match the canonical schema."""


# Column order — the one spelling of it. ``engine.sqlite_store`` builds its
# INSERT statements from these tuples, so a schema column and a log field can
# never drift apart.
FACT_FIELDS = ("id", "kind", "ts", "observer", "origin", "payload")
_TICK_BASE_FIELDS = ("id", "name", "ts", "since", "origin", "payload")
# The chain columns, named as a group because a consumer that carries a tick
# ACROSS stores must null them — they are store-local custody — and would
# otherwise re-count them by hand. The codec owns the COUNT; whether to null
# them is the consumer's decision, not this module's.
TICK_CHAIN_FIELDS = ("prev_hash", "window_start", "fact_cursor", "window_hash")
TICK_FIELDS = (*_TICK_BASE_FIELDS, *TICK_CHAIN_FIELDS)
SIGNATURE_FIELD = "signature"
_SIGNATURE = SIGNATURE_FIELD

# Which fields of a row may be null, per row class. Named at module level —
# rather than inline in ``_SPEC`` — because they describe the SQLITE ROW, not
# this module's line framing: :mod:`engine.arrival_body` frames the same rows
# without a ``t`` discriminator and holds them to exactly this domain. One
# definition of "what a well-formed row is" is what keeps the two framings
# from drifting about it.
FACT_NULLABLE: frozenset[str] = frozenset()
TICK_NULLABLE: frozenset[str] = frozenset(("since", *TICK_CHAIN_FIELDS))

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
    "fact": _Spec("fact", FACT_FIELDS, FACT_NULLABLE),
    "tick": _Spec("tick", TICK_FIELDS, TICK_NULLABLE),
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


def object_of_fact_row(row: tuple) -> dict:
    """A fact row ``(id, kind, ts, observer, origin, payload[, signature])`` as
    its VALIDATED record object."""
    return _encode_obj(row, _SPEC["fact"])


def object_of_tick_row(row: tuple) -> dict:
    """A tick row (``_TICK_ROW_SQL`` order, signature optional) as its
    VALIDATED record object."""
    return _encode_obj(row, _SPEC["tick"])


def object_of_batch(rows: list[tuple]) -> dict:
    """A multi-row ceremony as ONE atomic record object.

    ``rows`` are fact row tuples in emission order. One row collapses to a
    plain fact object — a 1-row batch would be a second spelling of the same
    record (the "signature must be absent, not null" ethos), so the envelope
    exists only where multi-row atomicity does. Zero rows is a caller bug.

    Same both-directions symmetry as the scalar encoders: the built envelope
    is held to :func:`_validate_batch`, so a bad row fails at the append
    site instead of bricking every later open.
    """
    if not rows:
        raise JsonlCodecError("batch requires at least one fact row")
    if len(rows) == 1:
        return object_of_fact_row(rows[0])
    obj = {"t": _BATCH, _ROWS: [_encode_obj(r, _SPEC["fact"]) for r in rows]}
    # Structural half only: every row object just came out of _encode_obj,
    # which already ran the field-level _validate — re-running it per row
    # would be the same check twice on the same object.
    _validate_batch(obj, validate_rows=False)
    return obj


# The three serializers are their encoders composed with the dump, mirroring
# the decode side (``deserialize_records`` is the load composed with
# ``records_from_object``). A consumer that already holds — or wants — the
# OBJECT calls the encoder directly rather than dumping a line only to parse
# it straight back; an arrival record's ``body`` is exactly that object.


def serialize_fact_row(row: tuple) -> str:
    """Encode a fact row ``(id, kind, ts, observer, origin, payload[, signature])``."""
    return _dump(object_of_fact_row(row))


def serialize_tick_row(row: tuple) -> str:
    """Encode a tick row (``_TICK_ROW_SQL`` order, signature optional)."""
    return _dump(object_of_tick_row(row))


def serialize_batch(rows: list[tuple]) -> str:
    """Encode a multi-row ceremony as ONE atomic line — see
    :func:`object_of_batch`, whose object this dumps."""
    return _dump(object_of_batch(rows))


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


def row_object_fault(
    obj: dict,
    *,
    t: str,
    frame: str,
    fields: tuple[str, ...],
    allowed: frozenset[str],
    nullable: frozenset[str],
) -> str | None:
    """Why ``obj`` is not a well-formed row object, or None when it is.

    The half the two row framings SHARE. A ``.jsonl`` line and an arrival
    record's body carry the same sqlite row and differ only in where the
    record class is written — inside the object as ``"t"`` for a line, in
    the envelope's ``k`` for an arrival body — so the field domain is one
    rule with two callers rather than two rules that must be kept in step.
    ``allowed`` is exactly where they fork: the line framing admits ``t``
    and the arrival body does not (decision:design/arrival-wire-v1-seam-triage).

    Returns a fault string rather than raising, the shape
    :func:`engine.arrival._placement_fault` and
    :func:`engine.arrival._key_shape_fault` already use, so each framing
    raises its OWN error class over one set of rules. ``frame`` names the
    container in the two messages that mention it, so a body's refusal does
    not tell the reader to go looking for a line.
    """
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
            # Standards-valid JSON can still spell a number outside the JCS
            # domain (``1e999`` overflows to inf; a 400-digit integer exceeds
            # the safe-integer bound). Range-check here — the literal parser
            # only sees the NaN/Infinity spellings.
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
        # Absent IS the unsigned era; an explicit null is a second spelling
        # of the same state, so serialize stays the unique canonical form.
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
    """Hold a batch envelope to the structural rules — both directions.

    Two halves: the STRUCTURAL rules (envelope keys, ≥ 2 rows, fact records
    only — no nesting, no ticks — and no duplicate id) always run; the
    per-row FIELD validation (``_validate``) runs only when
    ``validate_rows`` — the deserialize path keeps it, the serialize path
    skips it because its row objects were just built (and validated) by
    ``_encode_obj``.
    """
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
        if validate_rows:
            _validate(elem, _SPEC["fact"])
        row_id = elem["id"]
        if row_id in seen_ids:
            raise JsonlCodecError(f"duplicate id {row_id!r} within one batch")
        seen_ids.add(row_id)


def _row_of(obj: dict, spec: _Spec) -> tuple:
    """A VALIDATED record object as its full-arity row tuple."""
    return (*(obj[f] for f in spec.fields), obj.get(_SIGNATURE))


def _ordered(obj: dict, spec: _Spec) -> dict:
    """A VALIDATED record object, rebuilt in canonical field order.

    Same shape :func:`_encode_obj` builds from a row tuple — discriminator,
    then the spec's fields in sqlite column order, then ``signature`` when
    the row carries one. Rebuilt rather than re-dumped as-received because
    key order in a decoded object is whatever its producer happened to use,
    and :func:`serialize_object` promises the bytes the row serializers
    produce.
    """
    out: dict = {"t": spec.t}
    out.update((field, obj[field]) for field in spec.fields)
    if obj.get(_SIGNATURE) is not None:
        out[_SIGNATURE] = obj[_SIGNATURE]
    return out


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

    Defined as the line decode composed with :func:`records_from_object`,
    so decoding still has exactly one dispatch.
    """
    return records_from_object(_load(line))


def records_from_object(obj: dict) -> list[tuple[str, tuple]]:
    """:func:`deserialize_records` on an ALREADY-DECODED object.

    An arrival record's ``body`` IS this codec's object for the row it
    carries, so a consumer holding one has nothing to parse — before this
    entry existed, ``arrival_store`` re-encoded the body just to hand a
    string back to the line decoder.

    The SAME validator runs: an object handed in is held to exactly the
    domain a line is held to. What a line has and an object cannot is a
    duplicate key, which the decode hook catches; everything downstream of
    that hook is shared.
    """
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


def serialize_object(obj: dict) -> str:
    """Encode an ALREADY-DECODED record object as one canonical line.

    Validated through :func:`records_from_object` — the same domain a line
    is held to — then dumped in canonical field order, so the result is
    byte-identical to the ``serialize_*`` call that produced the object.
    Field order is REBUILT rather than inherited: a decoded object's key
    order is its producer's, and this function's contract is about the
    codec's bytes, not the caller's dict.
    """
    records_from_object(obj)
    t = obj["t"]
    if t == _BATCH:
        fact = _SPEC["fact"]
        return _dump({"t": _BATCH, _ROWS: [_ordered(e, fact) for e in obj[_ROWS]]})
    return _dump(_ordered(obj, _SPEC[t]))
