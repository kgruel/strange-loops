"""Exact transfer preserves custody and captured resource lifetime."""

from __future__ import annotations

from dataclasses import replace

import pytest

from engine.arrival import ArrivalLog, Entry
from engine.arrival_contract import (
    Head,
    HeadMismatch,
    Profile,
    StoreDescriptor,
)
from engine.arrival_head_seam import AttestedLedger
from engine.arrival_registry import BackendRegistry
from engine.arrival_transfer import (
    open_export,
)


@pytest.fixture(autouse=True)
def isolated_witness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _head(log: ArrivalLog) -> Head:
    row = log.head()
    return Head(row["lin"], row["ord"], row["rh"])


def _fixture(tmp_path, keys, signer):
    source_path = tmp_path / "source.arbitrary"
    log = ArrivalLog.mint(source_path, observer="alice", key=keys.public, signer=signer)
    log.append_marked_many([
        Entry(k="note", body={"value": value}, observer="alice", at=float(value))
        for value in range(3)
    ])
    source = StoreDescriptor("file", str(source_path), role=Profile.AUTHORITY)
    receiver = StoreDescriptor("file", str(tmp_path / "receiver.arbitrary"), role=Profile.REPLICA)
    return BackendRegistry.with_builtin_backends(), log, source, receiver


def test_export_holds_resources_and_stays_at_capture(tmp_path, keys, signer, monkeypatch):
    registry, log, source, _receiver = _fixture(tmp_path, keys, signer)
    closed = []
    original_close = AttestedLedger.close

    def close(self):
        closed.append(self)
        original_close(self)

    monkeypatch.setattr(AttestedLedger, "close", close)
    expected = log.path.read_bytes()
    with open_export(registry, source) as exported:
        assert closed == []
        captured = exported.head
        log.append_marked_many([Entry(k="note", body={"later": True}, observer="alice", at=9.0)])
        assert b"".join(exported.records) == expected
        assert exported.head == captured
        assert exported.manifest["count"] == captured.ordinal + 1
    assert len(closed) == 1


def test_export_refuses_unverified_or_future_selected_head(tmp_path, keys, signer):
    registry, log, source, _receiver = _fixture(tmp_path, keys, signer)
    for through in (replace(_head(log), record_hash="0" * 64), replace(_head(log), ordinal=99)):
        with pytest.raises(HeadMismatch):
            open_export(registry, source, through=through)

