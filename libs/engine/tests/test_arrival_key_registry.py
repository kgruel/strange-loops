"""The SELECTIVE walk: registry-forming envelopes verified, ordinary not.

``key_registry`` is the admission verb (slice D §D4, DP-r2-03). It answers
one question — which keys does this log make valid for whom, from where on —
and it earns that answer by verifying exactly the records that FORM it: the
genesis and every key introduction. An ordinary record's envelope signature
is no part of the answer, so it is never checked here, which is the whole
reason this verb exists beside :func:`verify_authorship` rather than being
that function.

Real Ed25519 throughout, INJECTED, same posture as the authority suite.
"""

from __future__ import annotations

import pytest

from engine.arrival import (
    KEY_INTRODUCTION_KIND,
    ArrivalLog,
    AuthorshipUnverified,
    key_registry,
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


@pytest.fixture
def mallory(tmp_path):
    return _Custodian(tmp_path, "mallory")


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


# --- what the registry says ---------------------------------------------------


def test_the_genesis_key_is_registered_at_ordinal_zero(tmp_path, kyle):
    log = _mint(tmp_path, kyle)
    registry = key_registry(log, _verify)
    assert registry.lineage == log.lineage()
    assert registry.introductions == {"kyle": ((kyle.public, 0),)}


def test_an_introduction_registers_the_named_key_at_its_own_ordinal(
    tmp_path, kyle, ana
):
    log = _mint(tmp_path, kyle)
    intro = _introduce(log, by=kyle, named=ana)
    registry = key_registry(log, _verify)
    assert registry.introductions["ana"] == ((ana.public, intro["ord"]),)


def test_validity_is_strictly_after_introduction(tmp_path, kyle, ana):
    """The ruled clause, asked of the registry directly: valid at N iff
    introduced at a position < N."""
    log = _mint(tmp_path, kyle)
    intro = _introduce(log, by=kyle, named=ana)  # ordinal 1
    registry = key_registry(log, _verify)

    assert registry.keys_valid_at("ana", intro["ord"]) == ()
    assert registry.keys_valid_at("ana", intro["ord"] + 1) == ((ana.public, 1),)
    # The genesis key is valid everywhere after ordinal 0, and not AT it —
    # self-certification is the walk's business, not the registry's.
    assert registry.keys_valid_at("kyle", 0) == ()
    assert registry.keys_valid_at("kyle", 1) == ((kyle.public, 0),)


def test_keys_are_bound_to_observers_not_free_floating(tmp_path, kyle, ana):
    log = _mint(tmp_path, kyle)
    _introduce(log, by=kyle, named=ana)
    registry = key_registry(log, _verify)
    assert registry.keys_valid_at("ana", 99) == ((ana.public, 1),)
    assert registry.keys_valid_at("nobody", 99) == ()


# --- the selective boundary ---------------------------------------------------


def test_a_bad_ordinary_envelope_does_not_refuse_the_registry(
    tmp_path, kyle, mallory
):
    """The boundary, one half: an ordinary record signed by a key valid for
    nobody is not the registry's business, and the whole-log verifier's
    refusal on the SAME log is what proves the two verbs differ here."""
    log = _mint(tmp_path, kyle)
    # kyle's own record, signed with mallory's key: no key valid for kyle at
    # this position verifies it.
    log.append("note", {"n": 1}, observer="kyle", signer=mallory.signer)

    assert key_registry(log, _verify).introductions == {"kyle": ((kyle.public, 0),)}
    with pytest.raises(AuthorshipUnverified):
        verify_authorship(log, _verify)


def test_a_forged_key_introduction_refuses_the_registry(
    tmp_path, kyle, ana, mallory
):
    """The boundary, the other half: an introduction whose signature no
    previously-valid key verifies refuses. A key history assembled from
    unverified records is not a key history."""
    log = _mint(tmp_path, kyle)
    log.append(
        KEY_INTRODUCTION_KIND,
        {"observer": ana.name, "key": ana.public},
        observer="kyle",
        signer=mallory.signer,  # mallory holds no key valid for kyle
    )

    with pytest.raises(AuthorshipUnverified) as exc:
        key_registry(log, _verify)
    assert exc.value.ordinal == 1


def test_a_genesis_that_does_not_self_certify_refuses_the_registry(
    tmp_path, kyle, ana
):
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=kyle.signer, key=ana.public
    )
    with pytest.raises(AuthorshipUnverified, match="self-certifying") as exc:
        key_registry(log, _verify)
    assert exc.value.ordinal == 0


def test_the_whole_log_is_still_walked_structurally(tmp_path, kyle):
    """Selective is about SIGNATURES, not about coverage: the structural
    walk still holds every record, so corruption anywhere refuses."""
    from engine.arrival import ArrivalCorrupt

    log = _mint(tmp_path, kyle)
    log.append("note", {"n": 1}, observer="kyle", signer=kyle.signer)
    lines = log.path.read_text().splitlines()
    lines[1] = lines[1].replace('"n":1', '"n":2')
    log.path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ArrivalCorrupt):
        key_registry(log, _verify)


# --- one placement rule, two verbs -------------------------------------------


def test_both_verbs_agree_on_the_registry_a_clean_log_builds(tmp_path, kyle, ana):
    """``verify_authorship`` is ``key_registry`` plus the verify-every-
    envelope clause: on a log where every signature is good, the keys the
    whole-log verifier resolved records to are exactly the registry's."""
    log = _mint(tmp_path, kyle)
    _introduce(log, by=kyle, named=ana)
    log.append("note", {"n": 1}, observer="ana", signer=ana.signer)
    log.append("note", {"n": 2}, observer="kyle", signer=kyle.signer)

    registry = key_registry(log, _verify)
    for row in verify_authorship(log, _verify):
        if row.ordinal == 0:
            continue
        assert (row.key, row.introduced_ordinal) in registry.keys_valid_at(
            row.observer, row.ordinal
        )
