"""Supported atomic Arrival batch planning and execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from atoms import Fact as AtomFact
from lang import genesis_payload, parse_vertex
from lang.ast import VertexFile

from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog, content_commitment
from engine.arrival_binding import file_binding
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import (
    AtomicLimitExceeded,
    FactRequest,
    Head,
    HeadMismatch,
    Profile,
    ProjectionBehind,
    ProjectionRequirement,
    RecordDraft,
    StoreDescriptor,
    TickRequest,
)
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_head_attestation import IndeterminateComparison
from engine.arrival_head_seam import AttestedLedger, Indeterminate
from engine.arrival_maintenance import sync_projection
from engine.arrival_registry import BackendRegistry
from engine.handle import WriteCredentials
from engine.residence import index_path_for
from engine.row_commitment import fact_row_hash, tick_commitment_hash, tick_row_hash
from engine.runtime_write import (
    BatchFactInput,
    BatchItemResult,
    BatchPostCommitProjectionFailed,
    BatchWriteCommitUnknown,
    BatchWritePlan,
    BatchWritePreparationRefused,
    ProjectionOutcome,
    RuntimeWriteRefused,
    execute_batch_write,
    prepare_batch_write,
)


@dataclass(frozen=True)
class _Target:
    vertex: Path
    locator: VertexFile
    log: ArrivalLog
    descriptor: StoreDescriptor
    registry: BackendRegistry


def _make_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    keys,
    signer,
    *,
    boundary: str = "",
    observers: str | None = None,
    max_atomic_records: int | None = None,
    source_text: str = "",
    extra_loops: str = "",
) -> _Target:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    log = ArrivalLog.mint(
        tmp_path / "batch.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
        at=1.0,
    )
    vertex = tmp_path / "batch.vertex"
    observer_block = observers or ("observers {\n  kyle { }\n  alice { }\n  bob { }\n}\n")
    source = (
        'name "batch-target"\n'
        f'store "{log.path}" backend="file" lineage="{log.lineage()}" '
        'role="authority"\n'
        "strict true\n"
        f"{observer_block}"
        f"{source_text}"
        "loops {\n"
        "  note {\n"
        '    fold { items "collect" 20 }\n'
        f"    {boundary}\n"
        "  }\n"
        f"{extra_loops}"
        "}\n"
    )
    vertex.write_text(source, encoding="utf-8")
    locator = parse_vertex(source, vertex)
    declaration = json.dumps(genesis_payload(locator))
    declaration_signature = signer(
        "kyle",
        fact_commitment_hash("_decl.genesis", 2.0, "kyle", "test", declaration),
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "kyle",
                "test",
                declaration,
                declaration_signature,
            )
        ),
        observer="kyle",
        origin="test",
        at=2.0,
        signer=signer,
    )
    descriptor = StoreDescriptor(
        "file",
        str(log.path),
        lineage=log.lineage(),
        role=Profile.AUTHORITY,
    )
    if max_atomic_records is None:
        registry = BackendRegistry.with_builtin_backends()
    else:
        registry = BackendRegistry()
        registry.register(
            "file",
            lambda _descriptor: (
                FileLedger(log, max_atomic_records=max_atomic_records),
                FileQuery(index_path_for(log.path)),
            ),
            binding_provider=lambda registered: file_binding(registered.location),
        )
    # Materialization is explicit and complete before supported preparation.
    # A limited registry has no maintenance provider, so bootstrap through the
    # same built-in file adapter first; both name the same custody identity.
    sync_projection(
        BackendRegistry.with_builtin_backends(),
        descriptor,
        through=FileLedger(log).head(),
    )
    return _Target(vertex, locator, log, descriptor, registry)


def _fact(identifier: str, ts: float, *, observer: str = "kyle", value: str = "x"):
    return BatchFactInput(
        AtomFact("note", ts, {"value": value}, observer=observer, origin="test"),
        fact_id=identifier,
    )


def _prepare(target: _Target, *items: BatchFactInput, credentials=None):
    return prepare_batch_write(
        target.registry,
        target.descriptor,
        target.locator,
        items,
        credentials=credentials or WriteCredentials(),
    )


def _sync_after(target: _Target):
    return lambda head: sync_projection(target.registry, target.descriptor, through=head)


def _registry_with_limit(target: _Target, limit: int) -> BackendRegistry:
    registry = BackendRegistry()
    registry.register(
        "file",
        lambda _descriptor: (
            FileLedger(target.log, max_atomic_records=limit),
            FileQuery(index_path_for(target.log.path)),
        ),
        binding_provider=lambda registered: file_binding(registered.location),
    )
    return registry


def test_real_same_observer_batch_is_one_wire_record_and_one_shared_commit(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    before = FileLedger(target.log).head()
    credentials = WriteCredentials(fact_signer=signer, arrival_signer=signer)
    plan = _prepare(
        target,
        _fact("one", 3.0),
        _fact("two", 4.0),
        credentials=credentials,
    )

    assert [draft.kind for draft in plan.drafts] == ["batch"]
    assert [row["id"] for row in plan.drafts[0].body["rows"]] == ["one", "two"]
    from sign import ed25519

    batch_draft = plan.drafts[0]
    assert batch_draft.signature is not None
    assert ed25519.verify(
        ed25519.public_key_from_b64(keys.public),
        batch_draft.signature,
        content_commitment(
            "batch",
            batch_draft.authored_at,
            batch_draft.observer,
            batch_draft.origin,
            batch_draft.body,
        ).encode(),
        domain="test-arrival-v1",
    )
    assert all("signature" in row for row in batch_draft.body["rows"])
    outcome = execute_batch_write(
        target.registry,
        target.descriptor,
        plan,
        after_commit=_sync_after(target),
    )

    assert outcome.commit is not None
    assert outcome.commit.before == before
    assert outcome.commit.after.ordinal == before.ordinal + 1
    assert len(outcome.commit.records) == 1
    assert outcome.items == plan.items
    assert outcome.projection is ProjectionOutcome.SYNCED
    assert [record["k"] for record in target.log.walk()][-1] == "batch"
    snapshot = FileQuery(index_path_for(target.log.path)).open_snapshot(
        captured_head=outcome.commit.after,
        requirement=ProjectionRequirement.CURRENT,
    )
    try:
        assert [
            fact.id for fact in snapshot.facts(FactRequest(limit=None, order="oldest")).items
        ] == ["one", "two"]
    finally:
        snapshot.close()


def test_batch_fact_signer_does_not_sign_the_arrival_envelope(tmp_path, monkeypatch, keys, signer):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    plan = _prepare(
        target,
        _fact("one", 3.0),
        _fact("two", 4.0),
        credentials=WriteCredentials(
            fact_signer=lambda observer, digest: f"fact:{observer}:{digest}"
        ),
    )

    assert [draft.kind for draft in plan.drafts] == ["batch"]
    assert all(row["signature"].startswith("fact:kyle:") for row in plan.drafts[0].body["rows"])
    assert plan.drafts[0].signature is None


def test_real_mixed_observers_use_separate_records_under_one_commit(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    before = FileLedger(target.log).head()
    plan = _prepare(
        target,
        _fact("alice", 3.0, observer="alice"),
        _fact("bob", 4.0, observer="bob"),
    )

    assert [draft.kind for draft in plan.drafts] == ["fact", "fact"]
    outcome = execute_batch_write(target.registry, target.descriptor, plan)
    assert outcome.commit is not None
    assert outcome.commit.before == before
    assert outcome.commit.after.ordinal == before.ordinal + 2
    assert len(outcome.commit.records) == 2
    assert [record["observer"] for record in outcome.commit.records] == [
        "alice",
        "bob",
    ]


def test_invalid_later_item_refuses_the_whole_plan_before_append(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    before = target.log.path.read_bytes()
    invalid = BatchFactInput(
        AtomFact("other", 4.0, {}, observer="kyle", origin="test"),
        fact_id="invalid",
    )

    with pytest.raises(BatchWritePreparationRefused) as raised:
        _prepare(target, _fact("valid", 3.0), invalid)

    assert raised.value.item_index == 1
    assert raised.value.item == invalid
    assert raised.value.captured_head == FileLedger(target.log).head()
    assert target.log.path.read_bytes() == before


def test_each_item_resolves_its_own_snapshot_derived_observer_grant(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        observers=(
            "observers {\n"
            '  alice { grant { potential "note" } }\n'
            '  bob { grant { potential "other" } }\n'
            "}\n"
        ),
    )
    before = target.log.path.read_bytes()

    with pytest.raises(BatchWritePreparationRefused) as raised:
        _prepare(
            target,
            _fact("allowed", 3.0, observer="alice"),
            _fact("denied", 4.0, observer="bob"),
        )

    assert raised.value.item_index == 1
    assert raised.value.item.fact.observer == "bob"
    assert target.log.path.read_bytes() == before


def test_existing_and_within_batch_equal_duplicates_are_explicit_noops(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    first = _prepare(target, _fact("existing", 3.0, value="same"))
    execute_batch_write(
        target.registry,
        target.descriptor,
        first,
        after_commit=_sync_after(target),
    )
    before = FileLedger(target.log).head()

    plan = _prepare(
        target,
        _fact("existing", 3.0, value="same"),
        _fact("new", 4.0, value="new"),
        _fact("new", 4.0, value="new"),
    )

    assert [item.already_present for item in plan.items] == [True, False, True]
    assert [draft.kind for draft in plan.drafts] == ["fact"]
    outcome = execute_batch_write(target.registry, target.descriptor, plan)
    assert outcome.commit is not None
    assert outcome.commit.before == before
    assert outcome.commit.after.ordinal == before.ordinal + 1


@pytest.mark.parametrize("collision", ["existing", "pending"])
def test_differing_duplicate_refuses_before_any_batch_append(
    tmp_path, monkeypatch, keys, signer, collision
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    if collision == "existing":
        initial = _prepare(target, _fact("same-id", 3.0, value="first"))
        execute_batch_write(
            target.registry,
            target.descriptor,
            initial,
            after_commit=_sync_after(target),
        )
        items = (_fact("same-id", 3.0, value="different"),)
    else:
        items = (
            _fact("same-id", 3.0, value="first"),
            _fact("same-id", 3.0, value="different"),
        )
    before = target.log.path.read_bytes()

    with pytest.raises(BatchWritePreparationRefused) as raised:
        _prepare(target, *items)

    assert "different content" in str(raised.value.cause)
    assert raised.value.item_index == (0 if collision == "existing" else 1)
    assert raised.value.admission_refused is False
    assert target.log.path.read_bytes() == before


def _tick_row(tick) -> tuple:
    return (
        tick.id,
        tick.name,
        tick.ts,
        tick.since,
        tick.origin,
        tick.payload_text,
        tick.prev_hash,
        tick.window_start,
        tick.fact_cursor,
        tick.window_hash,
        tick.signature,
    )


def test_multiple_batch_boundaries_preserve_exact_chain_windows_and_periods(
    tmp_path, monkeypatch, keys, signer
):
    from sign import ed25519

    target = _make_target(tmp_path, monkeypatch, keys, signer, boundary="boundary every=1")
    credentials = WriteCredentials(
        fact_signer=signer,
        arrival_signer=signer,
        tick_signer=lambda digest: signer("kyle", digest),
    )
    plan = _prepare(
        target,
        _fact("one", 3.0),
        _fact("two", 4.0),
        _fact("three", 5.0),
        credentials=credentials,
    )
    assert [draft.kind for draft in plan.drafts] == [
        "fact",
        "tick",
        "fact",
        "tick",
        "fact",
        "tick",
    ]
    outcome = execute_batch_write(
        target.registry,
        target.descriptor,
        plan,
        after_commit=_sync_after(target),
    )
    assert outcome.commit is not None and len(outcome.commit.records) == 6

    snapshot = FileQuery(index_path_for(target.log.path)).open_snapshot(
        captured_head=outcome.commit.after,
        requirement=ProjectionRequirement.CURRENT,
    )
    try:
        facts = {
            fact.id: fact
            for fact in snapshot.facts(
                FactRequest(limit=None, include_internal=True, order="oldest")
            ).items
        }
        ticks = snapshot.ticks(TickRequest())
    finally:
        snapshot.close()
    assert [tick.since for tick in ticks] == [3.0, 4.0, 5.0]
    assert [tick.ts for tick in ticks] == [3.0, 4.0, 5.0]
    assert [tick.fact_cursor for tick in ticks] == ["one", "two", "three"]
    assert [tick.window_start for tick in ticks] == ["", "one", "two"]
    assert ticks[0].prev_hash is None
    assert ticks[1].prev_hash == tick_row_hash(_tick_row(ticks[0]))
    assert ticks[2].prev_hash == tick_row_hash(_tick_row(ticks[1]))
    first_window = hashlib.sha256()
    for identifier in (target.log.lineage(), "one"):
        fact = facts[identifier]
        first_window.update(
            fact_row_hash(
                (
                    fact.id,
                    fact.kind,
                    fact.ts,
                    fact.observer,
                    fact.origin,
                    fact.payload_text,
                    fact.signature,
                )
            ).encode()
        )
    assert ticks[0].window_hash == first_window.hexdigest()
    for tick, identifier in zip(ticks[1:], ("two", "three"), strict=True):
        fact = facts[identifier]
        expected = hashlib.sha256(
            fact_row_hash(
                (
                    fact.id,
                    fact.kind,
                    fact.ts,
                    fact.observer,
                    fact.origin,
                    fact.payload_text,
                    fact.signature,
                )
            ).encode()
        ).hexdigest()
        assert tick.window_hash == expected
    for tick in ticks:
        assert tick.signature is not None
        assert ed25519.verify(
            ed25519.public_key_from_b64(keys.public),
            tick.signature,
            tick_commitment_hash(_tick_row(tick)).encode(),
            domain="test-arrival-v1",
        )


def test_real_every_two_boundary_packs_pending_facts_and_hashes_both(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer, boundary="boundary every=2")
    plan = _prepare(
        target,
        _fact("one", 3.0),
        _fact("two", 4.0),
        _fact("three", 5.0),
    )

    assert [draft.kind for draft in plan.drafts] == ["batch", "tick", "fact"]
    assert [row["id"] for row in plan.drafts[0].body["rows"]] == ["one", "two"]
    tick_draft = plan.drafts[1]
    assert tick_draft.body["fact_cursor"] == "two"
    assert tick_draft.body["window_start"] == ""
    outcome = execute_batch_write(
        target.registry,
        target.descriptor,
        plan,
        after_commit=_sync_after(target),
    )
    assert outcome.commit is not None and len(outcome.commit.records) == 3

    snapshot = FileQuery(index_path_for(target.log.path)).open_snapshot(
        captured_head=outcome.commit.after,
        requirement=ProjectionRequirement.CURRENT,
    )
    try:
        facts = snapshot.facts(FactRequest(limit=None, include_internal=True, order="oldest")).items
        ticks = snapshot.ticks(TickRequest())
    finally:
        snapshot.close()
    assert len(ticks) == 1
    assert ticks[0].since == 3.0
    assert ticks[0].ts == 4.0
    assert ticks[0].fact_cursor == "two"
    expected = hashlib.sha256()
    for fact in facts:
        if fact.id == "three":
            continue
        expected.update(
            fact_row_hash(
                (
                    fact.id,
                    fact.kind,
                    fact.ts,
                    fact.observer,
                    fact.origin,
                    fact.payload_text,
                    fact.signature,
                )
            ).encode()
        )
    assert ticks[0].window_hash == expected.hexdigest()


def test_atomic_limit_counts_packed_records_and_refuses_before_append(
    tmp_path, monkeypatch, keys, signer
):
    fitting = _make_target(
        tmp_path / "fit",
        monkeypatch,
        keys,
        signer,
        max_atomic_records=1,
    )
    plan = _prepare(fitting, _fact("one", 3.0), _fact("two", 4.0))
    assert [draft.kind for draft in plan.drafts] == ["batch"]
    execute_batch_write(fitting.registry, fitting.descriptor, plan)

    refusing = _make_target(
        tmp_path / "refuse",
        monkeypatch,
        keys,
        signer,
        max_atomic_records=1,
    )
    before = refusing.log.path.read_bytes()
    with pytest.raises(AtomicLimitExceeded, match="2 packed records"):
        _prepare(
            refusing,
            _fact("alice", 3.0, observer="alice"),
            _fact("bob", 4.0, observer="bob"),
        )
    assert refusing.log.path.read_bytes() == before


def test_atomic_limit_is_rechecked_by_append_if_capacity_changes_after_plan(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    plan = _prepare(
        target,
        _fact("alice", 3.0, observer="alice"),
        _fact("bob", 4.0, observer="bob"),
    )
    assert len(plan.drafts) == 2
    before = target.log.path.read_bytes()

    with pytest.raises(AtomicLimitExceeded, match="configured atomic limit"):
        execute_batch_write(_registry_with_limit(target, 1), target.descriptor, plan)

    assert target.log.path.read_bytes() == before


def test_stale_batch_plan_refuses_before_append(tmp_path, monkeypatch, keys, signer):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    plan = _prepare(target, _fact("planned", 3.0))
    target.log.append(
        "fact",
        body_of_fact_row(("interloper", "note", 3.5, "kyle", "test", "{}", None)),
        observer="kyle",
        origin="test",
        at=3.5,
        signer=signer,
    )
    after_interloper = target.log.path.read_bytes()

    with pytest.raises(RuntimeWriteRefused, match="captured head changed"):
        execute_batch_write(target.registry, target.descriptor, plan)

    assert target.log.path.read_bytes() == after_interloper


def test_batch_execute_preserves_indeterminate_attestation_refusal(monkeypatch):
    head = Head("lineage", 2, "hash")
    refusal = IndeterminateComparison("journal evidence is incomplete")

    class IndeterminateLedger:
        def __init__(self):
            self.opened = type(
                "Opened",
                (),
                {
                    "comparison": Indeterminate(
                        presented=head,
                        refusal=refusal,
                        skipped=("bad",),
                        at_least=None,
                    )
                },
            )()

        def close(self):
            return None

    class Registry:
        def open(self, _descriptor):
            return IndeterminateLedger(), type("Query", (), {"close": lambda self: None})()

    monkeypatch.setattr("engine.runtime_write.AttestedLedger", IndeterminateLedger)
    plan = BatchWritePlan(
        captured_head=head,
        items=(BatchItemResult("planned", None, None, False),),
        drafts=(
            RecordDraft(
                "fact",
                3.0,
                "kyle",
                body={
                    "id": "planned",
                    "kind": "note",
                    "ts": 3.0,
                    "observer": "kyle",
                    "origin": "",
                    "payload": "{}",
                },
            ),
        ),
    )

    with pytest.raises(IndeterminateComparison) as raised:
        execute_batch_write(
            Registry(),
            StoreDescriptor("file", "ignored", role=Profile.AUTHORITY),
            plan,
        )
    assert raised.value is refusal


def test_batch_prepare_refuses_behind_projection_without_repair(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    index = index_path_for(target.log.path)
    projected_before = index.read_bytes()
    target.log.append(
        "fact",
        body_of_fact_row(("unprojected", "note", 3.0, "kyle", "test", "{}", None)),
        observer="kyle",
        origin="test",
        at=3.0,
        signer=signer,
    )

    with pytest.raises(ProjectionBehind):
        _prepare(target, _fact("planned", 4.0))

    assert index.read_bytes() == projected_before


def test_append_level_head_mismatch_does_not_land_any_planned_record(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    plan = _prepare(target, _fact("planned-one", 3.0), _fact("planned-two", 4.0))
    before = FileLedger(target.log).head()
    original_append = FileLedger.append
    raced = False

    def append_after_interloper(self, expected, drafts):
        nonlocal raced
        if not raced:
            raced = True
            target.log.append(
                "fact",
                body_of_fact_row(("interloper", "note", 3.5, "kyle", "test", "{}", None)),
                observer="kyle",
                origin="test",
                at=3.5,
                signer=signer,
            )
        return original_append(self, expected, drafts)

    monkeypatch.setattr(FileLedger, "append", append_after_interloper)
    with pytest.raises(HeadMismatch):
        execute_batch_write(target.registry, target.descriptor, plan)

    records = list(target.log.walk())
    assert FileLedger(target.log).head().ordinal == before.ordinal + 1
    assert records[-1]["body"]["id"] == "interloper"
    encoded = json.dumps(records)
    assert "planned-one" not in encoded
    assert "planned-two" not in encoded


def test_batch_durable_then_raise_is_typed_unknown_and_attempted_once(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    plan = _prepare(target, _fact("one", 3.0), _fact("two", 4.0))
    before = FileLedger(target.log).head()
    original = AttestedLedger.append
    calls = 0

    def append_then_raise(self, expected, drafts):
        nonlocal calls
        calls += 1
        original(self, expected, drafts)
        raise OSError("adapter lost its completion response")

    monkeypatch.setattr(AttestedLedger, "append", append_then_raise)
    with pytest.raises(BatchWriteCommitUnknown) as raised:
        execute_batch_write(target.registry, target.descriptor, plan)

    unknown = raised.value
    assert calls == 1
    assert unknown.captured_head == before
    assert unknown.fact_ids == ("one", "two")
    assert unknown.tick_ids == ()
    assert unknown.items == plan.items
    assert unknown.drafts == plan.drafts
    assert isinstance(unknown.cause, OSError)
    assert FileLedger(target.log).head().ordinal == before.ordinal + 1


def test_batch_postcommit_projection_failure_retains_commit_and_all_ids(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer, boundary="boundary every=1")
    plan = _prepare(target, _fact("one", 3.0), _fact("two", 4.0))

    def fail_projection(_head):
        raise RuntimeError("projection unavailable")

    with pytest.raises(BatchPostCommitProjectionFailed) as raised:
        execute_batch_write(
            target.registry,
            target.descriptor,
            plan,
            after_commit=fail_projection,
        )

    failure = raised.value
    assert failure.commit.after == FileLedger(target.log).head()
    assert failure.fact_ids == ("one", "two")
    assert failure.tick_ids == tuple(
        item.tick_id for item in plan.items if item.tick_id is not None
    )
    assert failure.items == plan.items
    assert failure.projection is ProjectionOutcome.FAILED
    assert isinstance(failure.cause, RuntimeError)
