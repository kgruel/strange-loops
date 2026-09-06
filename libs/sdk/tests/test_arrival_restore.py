"""SDK restoration keeps exact custody and typed failure evidence."""

import json
from pathlib import Path

import pytest
from engine.arrival import ArrivalLog, Entry
from engine.arrival_file_backend import FileLedger

from sdk import (
    ArrivalRefusal,
    CommittedIncomplete,
    CommittedOutcomeUnknown,
    TargetUnsupported,
    init_vertex,
    restore_forward,
    verify_target,
)


@pytest.fixture(autouse=True)
def isolated_witness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _fixture(tmp_path):
    source = tmp_path / "source.vertex"
    initialized = init_vertex(source, backend="file", location="source.arrival", observer="alice")
    source_log = Path(initialized.store.location)
    receiver_log = tmp_path / "receiver.arrival"
    receiver_log.write_bytes(source_log.read_bytes())
    receiver = tmp_path / "receiver.vertex"
    receiver.write_text(
        'name "copy"\n'
        f'store "{receiver_log}" backend="file" '
        f'lineage="{initialized.store.lineage}" role="replica"\n'
        'loops { note { fold { items "collect" 10; } } }\n'
    )
    log = ArrivalLog(source_log)
    log.append_marked_many([Entry(k="note", body={"value": 1}, observer="alice", at=3.0)])
    verify_target(source)
    return source, receiver, source_log, receiver_log


def test_sdk_restore_replica_and_repeat(tmp_path):
    source, receiver, source_log, receiver_log = _fixture(tmp_path)
    with pytest.raises(ArrivalRefusal) as rollback:
        verify_target(receiver)
    assert rollback.value.source_type == "HeadRollback"
    result = restore_forward(source, receiver)
    assert result.commit.after == result.after == result.captured_head
    assert result.receiver_store.role == "replica"
    assert receiver_log.read_bytes() == source_log.read_bytes()
    encoded = result.as_dict()
    assert encoded["schema"] == "loops.sdk/restore-forward/v2"
    json.dumps(encoded, allow_nan=False)
    assert restore_forward(source, receiver).commit is None
    verify_target(receiver)


def test_sdk_unknown_receipt_retains_before_and_target(tmp_path, monkeypatch):
    source, receiver, source_log, receiver_log = _fixture(tmp_path)
    replicate = FileLedger.replicate

    def lost(self, expected, records):
        replicate(self, expected, records)
        raise OSError("lost reply")

    monkeypatch.setattr(FileLedger, "replicate", lost)
    with pytest.raises(CommittedOutcomeUnknown) as caught:
        restore_forward(source, receiver)
    error = caught.value.as_dict()
    assert error["outcome"] == "unknown"
    assert error["details"]["before"]["ordinal"] < error["details"]["target"]["ordinal"]
    assert receiver_log.read_bytes() == source_log.read_bytes()
    json.dumps(error, allow_nan=False)


def test_sdk_known_commit_is_not_normalized_as_refusal(tmp_path, monkeypatch):
    import engine.arrival_restore as restoration

    source, receiver, source_log, receiver_log = _fixture(tmp_path)

    def failed(*args, **kwargs):
        raise OSError("binding write failed")

    monkeypatch.setattr(restoration, "record_binding", failed)
    with pytest.raises(CommittedIncomplete) as caught:
        restore_forward(source, receiver)
    error = caught.value.as_dict()
    assert error["outcome"] == "committed-incomplete"
    assert error["details"]["commit"]["after"] == error["details"]["after"]
    assert receiver_log.read_bytes() == source_log.read_bytes()
    json.dumps(error, allow_nan=False)


def test_sdk_restore_has_no_legacy_fallback(tmp_path):
    source, receiver, _source_log, _receiver_log = _fixture(tmp_path)
    receiver.write_text('name "legacy"\nstore "legacy.db"\n')
    with pytest.raises(TargetUnsupported):
        restore_forward(source, receiver)
