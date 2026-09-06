"""The backend-neutral authorship seam over an already verified prefix."""

from __future__ import annotations

import pytest

from engine.arrival import (
    KEY_INTRODUCTION_KIND,
    ArrivalLog,
    AuthorshipUnverified,
    key_registry,
    key_registry_from_records,
    verify_authorship,
    verify_authorship_records,
)
from tests.conftest import Custodian as _Custodian
from tests.conftest import ed25519_verify as _verify


def _mint(tmp_path, custodian: _Custodian) -> ArrivalLog:
    return ArrivalLog.mint(
        tmp_path / "records.arrival",
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


def test_record_stream_matches_legacy_both_widths(tmp_path):
    kyle = _Custodian(tmp_path, "kyle")
    ana = _Custodian(tmp_path, "ana")
    log = _mint(tmp_path, kyle)
    _introduce(log, kyle, ana)
    log.append("note", {"value": 1}, observer="ana", signer=ana.signer)
    log.append("note", {"value": 2}, observer="kyle", signer=kyle.signer)
    records = tuple(log.walk())

    selective_registry, selective_rows = key_registry_from_records(records, _verify)
    all_registry, all_rows = verify_authorship_records(records, _verify)

    assert selective_registry == key_registry(log, _verify)
    assert all_registry == selective_registry
    assert selective_rows == (all_rows[0], all_rows[1])
    assert all_rows == verify_authorship(log, _verify)


def test_unknown_signed_author_and_preintroduction_position_refuse(tmp_path):
    kyle = _Custodian(tmp_path, "kyle")
    ana = _Custodian(tmp_path, "ana")
    log = _mint(tmp_path, kyle)
    log.append("note", {"value": 1}, observer="ana", signer=ana.signer)
    _introduce(log, kyle, ana)

    with pytest.raises(AuthorshipUnverified) as raised:
        verify_authorship_records(tuple(log.walk()), _verify)
    assert raised.value.ordinal == 1

    unknown = _Custodian(tmp_path, "unknown")
    clean = _mint(tmp_path / "other", kyle)
    clean.append("note", {"value": 1}, observer="unknown", signer=unknown.signer)
    with pytest.raises(AuthorshipUnverified) as raised:
        verify_authorship_records(tuple(clean.walk()), _verify)
    assert raised.value.ordinal == 1


def test_unsigned_ordinary_record_is_legal_and_not_evidence(tmp_path):
    kyle = _Custodian(tmp_path, "kyle")
    log = _mint(tmp_path, kyle)
    log.append("note", {"value": 1}, observer="unknown")

    registry, rows = verify_authorship_records(tuple(log.walk()), _verify)
    assert registry.introductions == {"kyle": ((kyle.public, 0),)}
    assert [row.ordinal for row in rows] == [0]


def test_multiple_key_rotations_resolve_in_order(tmp_path):
    kyle = _Custodian(tmp_path, "kyle")
    ana_first = _Custodian(tmp_path, "ana")
    ana_second = _Custodian(tmp_path / "rotated", "ana")
    log = _mint(tmp_path, kyle)
    first = _introduce(log, kyle, ana_first)
    second = _introduce(log, ana_first, ana_second)
    log.append("note", {"value": 1}, observer="ana", signer=ana_second.signer)

    registry, rows = verify_authorship_records(tuple(log.walk()), _verify)
    assert registry.keys_valid_at("ana", first["ord"] + 1) == (
        (ana_first.public, first["ord"]),
    )
    assert registry.keys_valid_at("ana", second["ord"] + 1) == (
        (ana_first.public, first["ord"]),
        (ana_second.public, second["ord"]),
    )
    assert rows[-1].key == ana_second.public
    assert rows[-1].introduced_ordinal == second["ord"]


def test_record_stream_uses_injected_signature_verifier(tmp_path):
    kyle = _Custodian(tmp_path, "kyle")
    log = _mint(tmp_path, kyle)
    log.append("note", {"value": 1}, observer="kyle", signer=kyle.signer)
    calls: list[tuple[str, str, str]] = []

    def injected(key: str, signature: str, digest: str) -> bool:
        calls.append((key, signature, digest))
        return _verify(key, signature, digest)

    _registry, rows = verify_authorship_records(tuple(log.walk()), injected)
    assert len(rows) == 2
    assert len(calls) == 2
    assert all(call[0] == kyle.public for call in calls)
