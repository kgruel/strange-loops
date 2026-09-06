"""Restore-forward keeps rollback detection and exact custody together."""

from dataclasses import replace
from pathlib import Path

import pytest

from engine.arrival import ArrivalLog, Entry
from engine.arrival_contract import (
    AtomicLimitExceeded,
    Head,
    HeadMismatch,
    Profile,
    StoreDescriptor,
)
from engine.arrival_file_backend import FileLedger
from engine.arrival_head_attestation import HeadRollback, journal_path, read_journal
from engine.arrival_head_seam import AbandonedHistoryFenced, AttestedLedger, trust_reset
from engine.arrival_registry import BackendRegistry
from engine.arrival_restore import RestoreForwardIncomplete, RestoreForwardUnknown


@pytest.fixture(autouse=True)
def isolated_witness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _head(log):
    row = log.head()
    return Head(row["lin"], row["ord"], row["rh"])


def _fixture(tmp_path, keys, signer):
    source_path = tmp_path / "source.arrival"
    receiver_path = tmp_path / "receiver.arrival"
    log = ArrivalLog.mint(source_path, observer="alice", key=keys.public, signer=signer)
    receiver_path.write_bytes(source_path.read_bytes())
    before = _head(log)
    log.append_marked_many(
        [
            Entry(k="note", body={"value": value}, observer="alice", at=float(value))
            for value in range(3)
        ]
    )
    source = StoreDescriptor("file", str(source_path), role=Profile.AUTHORITY)
    receiver = StoreDescriptor("file", str(receiver_path), role=Profile.REPLICA)
    return BackendRegistry.with_builtin_backends(), log, source, receiver, before


def _remember(registry, descriptor):
    ledger, query = registry.open(descriptor)
    query.close()
    ledger.close()


def test_restore_exact_prefix_then_ordinary_open_and_repeat(tmp_path, keys, signer):
    from engine.arrival_file_backend import file_projection_path

    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)
    assert not file_projection_path(receiver.location).exists()
    _remember(registry, source)
    with pytest.raises(HeadRollback):
        registry.open(receiver)
    witness = journal_path(before.lineage).read_bytes()
    result = registry.restore_forward(source, receiver)
    assert result.before == before
    assert result.after == _head(log)
    assert result.commit.before == before
    assert Path(receiver.location).read_bytes() == log.path.read_bytes()
    assert not file_projection_path(receiver.location).exists()
    assert journal_path(before.lineage).read_bytes().startswith(witness)
    assert read_journal(before.lineage).established_head().head == result.after
    ledger, query = registry.open(receiver)
    assert not hasattr(result, "append")
    assert ledger.head() == result.after
    query.close()
    ledger.close()
    again = registry.restore_forward(source, receiver)
    assert again.commit is None
    assert again.before == again.after == result.after


def test_selected_head_below_witness_refuses_without_receiver_write(tmp_path, keys, signer):
    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)
    original = Path(receiver.location).read_bytes()
    _remember(registry, source)
    witness = journal_path(before.lineage).read_bytes()
    with pytest.raises(HeadRollback):
        registry.restore_forward(source, receiver, through=before)
    assert Path(receiver.location).read_bytes() == original
    assert journal_path(before.lineage).read_bytes() == witness


def test_forked_receiver_refuses(tmp_path, keys, signer):
    registry, log, source, receiver, _before = _fixture(tmp_path, keys, signer)
    other = ArrivalLog(receiver.location)
    other.append_marked_many([Entry(k="note", body={"fork": True}, observer="alice", at=1.0)])
    original = Path(receiver.location).read_bytes()
    with pytest.raises(HeadMismatch, match="exact receiver head"):
        registry.restore_forward(source, receiver)
    assert Path(receiver.location).read_bytes() == original


def test_missing_receiver_is_not_silently_created(tmp_path, keys, signer):
    from engine.arrival import GenesisRefused

    registry, log, source, receiver, _before = _fixture(tmp_path, keys, signer)
    Path(receiver.location).unlink()
    with pytest.raises(GenesisRefused):
        registry.restore_forward(source, receiver)
    assert not Path(receiver.location).exists()


def test_atomic_limit_refuses_without_chunking(tmp_path, keys, signer, monkeypatch):
    registry, log, source, receiver, _before = _fixture(tmp_path, keys, signer)
    original = Path(receiver.location).read_bytes()
    capabilities = FileLedger.capabilities
    monkeypatch.setattr(
        FileLedger, "capabilities", lambda self: replace(capabilities(self), max_atomic_records=1)
    )
    with pytest.raises(AtomicLimitExceeded):
        registry.restore_forward(source, receiver)
    assert Path(receiver.location).read_bytes() == original


def test_receiver_cas_race_is_refusal(tmp_path, keys, signer, monkeypatch):
    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)
    replicate = FileLedger.replicate
    competing = []

    def race(self, expected, records):
        assert expected == before
        other = ArrivalLog(receiver.location)
        other.append_marked_many([Entry(k="note", body={"race": True}, observer="alice", at=9.0)])
        competing.append(Path(receiver.location).read_bytes())
        return replicate(self, expected, records)

    monkeypatch.setattr(FileLedger, "replicate", race)
    with pytest.raises(HeadMismatch):
        registry.restore_forward(source, receiver)
    assert Path(receiver.location).read_bytes() == competing[0]
    assert read_journal(before.lineage).established_head().head == _head(log)


def test_lost_receipt_retains_exact_reconciliation_heads(tmp_path, keys, signer, monkeypatch):
    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)
    replicate = FileLedger.replicate

    def lost(self, expected, records):
        replicate(self, expected, records)
        raise OSError("lost reply after commit")

    monkeypatch.setattr(FileLedger, "replicate", lost)
    with pytest.raises(RestoreForwardUnknown) as caught:
        registry.restore_forward(source, receiver)
    assert caught.value.before == before
    assert caught.value.target == _head(log)
    assert Path(receiver.location).read_bytes() == log.path.read_bytes()
    monkeypatch.setattr(FileLedger, "replicate", replicate)
    assert registry.restore_forward(source, receiver).commit is None


def test_witness_failure_retains_commit(tmp_path, keys, signer, monkeypatch):
    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)

    def fail(self, commit):
        raise OSError("injected witness failure")

    monkeypatch.setattr(AttestedLedger, "_witness", fail)
    with pytest.raises(RestoreForwardIncomplete) as caught:
        registry.restore_forward(source, receiver)
    assert caught.value.commit.before == before
    assert caught.value.commit.after == _head(log)
    assert Path(receiver.location).read_bytes() == log.path.read_bytes()


def test_reset_fence_is_not_lifted_by_restore(tmp_path, keys, signer):
    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)
    _remember(registry, source)
    trust_reset(
        accepted=before,
        abandoned=_head(log),
        refused=None,
        reason="test abandoned history",
        location=source.location,
        observed_at=100.0,
    )
    original = Path(receiver.location).read_bytes()
    witness = journal_path(before.lineage).read_bytes()
    with pytest.raises(AbandonedHistoryFenced):
        registry.restore_forward(source, receiver)
    assert Path(receiver.location).read_bytes() == original
    assert journal_path(before.lineage).read_bytes() == witness


def test_witness_advancing_during_commit_reports_incomplete(tmp_path, keys, signer, monkeypatch):
    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)
    replicate = FileLedger.replicate
    selected = _head(log)

    def race(self, expected, records):
        commit = replicate(self, expected, records)
        log.append_marked_many([Entry(k="note", body={"later": True}, observer="alice", at=9.0)])
        _remember(registry, source)
        return commit

    monkeypatch.setattr(FileLedger, "replicate", race)
    with pytest.raises(RestoreForwardIncomplete) as caught:
        registry.restore_forward(source, receiver)
    assert caught.value.commit.after == selected
    assert isinstance(caught.value.cause, HeadRollback)
    assert read_journal(before.lineage).established_head().head == _head(log)
    with pytest.raises(HeadRollback):
        registry.open(receiver)


def test_projection_evidence_beyond_selected_prefix_refuses(tmp_path, keys, signer):
    from engine.arrival_contract import Watermark
    from engine.arrival_file_backend import FileQuery, file_projection_path
    from engine.arrival_head_seam import ProjectionAheadOfLedger

    _registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)

    class AheadQuery:
        def projected_through(self):
            return Watermark(before.lineage, _head(log).ordinal + 1)

        def close(self):
            pass

    def opener(descriptor):
        ledger = FileLedger(ArrivalLog(descriptor.location))
        query = (
            AheadQuery()
            if descriptor.location == receiver.location
            else FileQuery(file_projection_path(descriptor.location))
        )
        return ledger, query

    registry = BackendRegistry()
    registry.register("test", opener)
    original = Path(receiver.location).read_bytes()
    with pytest.raises(ProjectionAheadOfLedger):
        registry.restore_forward(replace(source, backend="test"), replace(receiver, backend="test"))
    assert Path(receiver.location).read_bytes() == original


def test_restore_refuses_fork_projection_ahead_of_actual_receiver(tmp_path, keys, signer):
    """Installing a valid suffix must not relabel a fork's derived rows."""
    from engine.arrival_body import body_of_fact_row
    from engine.arrival_file_backend import FileProjectionMaintenance, file_projection_path
    from engine.arrival_head_seam import ProjectionAheadOfLedger

    registry = BackendRegistry.with_builtin_backends()
    log = ArrivalLog.mint(
        tmp_path / "source.arrival", observer="alice", key=keys.public, signer=signer
    )
    receiver_path = tmp_path / "receiver.arrival"
    source = StoreDescriptor("file", str(log.path), role=Profile.AUTHORITY)
    receiver = StoreDescriptor("file", str(receiver_path), role=Profile.REPLICA)
    prefix = log.path.read_bytes()
    before = _head(log)
    receiver_path.write_bytes(prefix)
    fork = ArrivalLog(receiver_path)
    for ledger, identifier in ((log, "source-fact"), (fork, "forked-fact")):
        ledger.append(
            "fact", body_of_fact_row((identifier, "note", 1.0, "alice", "test", "{}", None)),
            observer="alice", origin="test", at=1.0,
        )
    assert receiver_path.stat().st_size == log.path.stat().st_size
    index = file_projection_path(receiver.location)
    maintenance = FileProjectionMaintenance(receiver_path, index)
    try:
        maintenance.catch_up(_head(fork))
    finally:
        maintenance.close()
    projection_bytes = index.read_bytes()
    receiver_path.write_bytes(prefix)
    assert _head(fork) == before

    with pytest.raises(ProjectionAheadOfLedger):
        registry.restore_forward(source, receiver)

    assert receiver_path.read_bytes() == prefix
    assert index.read_bytes() == projection_bytes


def test_restore_refuses_same_ordinal_fork_projection(tmp_path, keys, signer):
    """A level watermark cannot stand in for the record hash it lacks."""
    from engine.arrival_body import body_of_fact_row
    from engine.arrival_file_backend import FileProjectionMaintenance, file_projection_path

    registry = BackendRegistry.with_builtin_backends()
    source_log = ArrivalLog.mint(
        tmp_path / "source.arrival", observer="alice", key=keys.public, signer=signer
    )
    receiver_path = tmp_path / "receiver.arrival"
    receiver_path.write_bytes(source_log.path.read_bytes())
    source = StoreDescriptor("file", str(source_log.path), role=Profile.AUTHORITY)
    receiver = StoreDescriptor("file", str(receiver_path), role=Profile.REPLICA)
    fork = ArrivalLog(receiver_path)
    source_log.append(
        "fact",
        body_of_fact_row(("source-row", "note", 1.0, "alice", "test", "{}", None)),
        observer="alice",
        origin="test",
        at=1.0,
        signer=signer,
    )
    fork.append(
        "fact",
        body_of_fact_row(("fork-row", "note", 1.0, "alice", "test", "{}", None)),
        observer="alice",
        origin="test",
        at=1.0,
        signer=signer,
    )
    fork_head = _head(fork)
    index = file_projection_path(receiver.location)
    maintenance = FileProjectionMaintenance(receiver_path, index)
    try:
        maintenance.catch_up(fork_head)
    finally:
        maintenance.close()
    projection_bytes = index.read_bytes()
    receiver_path.write_bytes(source_log.path.read_bytes())
    assert fork_head.ordinal == _head(source_log).ordinal
    assert fork_head.record_hash != _head(source_log).record_hash

    with pytest.raises(HeadMismatch, match="projection rows do not exactly match"):
        registry.restore_forward(source, receiver)

    assert receiver_path.read_bytes() == source_log.path.read_bytes()
    assert index.read_bytes() == projection_bytes


def test_restore_accepts_healthy_level_projection(tmp_path, keys, signer):
    """The explicit audit accepts a projection derived from the exact head."""
    from engine.arrival_body import body_of_fact_row
    from engine.arrival_file_backend import FileProjectionMaintenance, file_projection_path

    registry = BackendRegistry.with_builtin_backends()
    source_log = ArrivalLog.mint(
        tmp_path / "source.arrival", observer="alice", key=keys.public, signer=signer
    )
    source_log.append(
        "fact",
        body_of_fact_row(("same-row", "note", 1.0, "alice", "test", "{}", None)),
        observer="alice",
        origin="test",
        at=1.0,
        signer=signer,
    )
    receiver_path = tmp_path / "receiver.arrival"
    receiver_path.write_bytes(source_log.path.read_bytes())
    source = StoreDescriptor("file", str(source_log.path), role=Profile.AUTHORITY)
    receiver = StoreDescriptor("file", str(receiver_path), role=Profile.REPLICA)
    maintenance = FileProjectionMaintenance(receiver_path, file_projection_path(receiver_path))
    try:
        maintenance.catch_up(_head(source_log))
    finally:
        maintenance.close()

    result = registry.restore_forward(source, receiver)

    assert result.commit is None
    assert result.before == result.after == _head(source_log)


def test_restore_audits_healthy_declared_prefix_then_packed_facts_and_tick(
    tmp_path, monkeypatch, keys, signer
):
    """Both a lagging adopted projection and full batch/tick rows audit cleanly."""
    from atoms import Fact

    from engine.arrival_file_backend import FileProjectionMaintenance, file_projection_path
    from engine.arrival_maintenance import sync_projection
    from engine.credentials import WriteCredentials
    from engine.runtime_write import BatchFactInput, execute_batch_write, prepare_batch_write
    from tests.test_runtime_batch_write import _make_target

    target = _make_target(
        tmp_path, monkeypatch, keys, signer, boundary="boundary every=2"
    )
    receiver_path = tmp_path / "receiver.arrival"
    receiver_path.write_bytes(target.log.path.read_bytes())
    receiver = replace(target.descriptor, location=str(receiver_path), role=Profile.REPLICA)
    maintenance = FileProjectionMaintenance(receiver_path, file_projection_path(receiver_path))
    try:
        maintenance.catch_up(_head(target.log))
    finally:
        maintenance.close()
    plan = prepare_batch_write(
        target.registry, target.descriptor, target.locator,
        tuple(
            BatchFactInput(Fact("note", ts, {"n": ts}, observer="kyle"), fact_id=f"note-{ts}")
            for ts in (3.0, 4.0)
        ),
        credentials=WriteCredentials(tick_signer=lambda digest: signer("kyle", digest)),
    )
    assert [draft.kind for draft in plan.drafts] == ["batch", "tick"]
    execute_batch_write(target.registry, target.descriptor, plan)

    restored = target.registry.restore_forward(target.descriptor, receiver)
    assert restored.commit is not None
    assert receiver_path.read_bytes() == target.log.path.read_bytes()
    sync_projection(target.registry, receiver)
    assert target.registry.restore_forward(target.descriptor, receiver).commit is None


def test_restore_refuses_projection_missing_adopted_declaration_anchor(
    tmp_path, keys, signer
):
    """Projected own genesis rows require their same-prefix identity marker."""
    import sqlite3

    from atoms import Fact as AtomFact

    from engine.arrival_file_backend import FileProjectionMaintenance, file_projection_path
    from engine.arrival_store import ArrivalStore
    from engine.residence import index_path_for

    registry = BackendRegistry.with_builtin_backends()
    source_log = ArrivalLog.mint(
        tmp_path / "source.arrival", observer="alice", key=keys.public, signer=signer
    )
    source_store = ArrivalStore(
        path=index_path_for(source_log.path),
        log_path=source_log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    try:
        source_store.absorb_genesis([], observer="alice", fact_signer=signer)
    finally:
        source_store.close()
    receiver_path = tmp_path / "receiver.arrival"
    receiver_path.write_bytes(source_log.path.read_bytes())
    source = StoreDescriptor("file", str(source_log.path), role=Profile.AUTHORITY)
    receiver = StoreDescriptor("file", str(receiver_path), role=Profile.REPLICA)
    projection_path = file_projection_path(receiver_path)
    maintenance = FileProjectionMaintenance(receiver_path, projection_path)
    try:
        maintenance.catch_up(_head(source_log))
    finally:
        maintenance.close()
    with sqlite3.connect(projection_path) as conn:
        conn.execute("DELETE FROM store_meta WHERE key = 'own_lineage'")

    with pytest.raises(HeadMismatch, match="does not name the audited declaration genesis"):
        registry.restore_forward(source, receiver)


def test_postcommit_projection_audit_failure_retains_commit(tmp_path, keys, signer, monkeypatch):
    """A mismatch found after durable replication remains reconcilable."""
    import sqlite3

    from engine.arrival_body import body_of_fact_row
    from engine.arrival_file_backend import FileProjectionMaintenance, file_projection_path

    registry = BackendRegistry.with_builtin_backends()
    source_log = ArrivalLog.mint(
        tmp_path / "source.arrival", observer="alice", key=keys.public, signer=signer
    )
    receiver_path = tmp_path / "receiver.arrival"
    receiver_path.write_bytes(source_log.path.read_bytes())
    source = StoreDescriptor("file", str(source_log.path), role=Profile.AUTHORITY)
    receiver = StoreDescriptor("file", str(receiver_path), role=Profile.REPLICA)
    source_log.append(
        "fact",
        body_of_fact_row(("source-row", "note", 1.0, "alice", "test", "{}", None)),
        observer="alice",
        origin="test",
        at=1.0,
        signer=signer,
    )
    original = FileLedger.replicate

    def corrupt_after_commit(self, expected, records):
        commit = original(self, expected, records)
        projection_path = file_projection_path(receiver_path)
        maintenance = FileProjectionMaintenance(receiver_path, projection_path)
        try:
            maintenance.catch_up(commit.after)
        finally:
            maintenance.close()
        with sqlite3.connect(projection_path) as conn:
            conn.execute(
                "UPDATE facts SET payload = ? WHERE id = ?",
                ('{"fork":true}', "source-row"),
            )
        return commit

    monkeypatch.setattr(FileLedger, "replicate", corrupt_after_commit)

    with pytest.raises(RestoreForwardIncomplete) as caught:
        registry.restore_forward(source, receiver)

    assert caught.value.commit.before.ordinal == 0
    assert caught.value.commit.after == _head(source_log)
    assert receiver_path.read_bytes() == source_log.path.read_bytes()


def test_backend_opaque_locations_and_resource_closure(tmp_path, keys, signer):
    from engine.arrival_file_backend import FileQuery, file_projection_path

    _registry, log, source, receiver, _before = _fixture(tmp_path, keys, signer)
    locations = {
        "service://source?a=b": source.location,
        "service://receiver?a=b": receiver.location,
    }
    closed = []

    class Ledger(FileLedger):
        def close(self):
            closed.append(self)

    class Query(FileQuery):
        def close(self):
            closed.append(self)
            super().close()

    def opener(descriptor):
        path = locations[descriptor.location]
        return Ledger(ArrivalLog(path)), Query(file_projection_path(path))

    registry = BackendRegistry()
    registry.register("service", opener)
    result = registry.restore_forward(
        replace(source, backend="service", location="service://source?a=b"),
        replace(receiver, backend="service", location="service://receiver?a=b"),
    )
    assert result.after == _head(log)
    assert Path(receiver.location).read_bytes() == log.path.read_bytes()
    assert len(closed) == 4
    assert len(set(map(id, closed))) == 4


def test_reset_during_append_is_reported_without_reaccepting_abandoned_history(
    tmp_path, keys, signer, monkeypatch
):
    registry, log, source, receiver, before = _fixture(tmp_path, keys, signer)
    replicate = FileLedger.replicate
    reset_bytes = []

    def reset(self, expected, records):
        commit = replicate(self, expected, records)
        trust_reset(
            accepted=before,
            abandoned=commit.after,
            refused=None,
            reason="concurrent operator reset",
            location=source.location,
            observed_at=100.0,
        )
        reset_bytes.append(journal_path(before.lineage).read_bytes())
        return commit

    monkeypatch.setattr(FileLedger, "replicate", reset)
    with pytest.raises(RestoreForwardIncomplete) as caught:
        registry.restore_forward(source, receiver)
    assert isinstance(caught.value.cause, AbandonedHistoryFenced)
    assert journal_path(before.lineage).read_bytes() == reset_bytes[0]
    assert read_journal(before.lineage).established_head().head == before
    assert Path(receiver.location).read_bytes() == log.path.read_bytes()
