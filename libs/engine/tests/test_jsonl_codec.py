"""JSONL line codec — payload verbatimness, hash re-derivation, strictness.

The whole point of the codec is that a row can leave sqlite, live as a line
of text, come back, and still hash to the same commitment. Every signature
in every live store depends on it, across three eras (pre-chain, chained,
signed), so the era matrix is tested explicitly.
"""

import json

import pytest

from engine.jsonl_codec import (
    JsonlCodecError,
    deserialize_fact_row,
    deserialize_row,
    deserialize_tick_row,
    serialize_fact_row,
    serialize_tick_row,
)
from engine.sqlite_store import (
    _fact_commitment_hash,
    _fact_row_hash,
    _tick_row_hash,
)

# --- fixtures: rows of every era -------------------------------------------

TRICKY_PAYLOAD = json.dumps(
    {
        "message": 'he said "hi"\nthen\tleft\r\n',
        "ünïcødé": "日本語 — emoji 🌀, U+2028\u2028 U+2029\u2029",
        "backslash": "C:\\path\\to\\\u0000nul",
        "nested": {"a": [1, 2.5, None, True]},
    },
    ensure_ascii=False,
)

# High-precision ts: shortest-roundtrip repr must survive the text hop.
TS = 1721359123.4567891

FACT_V1 = ("01JFACT", "decision", TS, "kyle", "loops", TRICKY_PAYLOAD)
FACT_SIGNED = (*FACT_V1, "sig-fact-abc")
FACT_UNSIGNED_7 = (*FACT_V1, None)

TICK_PRECHAIN = (
    "01JTICK", "project", TS, None, "loops", TRICKY_PAYLOAD,
    None, None, None, None,
)
TICK_CHAINED = (
    "01JTICK2", "project", TS, TS - 60.0, "loops", TRICKY_PAYLOAD,
    "prevhash", "2026-08-11T00:00:00Z", "01JFACT", "windowhash",
)
TICK_SIGNED = (*TICK_CHAINED, "sig-tick-xyz")
TICK_UNSIGNED_11 = (*TICK_CHAINED, None)


# --- (a) payload verbatim + lossless round-trip ----------------------------


@pytest.mark.parametrize("row", [FACT_V1, FACT_SIGNED, FACT_UNSIGNED_7])
def test_fact_round_trip_is_lossless(row):
    back = deserialize_fact_row(serialize_fact_row(row))
    assert len(back) == 7
    assert back[:6] == row[:6]
    assert back[6] == (row[6] if len(row) > 6 else None)
    assert back[5] == TRICKY_PAYLOAD  # verbatim, character for character
    assert back[2] == TS


@pytest.mark.parametrize(
    "row", [TICK_PRECHAIN, TICK_CHAINED, TICK_SIGNED, TICK_UNSIGNED_11]
)
def test_tick_round_trip_is_lossless(row):
    back = deserialize_tick_row(serialize_tick_row(row))
    assert len(back) == 11
    assert back[:10] == row[:10]
    assert back[10] == (row[10] if len(row) > 10 else None)
    assert back[5] == TRICKY_PAYLOAD


def test_payload_is_never_reparsed_and_need_not_be_json():
    # The codec treats payload as opaque TEXT. Even a non-JSON string
    # survives — validation belongs to the store's CHECK, not the codec.
    row = ("id", "kind", 1.0, "obs", "orig", "not json at all {")
    assert deserialize_fact_row(serialize_fact_row(row))[5] == "not json at all {"


def test_lines_are_single_line_and_ascii():
    for line in (serialize_fact_row(FACT_SIGNED),
                 serialize_tick_row(TICK_SIGNED)):
        assert "\n" not in line and "\r" not in line
        assert "\u2028" not in line and "\u2029" not in line
        line.encode("ascii")  # ensure_ascii=True contract


def test_signature_none_and_short_row_serialize_identically():
    # Era-aware: absence and NULL are the same era, and hash the same.
    assert serialize_fact_row(FACT_V1) == serialize_fact_row(FACT_UNSIGNED_7)
    assert serialize_tick_row(TICK_CHAINED) == serialize_tick_row(
        TICK_UNSIGNED_11
    )
    assert "signature" not in serialize_fact_row(FACT_V1)


# --- (b) hash re-derivation across all eras --------------------------------


@pytest.mark.parametrize(
    "row", [FACT_V1, FACT_UNSIGNED_7, FACT_SIGNED],
    ids=["unsigned-6", "unsigned-7", "signed"],
)
def test_fact_row_hash_survives_round_trip(row):
    back = deserialize_fact_row(serialize_fact_row(row))
    assert _fact_row_hash(back) == _fact_row_hash(row)


@pytest.mark.parametrize(
    "row", [FACT_V1, FACT_SIGNED], ids=["unsigned", "signed"]
)
def test_fact_commitment_hash_survives_round_trip(row):
    back = deserialize_fact_row(serialize_fact_row(row))
    # (kind, ts, observer, origin, payload) — content commitment, what the
    # fact signer signed.
    assert _fact_commitment_hash(
        back[1], back[2], back[3], back[4], back[5]
    ) == _fact_commitment_hash(row[1], row[2], row[3], row[4], row[5])


@pytest.mark.parametrize(
    "row", [TICK_PRECHAIN, TICK_CHAINED, TICK_UNSIGNED_11, TICK_SIGNED],
    ids=["pre-chain", "chained-10", "chained-11", "signed"],
)
def test_tick_row_hash_survives_round_trip(row):
    back = deserialize_tick_row(serialize_tick_row(row))
    assert _tick_row_hash(back) == _tick_row_hash(row)


def test_signed_and_unsigned_hashes_differ():
    # Guards the round-trip tests against trivially passing by collapsing
    # the eras together.
    assert _fact_row_hash(FACT_SIGNED) != _fact_row_hash(FACT_V1)
    assert _tick_row_hash(TICK_SIGNED) != _tick_row_hash(TICK_CHAINED)


# --- (c) strictness: reject loudly -----------------------------------------


def test_unknown_field_rejected():
    obj = json.loads(serialize_fact_row(FACT_SIGNED))
    obj["extra"] = "surprise"
    with pytest.raises(JsonlCodecError, match="unknown field"):
        deserialize_fact_row(json.dumps(obj))


def test_missing_field_rejected():
    obj = json.loads(serialize_fact_row(FACT_V1))
    del obj["observer"]
    with pytest.raises(JsonlCodecError, match="observer"):
        deserialize_fact_row(json.dumps(obj))


def test_wrong_discriminator_rejected():
    line = serialize_tick_row(TICK_SIGNED)
    with pytest.raises(JsonlCodecError, match="expected t='fact'"):
        deserialize_fact_row(line)
    with pytest.raises(JsonlCodecError, match="discriminator"):
        deserialize_row(json.dumps({"t": "blob"}))


def test_non_object_line_rejected():
    with pytest.raises(JsonlCodecError, match="JSON object"):
        deserialize_row("[1,2,3]")
    with pytest.raises(JsonlCodecError, match="not valid JSON"):
        deserialize_row("{oops")


@pytest.mark.parametrize(
    "field,value",
    [("ts", "1.0"), ("ts", True), ("payload", {"a": 1}), ("kind", 3),
     ("observer", None), ("signature", 7)],
)
def test_bad_types_rejected(field, value):
    obj = json.loads(serialize_fact_row(FACT_SIGNED))
    obj[field] = value
    with pytest.raises(JsonlCodecError, match=field):
        deserialize_fact_row(json.dumps(obj))


def test_tick_nullable_fields_accepted_facts_not_null():
    # since/prev_hash/window_* legitimately NULL on pre-chain ticks.
    deserialize_tick_row(serialize_tick_row(TICK_PRECHAIN))
    obj = json.loads(serialize_tick_row(TICK_CHAINED))
    obj["name"] = None
    with pytest.raises(JsonlCodecError, match="must not be null"):
        deserialize_tick_row(json.dumps(obj))


def test_explicit_null_signature_rejected():
    # serialize never emits it; accepting it would give one row two
    # canonical spellings.
    obj = json.loads(serialize_fact_row(FACT_V1))
    obj["signature"] = None
    with pytest.raises(JsonlCodecError, match="absent, not null"):
        deserialize_fact_row(json.dumps(obj))


def test_bad_arity_rejected():
    with pytest.raises(JsonlCodecError, match="fields"):
        serialize_fact_row(("id", "kind", 1.0))
    with pytest.raises(JsonlCodecError, match="fields"):
        serialize_tick_row((*TICK_SIGNED, "extra"))


def test_deserialize_row_dispatches():
    assert deserialize_row(serialize_fact_row(FACT_SIGNED))[0] == "fact"
    assert deserialize_row(serialize_tick_row(TICK_SIGNED)) == (
        "tick", TICK_SIGNED
    )


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_json_literals_rejected(literal):
    # allow_nan=False means these can never be emitted; they must not be
    # admitted on read either — otherwise a corrupt line passes the codec
    # gate and detonates inside the JCS commitment hashers.
    line = (
        '{"t":"fact","id":"i","kind":"k","ts":' + literal + ","
        '"observer":"o","origin":"g","payload":"{}"}'
    )
    with pytest.raises(JsonlCodecError):
        deserialize_fact_row(line)
    with pytest.raises(JsonlCodecError):
        deserialize_row(line)


def test_non_json_literal_rejected_in_tick():
    obj = json.loads(serialize_tick_row(TICK_SIGNED))
    parts = [
        f'"{k}":' + ("NaN" if k == "ts" else json.dumps(v))
        for k, v in obj.items()
    ]
    line = "{" + ",".join(parts) + "}"
    with pytest.raises(JsonlCodecError):
        deserialize_tick_row(line)


# Standards-valid JSON spellings that the literal parser never sees, but
# that are outside the JCS numeric domain the commitment hashers require.
_OUT_OF_DOMAIN = [
    "1e999",            # overflows to inf
    "-1e999",           # overflows to -inf
    "9007199254740992",     # 2**53 — first unsafe integer
    "-9007199254740992",
    "1" + "0" * 400,        # 401-digit integer
]


@pytest.mark.parametrize("number", _OUT_OF_DOMAIN)
def test_out_of_jcs_domain_numbers_rejected_in_fact(number):
    line = (
        '{"t":"fact","id":"i","kind":"k","ts":' + number + ","
        '"observer":"o","origin":"g","payload":"{}"}'
    )
    with pytest.raises(JsonlCodecError):
        deserialize_fact_row(line)
    with pytest.raises(JsonlCodecError):
        deserialize_row(line)


@pytest.mark.parametrize("field", ["ts", "since"])
@pytest.mark.parametrize("number", _OUT_OF_DOMAIN)
def test_out_of_jcs_domain_numbers_rejected_in_tick(field, number):
    obj = json.loads(serialize_tick_row(TICK_SIGNED))
    parts = [
        f'"{k}":' + (number if k == field else json.dumps(v))
        for k, v in obj.items()
    ]
    line = "{" + ",".join(parts) + "}"
    with pytest.raises(JsonlCodecError):
        deserialize_tick_row(line)


def test_jcs_boundary_integers_accepted():
    # The bound itself is inside the domain — reject one past it, not it.
    for number in ("9007199254740991", "-9007199254740991"):
        line = (
            '{"t":"fact","id":"i","kind":"k","ts":' + number + ","
            '"observer":"o","origin":"g","payload":"{}"}'
        )
        assert deserialize_fact_row(line)[2] == int(number)
