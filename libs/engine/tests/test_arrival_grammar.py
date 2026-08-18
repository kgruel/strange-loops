"""The arrival record grammar: field order, hashing, and both-directions validation."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
import rfc8785

from engine.arrival import (
    ARRIVAL_SUFFIX,
    GENESIS_KIND,
    GRAMMAR_VERSION,
    RECORD_FIELDS,
    ArrivalGrammarError,
    ArrivalLog,
    GenesisRefused,
    arrival_path_for,
    build_record,
    content_commitment,
    decode_record,
    encode_record,
    lock_path_for,
    record_hash,
    tmp_path_for,
)


def _sign(observer: str, commitment: str) -> str:
    """A deterministic stand-in signer with the store's injected shape."""
    return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()


# A shape-valid founding key (raw-32-byte base64 wire format). Grammar tests
# only need the shape; cryptographic verification is the authority suite's.
_KEY = base64.b64encode(b"k" * 32).decode()


def _record(**over) -> dict:
    fields = {
        "lin": "LIN", "ordinal": 1, "prev": "a" * 64, "k": "note",
        "body": {"i": 1}, "observer": "kyle", "origin": "", "at": 1.5,
    }
    fields.update(over)
    return build_record(**fields)


# --- paths -----------------------------------------------------------------


def test_companion_paths_append_to_the_full_name():
    """``alcove.db`` and ``alcove`` must not collapse onto one arrival path,
    which ``with_suffix`` would do."""
    from pathlib import Path

    assert arrival_path_for(Path("/s/alcove")).name == "alcove" + ARRIVAL_SUFFIX
    assert arrival_path_for(Path("/s/alcove.db")).name == "alcove.db.arrival"
    assert lock_path_for("/s/alcove.arrival").name == "alcove.arrival.lock"
    assert tmp_path_for("/s/alcove.arrival").name == "alcove.arrival.tmp"


# --- field order and framing ----------------------------------------------


def test_emitted_key_order_is_the_grammar_order():
    line = encode_record(_record(sig="sig:x"))
    assert list(json.loads(line)) == [*RECORD_FIELDS, "sig", "rh"]


def test_rh_is_last_even_without_a_signature():
    assert list(json.loads(encode_record(_record())))[-1] == "rh"


def test_encoded_lines_are_seven_bit_and_carry_no_raw_newline():
    line = encode_record(_record(body={"s": "café \nnewline"}))
    assert "\n" not in line
    assert line.isascii()


def test_non_finite_numbers_are_refused():
    with pytest.raises(ArrivalGrammarError, match="finite"):
        _record(at=float("nan"))


def test_integers_outside_the_jcs_domain_are_refused():
    with pytest.raises(ArrivalGrammarError, match="JCS integer domain"):
        _record(ordinal=2**53)


# --- rh --------------------------------------------------------------------


def test_rh_is_sha256_over_jcs_of_the_record_without_rh():
    record = _record()
    without = {k: v for k, v in record.items() if k != "rh"}
    assert record["rh"] == hashlib.sha256(rfc8785.dumps(without)).hexdigest()


def test_rh_covers_the_coordinate():
    """The coordinate is not signed, so ``rh`` is what makes it tamper-evident."""
    assert record_hash(_record(ordinal=1)) != record_hash(_record(ordinal=2))


def test_rh_covers_the_signature():
    a = {k: v for k, v in _record(sig="sig:a").items() if k != "rh"}
    b = dict(a, sig="sig:b")
    assert record_hash(a) != record_hash(b)


def test_a_tampered_line_fails_to_decode():
    line = encode_record(_record(body={"amount": 1}))
    with pytest.raises(ArrivalGrammarError, match="rh does not recompute"):
        decode_record(line.replace('"amount":1', '"amount":9'))


def test_encode_refuses_an_rh_that_does_not_match_its_record():
    record = dict(_record(), rh="f" * 64)
    with pytest.raises(ArrivalGrammarError, match="rh does not match"):
        encode_record(record)


def test_round_trip():
    record = _record(sig="sig:x", body={"nested": {"b": 2, "a": [1, 2.5, None, True]}})
    assert decode_record(encode_record(record)) == record


# --- the signed envelope ---------------------------------------------------


def test_the_commitment_covers_exactly_the_five_content_fields():
    envelope = {"k": "note", "at": 1.5, "observer": "kyle", "origin": "o", "body": {"i": 1}}
    assert content_commitment(**envelope) == hashlib.sha256(
        rfc8785.dumps(envelope)
    ).hexdigest()


def test_the_commitment_excludes_the_coordinate():
    """A signature must survive a record being carried into another store at
    a different ordinal — that is what content-only buys."""
    a, b = _record(ordinal=1, sig="s"), _record(ordinal=7, prev="b" * 64, sig="s")
    args = ("k", "at", "observer", "origin", "body")
    assert content_commitment(*(a[f] for f in args)) == content_commitment(
        *(b[f] for f in args)
    )


# --- absent, never null ----------------------------------------------------


def test_an_unsigned_record_omits_sig_rather_than_nulling_it():
    assert "sig" not in _record()


def test_an_explicit_null_sig_is_not_spellable():
    record = dict(_record())
    record["sig"] = None
    with pytest.raises(ArrivalGrammarError, match="sig"):
        encode_record(record)


# --- the validator runs in both directions ---------------------------------


@pytest.mark.parametrize(
    "over, match",
    [
        ({"lin": ""}, "lin must be"),
        ({"k": ""}, "k must be"),
        ({"observer": ""}, "observer must be"),
        ({"origin": 3}, "origin must be"),
        ({"body": "text"}, "body must be a JSON object"),
        ({"ordinal": -1}, "ord must be"),
        ({"ordinal": True}, "ord must be"),
        ({"at": "1.5"}, "at must be a number"),
        ({"prev": "short"}, "prev must be"),
        ({"ordinal": 0}, "prev must be null at ordinal 0"),
    ],
)
def test_build_refuses_what_decode_would_refuse(over, match):
    """A wrongly typed field must fail at the append site, where it is
    attributable, not become a durable line that bricks every later open."""
    with pytest.raises(ArrivalGrammarError, match=match):
        _record(**over)


def test_genesis_prev_must_be_null():
    assert _record(ordinal=0, prev=None)["prev"] is None


@pytest.mark.parametrize(
    "line, match",
    [
        ("not json", "not valid JSON"),
        ('{"v":1}', "missing record field"),
        ('[1,2]', "must be a JSON object"),
    ],
)
def test_decode_refuses_malformed_lines(line, match):
    with pytest.raises(ArrivalGrammarError, match=match):
        decode_record(line)


def test_decode_refuses_an_unknown_field():
    record = dict(_record())
    record["extra"] = 1
    with pytest.raises(ArrivalGrammarError, match="unknown record field"):
        decode_record(json.dumps(record))


def test_decode_refuses_a_duplicate_key():
    """JSON's last-wins resolution would let one line carry two ordinals and
    a reader silently pick one."""
    line = encode_record(_record())
    with pytest.raises(ArrivalGrammarError, match="duplicate key"):
        decode_record(line.replace('"ord":1', '"ord":1,"ord":2'))


def test_decode_refuses_a_future_grammar_version():
    record = dict(_record())
    record["v"] = 2
    with pytest.raises(ArrivalGrammarError, match="unsupported grammar version"):
        decode_record(json.dumps(record))


# --- genesis ---------------------------------------------------------------


def test_genesis_is_signed_at_ordinal_zero_and_self_naming(tmp_path):
    log = ArrivalLog.mint(tmp_path / "alcove.arrival", observer="kyle", signer=_sign, key=_KEY)
    genesis = log.genesis()
    assert (genesis["ord"], genesis["prev"], genesis["k"]) == (0, None, GENESIS_KIND)
    assert genesis["body"] == {
        "protocol": GRAMMAR_VERSION,
        "lineage": genesis["lin"],
        "key": _KEY,
    }
    assert genesis["sig"] == _sign(
        "kyle",
        content_commitment(
            GENESIS_KIND, genesis["at"], "kyle", "", genesis["body"]
        ),
    )


def test_genesis_body_is_the_ratified_three_fields():
    """The adoption genesis body is {protocol, lineage, key} and nothing
    else (decision:design/arrival-sliceA-authority §2.3): the document set
    is movement 2 at ordinal >= 1, era pins dissolve under the dense
    ordinal, and containment claims belong to the migration sidecar."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        log = ArrivalLog.mint(
            Path(d) / "s.arrival", observer="kyle", signer=_sign, key=_KEY
        )
        assert set(log.genesis()["body"]) == {"protocol", "lineage", "key"}


def test_a_keyless_genesis_is_refused(tmp_path):
    """The founding key is required at ordinal 0 for a live-store genesis;
    the keyless variant is the migration sidecar's open question, not this
    grammar's."""
    body = {"protocol": GRAMMAR_VERSION, "lineage": "LIN"}
    record = build_record(
        lin="LIN", ordinal=0, prev=None, k=GENESIS_KIND, body=body,
        observer="kyle", origin="", at=1.0, sig="sig:x",
    )
    path = tmp_path / "s.arrival"
    path.write_text(encode_record(record) + "\n")
    with pytest.raises(GenesisRefused, match="founding key"):
        ArrivalLog(path).genesis()


@pytest.mark.parametrize(
    "bad", ["", "not-base64!!", base64.b64encode(b"short").decode()]
)
def test_a_malformed_founding_key_is_refused_at_mint(tmp_path, bad):
    with pytest.raises(GenesisRefused, match="malformed"):
        ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=bad)
    assert not (tmp_path / "s.arrival").exists()


def test_an_unsigned_genesis_is_refused(tmp_path):
    with pytest.raises(GenesisRefused, match="unsigned"):
        ArrivalLog.mint(
            tmp_path / "s.arrival", observer="kyle", signer=lambda o, c: None, key=_KEY
        )
    assert not (tmp_path / "s.arrival").exists()
    assert not (tmp_path / "s.arrival.tmp").exists()


def test_minting_over_an_existing_log_is_refused(tmp_path):
    ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    with pytest.raises(GenesisRefused, match="already exists"):
        ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    assert not (tmp_path / "s.arrival.tmp").exists()


def test_a_file_whose_first_record_is_not_a_genesis_is_not_an_arrival_log(tmp_path):
    path = tmp_path / "s.arrival"
    path.write_text(encode_record(_record(ordinal=0, prev=None, k="note")) + "\n")
    with pytest.raises(GenesisRefused, match="not a genesis"):
        ArrivalLog(path).genesis()


def test_a_genesis_that_is_not_self_naming_is_refused(tmp_path):
    path = tmp_path / "s.arrival"
    forged = _record(
        ordinal=0, prev=None, k=GENESIS_KIND, lin="MINE",
        body={"protocol": 1, "lineage": "THEIRS"}, sig="sig:x",
    )
    path.write_text(encode_record(forged) + "\n")
    with pytest.raises(GenesisRefused, match="not self-naming"):
        ArrivalLog(path).genesis()


# --- append validates, it does not assign ----------------------------------


def test_append_writes_the_coordinate_into_the_record(tmp_path):
    log = ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    lin = log.lineage()
    records = [log.append("note", {"i": i}, observer="kyle") for i in range(3)]
    assert [r["ord"] for r in records] == [1, 2, 3]
    assert {r["lin"] for r in records} == {lin}
    assert [r["ord"] for r in log.walk()] == [0, 1, 2, 3]


def test_prev_chains_from_record_zero(tmp_path):
    log = ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    for i in range(4):
        log.append("note", {"i": i}, observer="kyle")
    walked = list(log.walk())
    assert walked[0]["prev"] is None
    assert all(b["prev"] == a["rh"] for a, b in zip(walked, walked[1:], strict=False))


def test_ordinary_records_may_be_unsigned_and_may_be_signed(tmp_path):
    log = ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    assert "sig" not in log.append("note", {}, observer="kyle")
    assert "sig" in log.append("note", {}, observer="kyle", signer=_sign)


@pytest.mark.parametrize(
    "over, match",
    [
        ({"lin": "OTHER"}, "lineage"),
        ({"ordinal": 9}, "ord"),
        ({"prev": "c" * 64}, "prev"),
    ],
)
def test_append_record_refuses_a_candidate_that_does_not_follow_the_head(
    tmp_path, over, match
):
    from engine.arrival import AppendRejected

    log = ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    head = log.head()
    fields = {
        "lin": head["lin"], "ordinal": head["ord"] + 1, "prev": head["rh"],
        "k": "note", "body": {}, "observer": "kyle",
    }
    fields.update(over)
    before = (tmp_path / "s.arrival").read_bytes()
    with pytest.raises(AppendRejected, match=match):
        log.append_record(build_record(**fields))
    assert (tmp_path / "s.arrival").read_bytes() == before


def test_append_record_accepts_a_well_placed_candidate(tmp_path):
    log = ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    head = log.head()
    log.append_record(
        build_record(
            lin=head["lin"], ordinal=1, prev=head["rh"], k="note",
            body={"carried": True}, observer="kyle",
        )
    )
    assert log.read(1)["body"] == {"carried": True}


def test_read_by_ordinal_and_head(tmp_path):
    log = ArrivalLog.mint(tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY)
    for i in range(3):
        log.append("note", {"i": i}, observer="kyle")
    assert log.read(2)["body"] == {"i": 1}
    assert log.head()["ord"] == 3
    with pytest.raises(Exception, match="no record at ordinal 9"):
        log.read(9)
