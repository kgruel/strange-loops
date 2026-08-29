"""The arrival body grammar — wire v1's t-less row framing.

Pins decision:design/arrival-wire-v1-seam-triage's first and fourth rulings:
``body.t`` DROPS (the envelope's ``k`` is the only place a record's class is
written), and a batch record's rows share one observer, enforced as a
wire-grammar refusal rather than left to the shape of the call chain.

The NON-NEGOTIABLE of the whole slice is asserted here too: no preserved
inner signature may be invalidated. The inner fact commitment is (kind, ts,
observer, origin, payload) and never named ``t``, so dropping it cannot
move a commitment — and this suite is where that stops being an argument
and becomes a check.
"""

from __future__ import annotations

import json

import pytest
from engine.arrival_body import (
    ArrivalBodyError,
    body_of_batch,
    body_of_fact_row,
    body_of_tick_row,
    legacy_object_of_body,
    rows_of_body,
)
from engine.jsonl_codec import (
    object_of_batch,
    object_of_fact_row,
    object_of_tick_row,
    serialize_object,
)
from engine.sqlite_store import fact_commitment_hash

_TS = 1700000000.0


def fact_row(ident="01F0", *, observer="kyle", message="m", signature=None):
    row = (ident, "note", _TS, observer, "", json.dumps({"message": message}))
    return (*row, signature) if signature is not None else row


def tick_row(ident="01K0", *, name="pulse"):
    return (ident, name, _TS, None, "v", json.dumps({"n": 1}), None, None, None, None)


# --- the drop ----------------------------------------------------------------


def test_no_encoded_body_carries_the_discriminator():
    assert "t" not in body_of_fact_row(fact_row())
    assert "t" not in body_of_tick_row(tick_row())
    batch = body_of_batch([fact_row("01A"), fact_row("01B")])
    assert "t" not in batch
    assert all("t" not in row for row in batch["rows"])


@pytest.mark.parametrize("k", ["fact", "tick"])
def test_a_body_still_carrying_t_is_refused_by_the_grammar(k):
    """Refusal-by-grammar, not by detection: ``t`` is simply not an allowed
    field, so a body carrying it fails the same unknown-field rule that
    refuses any other stray key. There is no compat mode to fall back to
    and nothing that sniffs for the old shape."""
    legacy = object_of_fact_row(fact_row()) if k == "fact" else object_of_tick_row(
        tick_row()
    )
    assert legacy["t"] == k  # the legacy codec still writes it, untouched
    with pytest.raises(ArrivalBodyError, match=r"unknown field\(s\).*'t'"):
        rows_of_body(k, legacy)


def test_a_batch_body_carrying_t_is_refused_at_the_envelope_and_in_its_rows():
    legacy = object_of_batch([fact_row("01A"), fact_row("01B")])
    with pytest.raises(ArrivalBodyError, match=r"unknown field\(s\) in batch body"):
        rows_of_body("batch", legacy)

    rows_carry_t = {"rows": [object_of_fact_row(fact_row("01A")),
                             object_of_fact_row(fact_row("01B"))]}
    with pytest.raises(ArrivalBodyError, match=r"unknown field\(s\).*'t'"):
        rows_of_body("batch", rows_carry_t)


def test_the_legacy_line_codec_keeps_its_t():
    """The fork is one-directional: slice 4's migration sidecar reads
    historical ``.jsonl`` logs and the derived-log projection writes them,
    so the line framing is untouched by the drop."""
    assert object_of_fact_row(fact_row())["t"] == "fact"
    assert object_of_tick_row(tick_row())["t"] == "tick"
    assert object_of_batch([fact_row("01A"), fact_row("01B")])["t"] == "batch"


# --- reading by k ------------------------------------------------------------


def test_rows_are_read_as_the_class_the_envelope_names():
    assert rows_of_body("fact", body_of_fact_row(fact_row())) == [
        ("fact", (*fact_row(), None))
    ]
    assert rows_of_body("tick", body_of_tick_row(tick_row())) == [
        ("tick", (*tick_row(), None))
    ]
    rows = rows_of_body("batch", body_of_batch([fact_row("01A"), fact_row("01B")]))
    assert [t for t, _row in rows] == ["fact", "fact"]
    assert [row[0] for _t, row in rows] == ["01A", "01B"]


def test_a_body_read_as_the_wrong_class_refuses():
    """The envelope is now the ONLY claim about a record's class, so a
    mismatch is a refusal rather than a body that quietly disagrees with
    its envelope — which is exactly the ambiguity carrying both spellings
    would have made possible."""
    with pytest.raises(ArrivalBodyError):
        rows_of_body("tick", body_of_fact_row(fact_row()))
    with pytest.raises(ArrivalBodyError):
        rows_of_body("fact", body_of_tick_row(tick_row()))


def test_a_kind_that_carries_no_rows_refuses():
    with pytest.raises(ArrivalBodyError, match="carries no rows"):
        rows_of_body("genesis", {"protocol": 1, "lineage": "L", "key": "k"})


# --- the batch same-observer grammar -----------------------------------------


def test_a_batch_spanning_observers_is_refused_on_construction():
    """Ruling 4. The envelope's observer is read off row 0 and selects the
    key that signs a commitment covering every row, so a mixed-observer
    batch would have row 0's author attesting to another author's facts.
    Construction over detection: it cannot be built."""
    with pytest.raises(ArrivalBodyError, match="span 2 observers"):
        body_of_batch([fact_row("01A", observer="kyle"),
                       fact_row("01B", observer="someone-else")])


def test_a_batch_spanning_observers_is_refused_on_decode_too():
    """A grammar rule enforced in one direction only is a rule a determined
    caller routes around — here, by hand-assembling the body it could not
    build and appending that."""
    forged = {
        "rows": [
            dict(zip(("id", "kind", "ts", "observer", "origin", "payload"),
                     fact_row("01A", observer="kyle"), strict=True)),
            dict(zip(("id", "kind", "ts", "observer", "origin", "payload"),
                     fact_row("01B", observer="someone-else"), strict=True)),
        ]
    }
    with pytest.raises(ArrivalBodyError, match="span 2 observers"):
        rows_of_body("batch", forged)


def test_a_same_observer_batch_is_fine():
    body = body_of_batch([fact_row("01A"), fact_row("01B"), fact_row("01C")])
    assert len(rows_of_body("batch", body)) == 3


def test_the_line_codec_does_NOT_carry_the_same_observer_rule():
    """Scoped to the ARRIVAL seam, deliberately. Holding historical
    ``.jsonl`` logs to a rule that did not exist when they were written
    would turn slice 4's migration into a refusal, and the sidecar's own
    output is guarded anyway because it constructs bodies through
    ``body_of_batch``."""
    mixed = object_of_batch([fact_row("01A", observer="kyle"),
                             fact_row("01B", observer="someone-else")])
    assert [row["observer"] for row in mixed["rows"]] == ["kyle", "someone-else"]


def test_a_batch_still_refuses_one_row_and_a_duplicate_id():
    with pytest.raises(ArrivalBodyError, match="at least 2 rows"):
        body_of_batch([fact_row("01A")])
    with pytest.raises(ArrivalBodyError, match="duplicate id"):
        body_of_batch([fact_row("01A"), fact_row("01A", message="other")])


# --- round trips and the NON-NEGOTIABLE --------------------------------------


@pytest.mark.parametrize(
    "k,row,encode",
    [
        ("fact", fact_row(), body_of_fact_row),
        ("fact", fact_row(signature="sig:abc"), body_of_fact_row),
        ("tick", tick_row(), body_of_tick_row),
    ],
)
def test_encode_decode_encode_is_byte_stable(k, row, encode):
    """The oracle's identity round trip, asserted on BYTES rather than on
    dict equality — key order and JSON spelling are part of what a wire
    format promises."""
    body = encode(row)
    once = json.dumps(body, sort_keys=True, separators=(",", ":"))
    (_t, decoded), = rows_of_body(k, json.loads(once))
    twice = json.dumps(encode(decoded), sort_keys=True, separators=(",", ":"))
    assert once == twice


def test_a_batch_round_trips_byte_stably():
    rows = [fact_row("01A"), fact_row("01B", signature="sig:b")]
    once = json.dumps(body_of_batch(rows), sort_keys=True, separators=(",", ":"))
    decoded = [row for _t, row in rows_of_body("batch", json.loads(once))]
    twice = json.dumps(body_of_batch(decoded), sort_keys=True, separators=(",", ":"))
    assert once == twice


def test_payload_rides_as_verbatim_stored_text():
    """The load-bearing invariant, inherited unchanged. The payload is a
    JSON STRING inside the body, never re-serialized — which is why every
    commitment hash re-derives byte-identically."""
    payload = '{"message": "m",  "spacing": "preserved"}'
    row = ("01F0", "note", _TS, "kyle", "", payload)
    body = body_of_fact_row(row)
    assert body["payload"] == payload
    assert rows_of_body("fact", body)[0][1][5] == payload


def test_dropping_t_moves_no_inner_commitment():
    """NON-NEGOTIABLE. ``fact_commitment_hash`` is (kind, ts, observer,
    origin, payload) — it never named ``t``, so a signature made before the
    drop still covers exactly what it covered. Asserted against the row
    recovered from a t-less body, which is the row a verifier will hold."""
    row = fact_row(signature="sig:preserved")
    before = fact_commitment_hash(*row[1:6])
    (_t, recovered), = rows_of_body("fact", body_of_fact_row(row))
    assert fact_commitment_hash(*recovered[1:6]) == before
    assert recovered[6] == "sig:preserved"  # and the signature rides verbatim


# --- the derived log's restored discriminator --------------------------------


@pytest.mark.parametrize(
    "k,row,legacy_encode,body_encode",
    [
        ("fact", fact_row(), object_of_fact_row, body_of_fact_row),
        ("tick", tick_row(), object_of_tick_row, body_of_tick_row),
    ],
)
def test_the_derived_log_line_is_unchanged_by_the_drop(
    k, row, legacy_encode, body_encode
):
    """The derived ``.jsonl`` projection is legacy-shaped on purpose, so its
    bytes must be exactly what they were before wire v1 — the drop happens
    on the arrival side of the seam and nowhere else."""
    restored = legacy_object_of_body(k, body_encode(row))
    assert serialize_object(restored) == serialize_object(legacy_encode(row))


def test_the_derived_log_line_for_a_batch_is_unchanged_by_the_drop():
    rows = [fact_row("01A"), fact_row("01B")]
    restored = legacy_object_of_body("batch", body_of_batch(rows))
    assert serialize_object(restored) == serialize_object(object_of_batch(rows))


def test_restoring_a_malformed_body_refuses_rather_than_laundering_it():
    """``t`` is put back from ``k``, so a body that is malformed as an
    arrival body must not become well-formed merely by acquiring a
    discriminator."""
    with pytest.raises(ArrivalBodyError):
        legacy_object_of_body("fact", {"id": "01A"})
