"""The first verifier: keys resolve from log coordinates, and nowhere else.

Cut A of the arrival substrate (decision:design/arrival-sliceA-authority).
The ruled rule under test, verbatim: a key is valid at position N iff it was
introduced at a position < N, or N is the genesis position and the record is
self-certifying. Self-certification is legal at ordinal 0 and nowhere else.

Real Ed25519 throughout, INJECTED — ``engine`` never imports ``sign``; this
suite composes the two the way an app does, which is the posture the module
pins (``arrival.Signer`` / ``arrival.Verify``).
"""

from __future__ import annotations

import pytest

from engine.arrival import (
    KEY_INTRODUCTION_KIND,
    ArrivalGrammarError,
    ArrivalLog,
    AuthorshipUnverified,
    GenesisRefused,
    verify_authorship,
)
from tests.conftest import Custodian as _Custodian
from tests.conftest import ed25519_verify as _verify


@pytest.fixture
def kyle(tmp_path):
    return _Custodian(tmp_path, "kyle")


@pytest.fixture
def ana(tmp_path):
    return _Custodian(tmp_path, "ana")


def _mint(tmp_path, custodian: _Custodian) -> ArrivalLog:
    return ArrivalLog.mint(
        tmp_path / "s.arrival",
        observer=custodian.name,
        signer=custodian.signer,
        key=custodian.public,
    )


def _introduce(log: ArrivalLog, by: _Custodian, named: _Custodian) -> dict:
    return log.append(
        KEY_INTRODUCTION_KIND,
        {"observer": named.name, "key": named.public},
        observer=by.name,
        signer=by.signer,
    )


# --- genesis self-certification ---------------------------------------------


def test_genesis_self_certifies_and_the_trace_names_ordinal_zero(tmp_path, kyle):
    log = _mint(tmp_path, kyle)
    rows = verify_authorship(log, _verify)
    assert len(rows) == 1
    row = rows[0]
    assert (row.ordinal, row.observer, row.key) == (0, "kyle", kyle.public)
    assert (row.introduced_lineage, row.introduced_ordinal) == (log.lineage(), 0)


def test_a_genesis_signed_by_a_key_other_than_its_own_is_refused(
    tmp_path, kyle, ana
):
    # kyle signs, but the body claims ana's key: self-naming holds, but
    # self-certification fails — the first verification arrival performs.
    log = ArrivalLog.mint(
        tmp_path / "s.arrival",
        observer="kyle",
        signer=kyle.signer,
        key=ana.public,
    )
    with pytest.raises(AuthorshipUnverified, match="self-certifying") as exc:
        verify_authorship(log, _verify)
    assert exc.value.ordinal == 0


# --- the ruled validity clause ------------------------------------------------


def test_records_signed_by_the_founding_key_resolve_to_the_genesis_coordinate(
    tmp_path, kyle
):
    log = _mint(tmp_path, kyle)
    log.append("note", {"n": 1}, observer="kyle", signer=kyle.signer)
    log.append("note", {"n": 2}, observer="kyle", signer=kyle.signer)
    rows = verify_authorship(log, _verify)
    assert [r.ordinal for r in rows] == [0, 1, 2]
    assert all(r.introduced_ordinal == 0 for r in rows)
    assert all(r.key == kyle.public for r in rows)


def test_an_introduced_key_verifies_records_strictly_after_its_introduction(
    tmp_path, kyle, ana
):
    log = _mint(tmp_path, kyle)
    intro = _introduce(log, by=kyle, named=ana)  # ordinal 1
    log.append("note", {"n": 1}, observer="ana", signer=ana.signer)  # ordinal 2
    rows = verify_authorship(log, _verify)
    assert [r.ordinal for r in rows] == [0, 1, 2]
    ana_row = rows[2]
    assert (ana_row.observer, ana_row.key) == ("ana", ana.public)
    assert ana_row.introduced_ordinal == intro["ord"] == 1


def test_a_key_introduced_at_n_does_not_verify_a_record_at_or_before_n(
    tmp_path, kyle, ana
):
    log = _mint(tmp_path, kyle)
    # ana signs BEFORE her key is introduced: at her record's position no
    # key is valid for her, however real the signature is.
    log.append("note", {"n": 1}, observer="ana", signer=ana.signer)  # ordinal 1
    _introduce(log, by=kyle, named=ana)  # ordinal 2
    with pytest.raises(AuthorshipUnverified, match="strictly before") as exc:
        verify_authorship(log, _verify)
    assert exc.value.ordinal == 1


def test_self_certification_is_refused_above_ordinal_zero(tmp_path, kyle, ana):
    # A forged introduction: ana vouches for herself with a key the log has
    # never seen. The signature verifies under the key inside the record's
    # own body — which is exactly what the verifier must never consult.
    log = _mint(tmp_path, kyle)
    log.append(
        KEY_INTRODUCTION_KIND,
        {"observer": "ana", "key": ana.public},
        observer="ana",
        signer=ana.signer,
    )
    with pytest.raises(AuthorshipUnverified) as exc:
        verify_authorship(log, _verify)
    assert exc.value.ordinal == 1


def test_a_signature_by_the_wrong_observers_key_is_refused(tmp_path, kyle, ana):
    # ana's key is introduced, but a record CLAIMING kyle is signed with
    # ana's key: keys are bound to observers, so kyle's record must not
    # verify under ana's key.
    log = _mint(tmp_path, kyle)
    _introduce(log, by=kyle, named=ana)
    log.append("note", {"n": 1}, observer="kyle", signer=ana.signer)
    with pytest.raises(AuthorshipUnverified, match="verifies under none") as exc:
        verify_authorship(log, _verify)
    assert exc.value.ordinal == 2


def test_unsigned_records_make_no_authorship_claim(tmp_path, kyle):
    log = _mint(tmp_path, kyle)
    log.append("note", {"n": 1}, observer="anon")
    rows = verify_authorship(log, _verify)
    assert [r.ordinal for r in rows] == [0]


# --- introduction structure (grammar-level, enforced at the append gate) ------


def test_an_unsigned_key_introduction_is_refused_at_append(tmp_path, kyle, ana):
    log = _mint(tmp_path, kyle)
    with pytest.raises(Exception, match="no signature"):
        log.append(
            KEY_INTRODUCTION_KIND,
            {"observer": "ana", "key": ana.public},
            observer="kyle",
        )
    assert [r["ord"] for r in log.walk()] == [0]


@pytest.mark.parametrize(
    "body, match",
    [
        ({"key": "zz"}, "name the observer"),
        ({"observer": "ana"}, "well-formed key"),
        ({"observer": "ana", "key": "not-base64!!"}, "well-formed key"),
    ],
)
def test_a_malformed_key_introduction_is_refused_at_append(
    tmp_path, kyle, body, match
):
    log = _mint(tmp_path, kyle)
    with pytest.raises(Exception, match=match):
        log.append(KEY_INTRODUCTION_KIND, body, observer="kyle", signer=kyle.signer)
    assert [r["ord"] for r in log.walk()] == [0]


def test_the_walk_refuses_a_hand_written_malformed_introduction(tmp_path, kyle):
    from engine.arrival import ArrivalCorrupt, build_record, encode_record

    log = _mint(tmp_path, kyle)
    genesis = log.genesis()
    forged = build_record(
        lin=genesis["lin"], ordinal=1, prev=genesis["rh"],
        k=KEY_INTRODUCTION_KIND, body={"observer": "ana"},
        observer="kyle", at=1.0, sig="sig:x",
    )
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write(encode_record(forged) + "\n")
    with pytest.raises(ArrivalCorrupt, match="well-formed key"):
        list(log.walk())


def test_mint_key_and_signer_disagreeing_is_caught_by_the_verifier(tmp_path, kyle):
    # The grammar cannot check crypto (no verifier at mint); the verifier is
    # where a signer/key mismatch surfaces. This pins that division of labor.
    wrong = _Custodian(tmp_path, "other")
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=wrong.signer, key=kyle.public
    )
    with pytest.raises(AuthorshipUnverified):
        verify_authorship(log, _verify)


def test_grammar_errors_and_refusals_stay_typed(tmp_path, kyle):
    # Companion pin: the two refusal families remain distinct so callers can
    # tell "not a log / bad record" from "authorship unverified".
    assert not issubclass(AuthorshipUnverified, ArrivalGrammarError)
    assert not issubclass(AuthorshipUnverified, GenesisRefused)
