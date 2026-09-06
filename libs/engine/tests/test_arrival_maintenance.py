"""Explicit projection maintenance advances only an attested bounded prefix."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import (
    FactRequest,
    Full,
    HeadMismatch,
    NotSupported,
    Profile,
    ProjectionRequirement,
    StoreDescriptor,
)
from engine.arrival_file_backend import FileLedger, FileProjectionMaintenance, FileQuery
from engine.arrival_maintenance import ProjectionSyncError, sync_projection
from engine.arrival_projection import _ensure_index_schema, _meta_get
from engine.arrival_registry import BackendRegistry
from engine.arrival_store import ARRIVAL_ORDINAL_KEY
from engine.residence import index_path_for


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _append_fact(
    log: ArrivalLog,
    signer,
    *,
    fact_id: str,
    kind: str = "note",
    value: int = 1,
) -> None:
    payload = json.dumps({"value": value})
    log.append(
        "fact",
        body_of_fact_row(
            (fact_id, kind, float(value), "kyle", "test", payload, None)
        ),
        observer="kyle",
        origin="test",
        at=float(value),
        signer=signer,
    )


def _store(tmp_path: Path, keys, signer) -> tuple[ArrivalLog, StoreDescriptor]:
    log = ArrivalLog.mint(
        tmp_path / "sample.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
    )
    return log, StoreDescriptor(
        backend="file",
        location=str(log.path),
        lineage=log.lineage(),
        role=Profile.AUTHORITY,
    )


def _head(log: ArrivalLog):
    return FileLedger(log).head()


def test_missing_projection_builds_only_through_attested_target(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    target = _head(log)
    before_bytes = log.path.read_bytes()

    result = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert result.captured_head == target
    assert result.target == target
    assert result.projected_before is None
    assert result.projected_after == target
    assert result.changed is True
    assert result.rebuilt is False
    assert result.view_generation is not None
    assert log.path.read_bytes() == before_bytes
    query = FileQuery(index_path_for(log.path))
    snapshot = query.open_snapshot(
        captured_head=target, requirement=ProjectionRequirement.CURRENT
    )
    try:
        assert [fact.id for fact in snapshot.facts(FactRequest(limit=None)).items] == [
            "fact-1"
        ]
    finally:
        snapshot.close()
        query.close()


def test_catch_up_restores_only_physically_licensed_declaration_marker(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(
        log,
        signer,
        fact_id=log.lineage(),
        kind="_decl.genesis",
    )

    sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    conn = sqlite3.connect(index_path_for(log.path))
    try:
        assert _meta_get(conn, "own_lineage") == log.lineage()
    finally:
        conn.close()


def test_concurrent_append_does_not_expand_requested_prefix(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    target = _head(log)
    original = FileProjectionMaintenance.catch_up
    appended = False

    def append_then_catch_up(self: FileProjectionMaintenance, through):
        nonlocal appended
        if not appended:
            appended = True
            _append_fact(log, signer, fact_id="fact-2", value=2)
        return original(self, through)

    monkeypatch.setattr(FileProjectionMaintenance, "catch_up", append_then_catch_up)

    result = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert result.captured_head == target
    assert result.projected_after == target
    assert _head(log).ordinal == target.ordinal + 1
    assert FileQuery(index_path_for(log.path)).projected_through().ordinal == target.ordinal


def test_projection_already_beyond_target_is_validated_and_left_at_actual_prefix(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    earlier = _head(log)
    _append_fact(log, signer, fact_id="fact-2", value=2)
    latest = _head(log)
    registry = BackendRegistry.with_builtin_backends()
    sync_projection(registry, descriptor)

    result = sync_projection(registry, descriptor, through=earlier)

    assert result.target == earlier
    assert result.projected_before == latest
    assert result.projected_after == latest
    assert result.changed is False


def test_noop_reports_unknown_generation_when_projection_advances_after_capture(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    first = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)
    original_open = FileQuery.open_snapshot
    advanced = False

    def advance_then_open(self: FileQuery, **kwargs):
        nonlocal advanced
        if not advanced:
            advanced = True
            _append_fact(log, signer, fact_id="fact-2", value=2)
            other = FileProjectionMaintenance(log.path, index_path_for(log.path))
            try:
                other.catch_up(_head(log))
            finally:
                other.close()
        return original_open(self, **kwargs)

    monkeypatch.setattr(FileQuery, "open_snapshot", advance_then_open)

    result = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert result.captured_head == first.projected_after
    assert result.target == first.projected_after
    assert result.projected_before == result.projected_after == _head(log)
    assert result.view_generation is None
    assert result.changed is False


def test_behind_projection_advances_from_its_verified_prefix(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    first = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)
    _append_fact(log, signer, fact_id="fact-2", value=2)

    result = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert result.projected_before == first.projected_after
    assert result.projected_after.ordinal == first.projected_after.ordinal + 1
    assert result.changed is True


def test_concurrent_maintainer_is_reobserved_under_projection_lock(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    original = FileProjectionMaintenance.catch_up
    intervened = False

    def run_other_then_continue(self: FileProjectionMaintenance, through):
        nonlocal intervened
        if not intervened:
            intervened = True
            other = FileProjectionMaintenance(log.path, index_path_for(log.path))
            try:
                original(other, through)
            finally:
                other.close()
        return original(self, through)

    monkeypatch.setattr(FileProjectionMaintenance, "catch_up", run_other_then_continue)

    result = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert result.projected_before == result.projected_after == result.target
    assert result.changed is False


def test_maintenance_waits_for_projection_writer_lock(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    index = index_path_for(log.path)
    holder = sqlite3.connect(index)
    _ensure_index_schema(holder, log)
    holder.isolation_level = None
    holder.execute("BEGIN IMMEDIATE")
    started = threading.Event()
    results = []
    failures: list[BaseException] = []

    def maintain() -> None:
        started.set()
        try:
            results.append(
                sync_projection(BackendRegistry.with_builtin_backends(), descriptor)
            )
        except BaseException as exc:  # reported back to the asserting thread
            failures.append(exc)

    worker = threading.Thread(target=maintain)
    worker.start()
    assert started.wait(timeout=1.0)
    time.sleep(0.05)
    assert worker.is_alive()
    holder.commit()
    holder.close()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert failures == []
    assert len(results) == 1
    assert results[0].projected_after == _head(log)


def test_later_maintainer_advance_is_reported_as_successful_actual_prefix(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    requested = _head(log)
    original = FileProjectionMaintenance.catch_up
    intervened = False

    def advance_later_before_return(self: FileProjectionMaintenance, through):
        nonlocal intervened
        advance = original(self, through)
        if not intervened:
            intervened = True
            _append_fact(log, signer, fact_id="fact-2", value=2)
            later = FileProjectionMaintenance(log.path, index_path_for(log.path))
            try:
                original(later, _head(log))
            finally:
                later.close()
        return advance

    monkeypatch.setattr(
        FileProjectionMaintenance, "catch_up", advance_later_before_return
    )

    result = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert result.target == requested
    assert result.projected_after == _head(log)
    assert result.projected_after.ordinal == requested.ordinal + 1
    assert result.view_generation is None
    assert result.changed is True


def test_rebuild_is_explicitly_refused_without_materializing(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    index = index_path_for(log.path)

    with pytest.raises(NotSupported, match="rebuild is not supported"):
        sync_projection(
            BackendRegistry.with_builtin_backends(), descriptor, rebuild=True
        )

    assert not index.exists()


def test_full_target_verification_precedes_projection_mutation(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    verified: list[Full] = []
    original_verify = FileLedger.verify

    def refuse_full(self: FileLedger, scope):
        if isinstance(scope, Full):
            verified.append(scope)
            raise RuntimeError("injected full verification refusal")
        return original_verify(self, scope)

    monkeypatch.setattr(FileLedger, "verify", refuse_full)
    monkeypatch.setattr(
        FileProjectionMaintenance,
        "catch_up",
        lambda *_args: pytest.fail("maintenance ran before full verification"),
    )

    with pytest.raises(RuntimeError, match="full verification refusal"):
        sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert verified == [Full(through=_head(log))]
    assert not index_path_for(log.path).exists()


def test_same_height_change_after_verification_rolls_back_projection(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    target = _head(log)
    original_walk = ArrivalLog.walk_marked

    def changed_walk(self: ArrivalLog, mark):
        offset, records = original_walk(self, mark)

        def changed_records():
            for record, record_mark in records:
                if record["ord"] == target.ordinal:
                    record = {**record, "rh": "same-height-fork"}
                yield record, record_mark

        return offset, changed_records()

    monkeypatch.setattr(ArrivalLog, "walk_marked", changed_walk)

    with pytest.raises(ProjectionSyncError) as caught:
        sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert isinstance(caught.value.cause, HeadMismatch)
    assert "changed at the maintenance target" in str(caught.value.cause)
    conn = sqlite3.connect(index_path_for(log.path))
    try:
        assert conn.execute("SELECT id FROM facts").fetchall() == []
        assert _meta_get(conn, ARRIVAL_ORDINAL_KEY) is None
    finally:
        conn.close()


def test_interrupt_is_not_reclassified_as_projection_failure(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    monkeypatch.setattr(
        FileProjectionMaintenance,
        "catch_up",
        lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        sync_projection(BackendRegistry.with_builtin_backends(), descriptor)


def test_existing_rows_without_mark_refuse_without_row_or_marker_changes(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    index = index_path_for(log.path)
    conn = sqlite3.connect(index)
    _ensure_index_schema(conn, log)
    conn.execute(
        "INSERT INTO facts "
        "(id, kind, ts, observer, origin, payload, signature, "
        "arrival_ordinal, arrival_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("foreign", "note", 1.0, "other", "test", "{}", None, 99, 0),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ProjectionSyncError) as caught:
        sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert "rows without" in str(caught.value.cause)
    conn = sqlite3.connect(index)
    try:
        assert conn.execute("SELECT id FROM facts").fetchall() == [("foreign",)]
        assert _meta_get(conn, "own_lineage") is None
        assert _meta_get(conn, "arrival_ordinal") is None
    finally:
        conn.close()


def test_foreign_identity_marker_refuses_before_projecting_rows(
    tmp_path: Path, keys, signer
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    index = index_path_for(log.path)
    conn = sqlite3.connect(index)
    _ensure_index_schema(conn, log)
    conn.execute(
        "INSERT INTO store_meta (key, value) VALUES ('own_lineage', 'foreign')"
    )
    conn.commit()
    conn.close()

    with pytest.raises(ProjectionSyncError) as caught:
        sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert "differs from log lineage" in str(caught.value.cause)
    conn = sqlite3.connect(index)
    try:
        assert conn.execute("SELECT id FROM facts").fetchall() == []
        assert _meta_get(conn, "own_lineage") == "foreign"
        assert _meta_get(conn, ARRIVAL_ORDINAL_KEY) is None
    finally:
        conn.close()


def test_mid_projection_failure_rolls_back_rows_and_watermark(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, descriptor = _store(tmp_path, keys, signer)
    _append_fact(log, signer, fact_id="fact-1")
    _append_fact(log, signer, fact_id="fact-2", value=2)
    from engine import arrival_file_backend

    original = arrival_file_backend.rows_of_record

    def fail_second(record):
        if record["ord"] == 2:
            raise RuntimeError("injected projection failure")
        return original(record)

    monkeypatch.setattr(arrival_file_backend, "rows_of_record", fail_second)

    with pytest.raises(ProjectionSyncError) as caught:
        sync_projection(BackendRegistry.with_builtin_backends(), descriptor)

    assert isinstance(caught.value.cause, RuntimeError)
    assert caught.value.projected_before is None
    assert caught.value.observed_after is None
    conn = sqlite3.connect(index_path_for(log.path))
    try:
        assert conn.execute("SELECT id FROM facts").fetchall() == []
        assert conn.execute("SELECT id FROM ticks").fetchall() == []
        assert _meta_get(conn, ARRIVAL_ORDINAL_KEY) is None
    finally:
        conn.close()

    monkeypatch.setattr(arrival_file_backend, "rows_of_record", original)
    recovered = sync_projection(BackendRegistry.with_builtin_backends(), descriptor)
    assert recovered.changed is True
    assert recovered.projected_after.ordinal == 2
