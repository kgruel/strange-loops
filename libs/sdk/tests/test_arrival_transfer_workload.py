"""Public captured-prefix export and forward-restore conformance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.arrival_contract import ProjectionBehind

from sdk import (
    ArrivalRefusal,
    MappedCredentialProvider,
    emit_fact,
    export_target,
    init_vertex,
    read_facts,
    restore_forward,
    sync_target,
    verify_target,
)


@pytest.fixture(autouse=True)
def _isolated_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops-home"))


def test_captured_export_restore_floor_and_explicit_projection_sync(tmp_path: Path) -> None:
    provider = MappedCredentialProvider(
        tmp_path / "custody",
        namespace="transfer-workload",
        receipt_observer="alice",
    )
    provider.create_binding("alice", token="create-alice")

    source = tmp_path / "source.vertex"
    source_store = (tmp_path / "source.arrival").resolve()
    initialized = init_vertex(
        source,
        name="transfer-workload",
        store_type="arrival",
        location=source_store,
        observer="alice",
        strict=True,
        credentials=provider,
    )
    initial_head = verify_target(source).verified_through
    assert initial_head is not None
    assert initialized.store is not None
    assert initialized.store.role == "authority"
    assert initialized.store.lineage == initial_head.lineage == initialized.lineage

    # There is no public artifact-import operation. Installing the exact
    # genesis export and a replica descriptor is bounded fixture setup; every
    # transfer, verification, synchronization, and read below uses the SDK.
    receiver_store = (tmp_path / "receiver.arrival").resolve()
    initial_export = export_target(source, receiver_store, through=initial_head)
    assert initial_export.head == initial_export.captured_head == initial_head
    receiver = tmp_path / "receiver.vertex"
    receiver.write_text(
        source.read_text()
        .replace(str(source_store), str(receiver_store), 1)
        .replace('role="authority"', 'role="replica"', 1)
    )
    receiver_descriptor = receiver.read_bytes()
    initial_sync = sync_target(receiver)
    assert initial_sync.target == initial_head
    assert initial_sync.projected_after == initial_head
    assert initial_sync.changed is True
    initial_read = read_facts(receiver, limit=20, order="oldest")
    assert initial_read.items == []
    assert initial_read.truncated is False
    assert initial_read.basis is not None
    assert initial_read.basis.captured_head == initial_head
    assert initial_read.basis.projected_through == initial_head
    initial_internal = read_facts(
        receiver, limit=20, order="oldest", include_internal=True
    )
    initial_internal_ids = [item["id"] for item in initial_internal.items]
    assert initial_internal_ids
    assert initial_internal.truncated is False
    for result in (initial_export, initial_sync, initial_read, initial_internal):
        json.dumps(result.as_dict(), allow_nan=False)

    selected = emit_fact(
        source,
        "item",
        {"phase": "selected", "value": 1},
        observer="alice",
        origin="transfer-workload",
        ts=10.0,
        id_override="selected-item",
        credentials=provider,
    )
    assert selected.commit is not None
    assert selected.commit.before == initial_head
    selected_head = selected.commit.after
    selected_source_bytes = source_store.read_bytes()
    later = emit_fact(
        source,
        "item",
        {"phase": "later", "value": 2},
        observer="alice",
        origin="transfer-workload",
        ts=11.0,
        id_override="later-item",
        credentials=provider,
    )
    assert later.commit is not None
    assert later.commit.before == selected_head
    current_head = later.commit.after
    current_source_bytes = source_store.read_bytes()
    assert selected_head.lineage == current_head.lineage == initial_head.lineage
    assert initial_head.ordinal < selected_head.ordinal < current_head.ordinal

    retained_artifact = tmp_path / "selected-prefix.arrival"
    retained = export_target(source, retained_artifact, through=selected_head)
    retained_bytes = retained_artifact.read_bytes()
    assert retained.captured_head == current_head
    assert retained.head == selected_head
    assert retained.manifest["lineage"] == selected_head.lineage
    assert retained.manifest["through_ordinal"] == selected_head.ordinal
    assert retained.manifest["through_record_hash"] == selected_head.record_hash
    assert retained.manifest["count"] == selected_head.ordinal + 1
    assert retained.byte_count == len(retained_bytes)
    assert retained_bytes == selected_source_bytes
    assert b"later-item" not in retained_bytes
    assert retained_bytes != current_source_bytes
    json.dumps(retained.as_dict(), allow_nan=False)

    receiver_before_refusal = receiver_store.read_bytes()
    with pytest.raises(ArrivalRefusal) as rollback:
        restore_forward(source, receiver, through=selected_head)
    assert rollback.value.source_type == "HeadRollback"
    json.dumps(rollback.value.as_dict(), allow_nan=False)
    assert receiver_store.read_bytes() == receiver_before_refusal
    assert retained_artifact.read_bytes() == retained_bytes
    assert receiver.read_bytes() == receiver_descriptor

    restored = restore_forward(source, receiver)
    assert restored.captured_head == current_head
    assert restored.before == initial_head
    assert restored.after == current_head
    assert restored.commit is not None
    assert restored.commit.before == restored.before
    assert restored.commit.after == restored.after
    assert restored.receiver_store.role == "replica"
    assert receiver_store.read_bytes() == current_source_bytes
    assert receiver_store.read_bytes().startswith(receiver_before_refusal)
    assert receiver.read_bytes() == receiver_descriptor
    json.dumps(restored.as_dict(), allow_nan=False)

    verified = verify_target(receiver)
    assert verified.captured_head == current_head
    assert verified.verified_through == current_head
    assert verified.claims == ("grammar", "density", "lineage", "hash-chain")
    assert verified.excludes == (
        "signature-authorship",
        "external-key-trust",
        "projection",
    )

    # Custody advanced, but restore deliberately did not mutate the derived
    # projection. Reads refuse until the caller explicitly catches it up.
    with pytest.raises(ProjectionBehind):
        read_facts(receiver, limit=20, order="oldest")

    synced = sync_target(receiver)
    assert synced.captured_head == current_head
    assert synced.target == current_head
    assert synced.projected_before == initial_head
    assert synced.projected_after == current_head
    assert synced.changed is True
    assert synced.agreement is True

    receiver_read = read_facts(receiver, limit=20, order="oldest")
    assert receiver_read.truncated is False
    assert receiver_read.basis is not None
    assert receiver_read.basis.captured_head == current_head
    assert receiver_read.basis.projected_through == current_head
    assert [
        (item["id"], item["observer"], item["payload"])
        for item in receiver_read.items
    ] == [
        ("selected-item", "alice", {"phase": "selected", "value": 1}),
        ("later-item", "alice", {"phase": "later", "value": 2}),
    ]
    receiver_internal = read_facts(
        receiver, limit=20, order="oldest", include_internal=True
    )
    assert receiver_internal.truncated is False
    assert receiver_internal.items[: len(initial_internal.items)] == initial_internal.items
    assert [item["id"] for item in receiver_internal.items] == [
        *initial_internal_ids,
        "selected-item",
        "later-item",
    ]

    source_read = read_facts(source, limit=20, order="oldest")
    source_internal = read_facts(
        source, limit=20, order="oldest", include_internal=True
    )
    assert source_read.items == receiver_read.items
    assert source_read.basis == receiver_read.basis
    assert source_internal.items == receiver_internal.items
    assert source_internal.basis == receiver_internal.basis
    receiver_before_noop = receiver_store.read_bytes()
    repeated = restore_forward(source, receiver)
    assert repeated.before == repeated.after == current_head
    assert repeated.commit is None
    assert receiver_store.read_bytes() == receiver_before_noop
    assert receiver.read_bytes() == receiver_descriptor
    for result in (
        restored,
        verified,
        synced,
        receiver_read,
        receiver_internal,
        source_read,
        source_internal,
        repeated,
    ):
        json.dumps(result.as_dict(), allow_nan=False)
