"""arrival_body — the body grammar for arrival records.

An arrival record's ``body`` is one committed store row — or, for a batch,
the rows of one declaration ceremony — as a JSON object. It is deliberately
NOT :mod:`engine.jsonl_codec`'s object for the same row, and the difference
is one field.

Why the fork
------------
A ``.jsonl`` line has nowhere but the object itself to say which record
class it carries, so the line codec writes a ``"t"`` discriminator inside
it. An arrival record already answers that question in its envelope's
``k``, and the projection site holds ``k`` when it hands the body over. A
body carrying ``t`` is therefore the record class spelled twice, with
nothing keeping the two spellings honest — a record could claim ``k:"tick"``
around a body claiming ``t:"fact"``, and every reader would have to pick a
side. Wire v1 drops ``body.t``
(decision:design/arrival-wire-v1-seam-triage).

The drop is enforced BY THE GRAMMAR, not tolerated and not detected: ``t``
is simply absent from the allowed field set, so a body still carrying it is
refused by the same unknown-field rule that refuses any other stray key.
There is no compat mode and nothing to sniff for — the full break has no
``.arrival`` store to be compatible with, which is the whole reason the
seam could be closed at all.

What is shared, and what is not
-------------------------------
The ROW domain is shared: the field tuples, which fields may be null, and
their type rules describe a sqlite row and belong to neither framing. They
arrive here as :func:`engine.jsonl_codec.row_object_fault` so the two
encodings cannot drift about what a well-formed row is. The line codec
keeps its own ``t`` untouched — it still frames the derived ``.jsonl``
projection (:func:`engine.arrival_projection.line_of_record`) and it is
what the migration sidecar reads out of historical logs.

The BATCH grammar is not shared, and one rule is the reason: all rows in a
batch record share one observer (ruling 4 of the seam triage). The
envelope's observer is read off row 0 and selects the key that signs an
outer commitment covering every row, so a mixed-observer batch would have
one author attesting to another's facts. That is a wire-grammar refusal at
the ARRIVAL seam and nowhere else: adding it to the line codec would hold
historical ``.jsonl`` logs to a rule that did not exist when they were
written, and turn a migration into a refusal.

**The load-bearing invariant is the line codec's, unchanged: payload rides
as the VERBATIM stored TEXT string**, a JSON string value, never
re-serialized and never parsed here. Every inner commitment hash embeds it
that way, so a row round-tripped through this module re-derives
byte-identical hashes and every existing fact signature keeps verifying.
Nothing this module changed is covered by an inner signature:
``_fact_commitment_hash`` is (kind, ts, observer, origin, payload) and
never named ``t``.
"""

from __future__ import annotations

from .jsonl_codec import (
    FACT_FIELDS,
    FACT_NULLABLE,
    SIGNATURE_FIELD,
    TICK_FIELDS,
    TICK_NULLABLE,
    row_object_fault,
)

__all__ = [
    "BATCH_KIND",
    "FACT_KIND",
    "TICK_KIND",
    "ROW_KINDS",
    "ArrivalBodyError",
    "body_of_batch",
    "body_of_fact_row",
    "body_of_tick_row",
    "legacy_object_of_body",
    "rows_of_body",
]


class ArrivalBodyError(ValueError):
    """An arrival record's body does not match the wire v1 grammar.

    Its own family, not the line codec's: a caller that catches this is
    reasoning about an arrival record, and the two framings now refuse
    different things (a body carrying ``t``, a batch spanning observers).
    Sharing one exception name would make those refusals indistinguishable
    from a legacy line's.
    """


FACT_KIND = "fact"
TICK_KIND = "tick"
BATCH_KIND = "batch"

# The record classes that carry rows. The structural kinds (genesis, key
# introduction) have bodies that are not row objects at all, and never reach
# this module — :func:`engine.arrival_projection._projects` is where that
# split is decided, once, for every consumer.
ROW_KINDS = frozenset((FACT_KIND, TICK_KIND, BATCH_KIND))

_ROWS = "rows"
_BATCH_KEYS = frozenset((_ROWS,))
_MIN_BATCH_ROWS = 2

# Per row class: the fields, in sqlite column order, and which of them may be
# null. ``allowed`` is fields + signature and NOTHING ELSE — no ``t``. That
# omission is the wire v1 ruling, and it is why a t-carrying body is refused
# without a line of code that mentions ``t``.
_FIELDS = {FACT_KIND: FACT_FIELDS, TICK_KIND: TICK_FIELDS}
_NULLABLE = {FACT_KIND: FACT_NULLABLE, TICK_KIND: TICK_NULLABLE}
_ALLOWED = {
    kind: frozenset((*fields, SIGNATURE_FIELD)) for kind, fields in _FIELDS.items()
}


def _bad(message: str):
    raise ArrivalBodyError(message)


def _row_fault(obj: object, kind: str) -> str | None:
    """Why ``obj`` is not a well-formed ``kind`` body, or None when it is."""
    if not isinstance(obj, dict):
        return f"{kind} body must be a JSON object, got {type(obj).__name__}"
    return row_object_fault(
        obj,
        t=kind,
        frame="body",
        fields=_FIELDS[kind],
        allowed=_ALLOWED[kind],
        nullable=_NULLABLE[kind],
    )


def _validate_row(obj: object, kind: str) -> None:
    fault = _row_fault(obj, kind)
    if fault is not None:
        _bad(fault)


def _row_of(obj: dict, kind: str) -> tuple:
    """A VALIDATED body as its full-arity row tuple, signature last."""
    return (*(obj[f] for f in _FIELDS[kind]), obj.get(SIGNATURE_FIELD))


def _encode(row: tuple, kind: str) -> dict:
    """Build the body for a row — and hold it to the decoder's rules.

    ``encode(x)`` must always be decodable, the line codec's symmetry and
    for its reason: a row with a *typed*-wrong field (a fact carrying
    ``ts="1.0"``, which sqlite's REAL affinity accepts) would otherwise get
    a durable arrival record its own reader then refuses. Validating the
    built object puts the error at the append site, where it is
    attributable to the caller that assembled the row.
    """
    fields = _FIELDS[kind]
    n = len(fields)
    if len(row) not in (n, n + 1):
        _bad(f"{kind} row must have {n} or {n + 1} fields, got {len(row)}")
    body: dict = dict(zip(fields, row[:n], strict=True))
    if len(row) > n and row[n] is not None:
        body[SIGNATURE_FIELD] = row[n]
    _validate_row(body, kind)
    return body


def body_of_fact_row(row: tuple) -> dict:
    """A fact row ``(id, kind, ts, observer, origin, payload[, signature])``
    as its VALIDATED arrival body."""
    return _encode(row, FACT_KIND)


def body_of_tick_row(row: tuple) -> dict:
    """A tick row (``_TICK_ROW_SQL`` order, signature optional) as its
    VALIDATED arrival body."""
    return _encode(row, TICK_KIND)


def body_of_batch(rows: list[tuple]) -> dict:
    """A multi-row ceremony as ONE record's VALIDATED arrival body.

    ``rows`` are fact row tuples in emission order, two or more. A single
    row does NOT collapse to a fact body here: the caller that has one row
    is already choosing ``k="fact"`` for the envelope, and a collapse would
    be this module deciding a record's kind behind it.
    """
    body = {_ROWS: [_encode(r, FACT_KIND) for r in rows]}
    # Structural half only: every row object just came out of _encode, which
    # already ran the field-level check.
    _validate_batch(body, validate_rows=False)
    return body


def _validate_batch(body: object, *, validate_rows: bool = True) -> None:
    """Hold a batch body to the structural rules — both directions.

    Two halves. The STRUCTURAL rules always run: envelope keys, at least
    two rows, every row a well-formed fact, no duplicate id within the
    batch, and ONE OBSERVER ACROSS THE BATCH. The per-row FIELD validation
    runs only when ``validate_rows`` — the decode path keeps it, the encode
    path skips it because its rows were just built and validated.

    Note what is NOT here and cannot be: the line codec refuses a nested
    batch and a tick-inside-a-batch by reading each row's ``t``. Without a
    discriminator there is no such claim to refuse — a nested batch is an
    object with an unknown ``rows`` field and a tick is an object with
    unknown ``name``/``since`` fields, and both fail the fact rules on
    exactly those grounds. The refusals did not weaken; they stopped being
    a separate rule.
    """
    if not isinstance(body, dict):
        _bad(f"batch body must be a JSON object, got {type(body).__name__}")
    unknown = sorted(set(body) - _BATCH_KEYS)
    if unknown:
        _bad(f"unknown field(s) in batch body: {unknown}")
    rows = body.get(_ROWS)
    if not isinstance(rows, list):
        _bad(
            "batch field 'rows' must be an array of fact bodies, got "
            f"{type(rows).__name__}"
        )
    if len(rows) < _MIN_BATCH_ROWS:
        _bad(
            f"batch must carry at least {_MIN_BATCH_ROWS} rows, got "
            f"{len(rows)} — a 1-row batch is a second spelling of a plain "
            "fact record, and an empty one encodes nothing"
        )
    seen_ids: set = set()
    for i, elem in enumerate(rows):
        if validate_rows:
            fault = _row_fault(elem, FACT_KIND)
            if fault is not None:
                _bad(f"batch row {i}: {fault}")
        row_id = elem["id"]
        if row_id in seen_ids:
            _bad(f"duplicate id {row_id!r} within one batch")
        seen_ids.add(row_id)
    _refuse_mixed_observers(rows)


def _refuse_mixed_observers(rows: list[dict]) -> None:
    """Refuse a batch whose rows do not share one observer.

    Ruling 4 of decision:design/arrival-wire-v1-seam-triage, and a
    construction rule rather than a detection one. The record's envelope
    observer is read off row 0, and that value selects the key that signs
    an outer commitment covering EVERY row — so a batch spanning two
    observers would have row 0's author attesting to another author's
    facts. The envelope's row-0 read is honest exactly because this refusal
    exists; without it the invariant lived only in the shape of the call
    chain that happened to assemble every row against one observer
    variable, which is a property no reader of the wire format can check.

    One function, called on both the encode and the decode path, because a
    grammar rule that holds in one direction is a rule a determined caller
    routes around.
    """
    observers = {row["observer"] for row in rows}
    if len(observers) > 1:
        _bad(
            f"batch rows span {len(observers)} observers "
            f"({', '.join(sorted(repr(o) for o in observers))}) — every row "
            "in a batch record shares one observer, because the record's "
            "envelope names row 0's and its signature covers them all. A "
            "multi-observer ceremony is not one record."
        )


def rows_of_body(k: str, body: object) -> list[tuple[str, tuple]]:
    """The store rows one arrival body expands to, in on-the-wire order.

    Dispatches on the ENVELOPE's ``k``, which is the whole point of dropping
    ``t``: the record class is stated once, by the record, and the body is
    read as whatever the envelope already said it is. A ``fact`` or ``tick``
    yields one ``(t, row)``; a ``batch`` yields its rows expanded in array
    order (always two or more).

    The returned ``t`` is the ROW class, so a batch's rows come back as
    ``"fact"`` — callers index rows, and a batch is an atomicity envelope,
    not a row class.
    """
    if k == BATCH_KIND:
        _validate_batch(body)
        assert isinstance(body, dict)
        return [(FACT_KIND, _row_of(elem, FACT_KIND)) for elem in body[_ROWS]]
    if k not in _FIELDS:
        _bad(
            f"record kind {k!r} carries no rows — a body is read as the kind "
            "its envelope names, and this one names no row class"
        )
    _validate_row(body, k)
    assert isinstance(body, dict)
    return [(k, _row_of(body, k))]


def legacy_object_of_body(k: str, body: object) -> dict:
    """An arrival body as the LINE CODEC's object for the same rows.

    The one place the dropped discriminator is put back, and it exists for
    one consumer: the derived ``.jsonl`` projection, which is a legacy-shaped
    artifact on purpose — every last-0.x reader reads it, and the arrival
    log is the store either way.

    Validated as an arrival body FIRST, so a body that is malformed here
    cannot be laundered into a well-formed line by having ``t`` bolted onto
    it. The result is held to the line codec's own rules by
    :func:`engine.jsonl_codec.serialize_object` at the point of use, which
    also rebuilds key order — so this function's key order carries no
    weight and the projection's bytes are unchanged by the drop.
    """
    rows_of_body(k, body)
    assert isinstance(body, dict)
    if k == BATCH_KIND:
        return {
            "t": BATCH_KIND,
            _ROWS: [{"t": FACT_KIND, **elem} for elem in body[_ROWS]],
        }
    return {"t": k, **body}
