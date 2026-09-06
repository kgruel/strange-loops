"""Tier-atomic Arrival source execution over immutable runtime captures."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace

import pytest
from atoms import Fact, SourceError
from lang import genesis_payload

from engine.arrival_contract import FactRequest, ProjectionRequirement
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_head_seam import AttestedLedger, NotWitnessed
from engine.arrival_sources import (
    DeclarationChangedDuringInvocation,
    DispatchFailed,
    InvalidSourceOutput,
    SourcePreparationRefused,
    SourceTierPreparationRefused,
    collect_source_tier,
    execute_source_invocation,
    prepare_collected_tier,
    prepare_source_invocation,
)
from engine.handle import WriteCredentials
from engine.residence import index_path_for
from engine.runtime_write import (
    BatchPostCommitProjectionFailed,
    BatchWriteCommitUnknown,
    ProjectionOutcome,
    RuntimeWriteRefused,
    capture_runtime,
    execute_batch_write,
    plan_batch_from_capture,
)
from tests.test_runtime_batch_write import _make_target
from tests.test_runtime_capture import _append_fact, _sync


def _source_target(
    tmp_path,
    monkeypatch,
    keys,
    signer,
    definitions,
    *,
    boundary_by_kind=None,
    note_boundary="",
    max_atomic_records=None,
):
    paths = []
    boundary_by_kind = boundary_by_kind or {}
    for kind, cadence in definitions:
        path = tmp_path / f"{kind}.loop"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'kind "{kind}"\n'
            'observer "kyle"\n'
            f'source "collect-{kind}"\n'
            f"{cadence}",
            encoding="utf-8",
        )
        paths.append(path)
    source_text = "sources {\n" + "".join(
        f'  path "./{path.name}"\n' for path in paths
    ) + "}\n"
    extra_loops = "".join(
        "  " + kind + " {\n"
        '    fold { items "collect" 20 }\n'
        + (f"    {boundary_by_kind[kind]}\n" if kind in boundary_by_kind else "")
        + "  }\n"
        for kind, _cadence in definitions
        if kind != "note"
    )
    return _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary=note_boundary,
        source_text=source_text,
        extra_loops=extra_loops,
        max_atomic_records=max_atomic_records,
    )


def _credentials() -> WriteCredentials:
    return WriteCredentials()


def _facts_at(target, head):
    snapshot = FileQuery(index_path_for(target.log.path)).open_snapshot(
        captured_head=head,
        requirement=ProjectionRequirement.CURRENT,
    )
    try:
        return snapshot.facts(
            FactRequest(limit=None, include_internal=True, order="oldest")
        ).items
    finally:
        snapshot.close()


def test_prepare_freezes_event_time_cadence_and_dependency_tiers(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", 'every "60s"\n'), ("b", 'on "trigger"\n')),
    )
    _append_fact(target, "a-ok", "_sync.a", 10.0, signer, {"status": "ok"})
    _append_fact(target, "a-error", "_sync.a", 19.0, signer, {"status": "error"})
    _append_fact(target, "trigger", "trigger", 15.0, signer)
    _sync(target)

    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=20.0,
    )

    a, b = plan.cadence
    assert (a.latest_success_id, a.latest_success_ts, a.qualified) == (
        "a-ok",
        10.0,
        False,
    )
    assert b.trigger_fact_ids == ("trigger",)
    assert b.qualified is True
    assert plan.qualifying_indices == (1,)
    assert plan.tiers == ((1,),)


def test_prepare_refuses_unknown_lifecycle_observer_before_collection(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
    with pytest.raises(SourcePreparationRefused):
        prepare_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            observer="mallory",
            credentials=_credentials(),
            evaluated_at=10.0,
        )


def test_independent_collectors_run_concurrently_but_commit_in_source_order(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", ""), ("b", "")),
    )
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="alice",
        credentials=_credentials(),
        force=True,
        evaluated_at=10.0,
    )
    started = []
    released = asyncio.Event()

    def factory(source):
        async def collect():
            started.append(source.kind)
            if len(started) == 2:
                released.set()
            await asyncio.wait_for(released.wait(), timeout=1)
            if source.kind == "a":
                await asyncio.sleep(0.01)
            yield Fact(source.kind, 11.0, {"source": source.kind}, observer="kyle")

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
        )
    )

    assert result.status == "ok"
    assert Counter(started) == Counter(("a", "b"))
    assert [source.kind for source in result.collected_tiers[0].sources] == ["a", "b"]
    assert len(result.durable_tiers) == 1
    commit = result.durable_tiers[0].commit
    assert len(commit.records) == 4  # final lifecycle and overall sync pack together
    facts = _facts_at(target, commit.after)
    written = [fact for fact in facts if fact.ts >= 11.0]
    assert [fact.kind for fact in written] == ["a", "_sync.a", "b", "_sync.b", "_sync"]
    assert [fact.observer for fact in written if fact.kind.startswith("_sync")] == [
        "alice",
        "alice",
        "alice",
    ]


def test_source_error_keeps_yielded_output_and_durable_error_lifecycle(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )

    def factory(source):
        async def collect():
            yield Fact("a", 11.0, {"kept": True}, observer="kyle")
            raise SourceError(source.command, returncode=7, stderr="broken")

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
        )
    )
    source = result.collected_tiers[0].sources[0]
    assert result.status == "error" and result.terminal is None
    assert source.status == "error" and source.stderr == "broken"
    assert result.error_lifecycle_ids == result.durable_error_lifecycle_ids == (
        source.lifecycle_id,
    )
    written = _facts_at(target, result.durable_tiers[0].commit.after)
    assert any(fact.kind == "a" and fact.payload.get("kept") is True for fact in written)
    assert any(
        fact.kind == "_sync.a" and fact.payload.get("returncode") == 7
        for fact in written
    )


def test_invalid_later_output_refuses_whole_tier_with_zero_append(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", ""), ("b", "")),
    )
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        force=True,
        evaluated_at=10.0,
    )
    before = FileLedger(target.log).head()
    attempts = Counter()
    closed = Counter()

    def factory(source):
        async def collect():
            try:
                attempts[source.kind] += 1
                yield Fact(source.kind, 11.0, {}, observer="kyle")
                if source.kind == "b":
                    yield {"not": "a Fact"}
            finally:
                closed[source.kind] += 1

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
        )
    )
    assert result.status == "incomplete"
    assert isinstance(result.terminal, SourceTierPreparationRefused)
    assert isinstance(result.terminal.cause, InvalidSourceOutput)
    assert result.collected_uncommitted is result.terminal_tier
    assert result.durable_tiers == ()
    assert FileLedger(target.log).head() == before
    assert attempts == Counter(a=1, b=1)
    assert closed == Counter(a=1, b=1)


def test_unadmitted_collected_fact_refuses_whole_tier_with_zero_append(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )
    before = FileLedger(target.log).head()

    def factory(source):
        async def collect():
            yield Fact("undeclared", 11.0, {}, observer="kyle")

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
        )
    )
    assert isinstance(result.terminal, SourceTierPreparationRefused)
    assert result.collected_uncommitted is result.terminal_tier
    assert FileLedger(target.log).head() == before


def test_collected_tier_must_match_the_capture_basis(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )

    def factory(source):
        async def collect():
            yield Fact("a", 11.0, {}, observer="kyle")

        return collect()

    collected = asyncio.run(
        collect_source_tier(
            plan,
            plan.initial_capture,
            0,
            factory,
            clock=lambda: 12.0,
        )
    )
    collected = replace(
        collected,
        basis=replace(collected.basis, view_generation="different-view"),
    )
    with pytest.raises(SourceTierPreparationRefused) as caught:
        prepare_collected_tier(
            plan.initial_capture,
            collected,
            credentials=_credentials(),
        )
    assert isinstance(caught.value.cause, ValueError)


def test_force_dependency_tiers_commit_once_each_and_overall_only_last(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", ""), ("b", 'on "_sync.a"\n')),
    )
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        force=True,
        evaluated_at=10.0,
    )
    order = []
    original_capture = __import__(
        "engine.arrival_sources", fromlist=["capture_runtime"]
    ).capture_runtime
    later_locator_paths = []

    def inspect_capture(registry, descriptor, locator, **kwargs):
        later_locator_paths.append(locator.path)
        return original_capture(registry, descriptor, locator, **kwargs)

    original_locator_path = target.locator.path
    object.__setattr__(target.locator, "path", tmp_path / "mutated.vertex")
    monkeypatch.setattr("engine.arrival_sources.capture_runtime", inspect_capture)

    def factory(source):
        async def collect():
            order.append(source.kind)
            yield Fact(source.kind, 11.0 + len(order), {}, observer="kyle")

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 14.0,
        )
    )
    assert plan.tiers == ((0,), (1,))
    assert order == ["a", "b"]
    assert later_locator_paths == [original_locator_path]
    assert len(result.durable_tiers) == 2
    first_facts = _facts_at(target, result.durable_tiers[0].commit.after)
    assert not any(fact.kind == "_sync" for fact in first_facts)
    final_facts = _facts_at(target, result.durable_tiers[1].commit.after)
    assert sum(fact.kind == "_sync" for fact in final_facts) == 1
    assert result.bases[1].captured_head == result.durable_tiers[0].commit.after


def test_declaration_change_between_tiers_stops_before_next_collector(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", ""), ("b", 'on "_sync.a"\n')),
    )
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        force=True,
        evaluated_at=10.0,
    )
    original_capture = __import__(
        "engine.arrival_sources", fromlist=["capture_runtime"]
    ).capture_runtime
    changed = False

    def changed_capture(*args, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            document = genesis_payload(target.locator)["documents"][0]
            payload = dict(document["payload"])
            payload["name"] = "changed-between-tiers"
            _append_fact(
                target,
                "decl-between",
                document["kind"],
                20.0,
                signer,
                {
                    "lineage": target.log.lineage(),
                    "subject": document["subject"],
                    "payload": payload,
                },
            )
            _sync(target)
        return original_capture(*args, **kwargs)

    monkeypatch.setattr("engine.arrival_sources.capture_runtime", changed_capture)
    attempts = Counter()

    def factory(source):
        async def collect():
            attempts[source.kind] += 1
            yield Fact(source.kind, 11.0, {}, observer="kyle")

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
        )
    )
    assert isinstance(result.terminal, DeclarationChangedDuringInvocation)
    assert len(result.durable_tiers) == 1
    assert attempts == Counter(a=1)


def test_no_qualified_sources_records_only_overall_lifecycle(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", 'every "60s"\n'),),
    )
    _append_fact(target, "recent", "_sync.a", 9.0, signer, {"status": "ok"})
    _sync(target)
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )
    called = False

    def factory(source):
        nonlocal called
        called = True
        return source.collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 11.0,
        )
    )
    assert called is False
    assert result.status == "ok" and len(result.durable_tiers) == 1
    facts = _facts_at(target, result.durable_tiers[0].commit.after)
    assert facts[-1].kind == "_sync" and facts[-1].id == plan.overall_sync_id


def test_no_qualified_sources_commit_pending_boundary_then_overall(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", 'every "1h"\n'),),
        note_boundary='boundary when="seal" { run "pending-no-callback" }',
    )
    _append_fact(target, "prior-sync", "_sync.a", 9.0, signer, {"status": "ok"})
    _append_fact(target, "note", "note", 9.1, signer, {"value": "pending"})
    _append_fact(target, "seal", "seal", 9.2, signer)
    _sync(target)
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )
    assert plan.qualifying_indices == ()
    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=lambda source: pytest.fail("collector ran"),
            clock=lambda: 11.0,
        )
    )
    assert result.status == "ok"
    committed = result.durable_tiers[0]
    assert [record["k"] for record in committed.commit.records] == ["tick", "fact"]
    assert committed.plan.pending_tick_names == ("note",)
    assert committed.dispatch_succeeded is None
    assert [intent.command for intent in committed.dispatch_intents] == [
        "pending-no-callback"
    ]


def test_pending_signed_era_is_preflighted_before_collectors(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", ""),),
        note_boundary='boundary when="seal"',
    )
    _append_fact(target, "note-one", "note", 3.0, signer, {"value": "one"})
    _append_fact(target, "seal-one", "seal", 4.0, signer)
    _sync(target)
    first_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    first = plan_batch_from_capture(
        first_capture,
        (),
        credentials=WriteCredentials(
            tick_signer=lambda digest: signer("kyle", digest)
        ),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, first)
    _sync(target)
    _append_fact(target, "note-two", "note", 6.0, signer, {"value": "two"})
    _append_fact(target, "seal-two", "seal", 7.0, signer)
    _sync(target)

    with pytest.raises(SourcePreparationRefused, match="before collection") as caught:
        prepare_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            observer="kyle",
            credentials=_credentials(),
            evaluated_at=8.0,
        )
    assert isinstance(caught.value.cause, RuntimeWriteRefused)
    assert "unsigned tick in the signed tick era" in str(caught.value.cause)


def test_stale_after_collection_retains_uncommitted_tier_without_rerun(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )
    attempts = 0

    def factory(source):
        async def collect():
            nonlocal attempts
            attempts += 1
            _append_fact(target, "interloper", "note", 11.0, signer)
            yield Fact("a", 12.0, {}, observer="kyle")

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 13.0,
        )
    )
    assert attempts == 1
    assert isinstance(result.terminal, RuntimeWriteRefused)
    assert result.collected_uncommitted is result.terminal_tier
    assert result.durable_tiers == ()


def test_unknown_and_unwitnessed_paths_preserve_distinct_durability(
    tmp_path, monkeypatch, keys, signer
):
    for mode in ("unknown", "unwitnessed"):
        target = _source_target(
            tmp_path / mode,
            monkeypatch,
            keys,
            signer,
            (("a", ""),),
        )
        plan = prepare_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            observer="kyle",
            credentials=_credentials(),
            evaluated_at=10.0,
        )
        original_append = AttestedLedger.append
        attempts = 0

        def append_then_raise(
            self,
            expected,
            drafts,
            *,
            _append=original_append,
            _mode=mode,
        ):
            nonlocal attempts
            attempts += 1
            commit = _append(self, expected, drafts)
            if _mode == "unwitnessed":
                raise NotWitnessed("simulated witness loss", head=commit.after, commit=commit)
            raise OSError("simulated uncertain return")

        with monkeypatch.context() as patch:
            patch.setattr(AttestedLedger, "append", append_then_raise)

            def factory(source):
                async def collect():
                    yield Fact("a", 11.0, {}, observer="kyle")

                return collect()

            result = asyncio.run(
                execute_source_invocation(
                    target.registry,
                    target.descriptor,
                    target.locator,
                    plan,
                    credentials=_credentials(),
                    collector_factory=factory,
                    clock=lambda: 12.0,
                )
            )
        assert attempts == 1
        if mode == "unknown":
            assert isinstance(result.terminal, BatchWriteCommitUnknown)
            assert result.durable_tiers == ()
            assert result.collected_unknown is result.terminal_tier
            assert result.collected_uncommitted is None
        else:
            assert isinstance(result.terminal, NotWitnessed)
            assert len(result.durable_tiers) == 1
            assert result.durable_tiers[0].witnessed is False


def test_dispatch_intents_are_built_before_append(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )
    before = FileLedger(target.log).head()

    def factory(source):
        async def collect():
            yield Fact("a", 11.0, {}, observer="kyle")

        return collect()

    monkeypatch.setattr(
        "engine.arrival_sources._dispatch_intents",
        lambda *args: (_ for _ in ()).throw(ValueError("invalid dispatch evidence")),
    )
    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
        )
    )
    assert isinstance(result.terminal, ValueError)
    assert result.collected_uncommitted is result.terminal_tier
    assert result.durable_tiers == ()
    assert FileLedger(target.log).head() == before


def test_projection_and_dispatch_failures_keep_actual_commit(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path / "projection",
        monkeypatch,
        keys,
        signer,
        (("a", ""),),
    )
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )

    def factory(source):
        async def collect():
            yield Fact("a", 11.0, {}, observer="kyle")

        return collect()

    with monkeypatch.context() as patch:
        patch.setattr(
            "engine.arrival_sources.sync_projection",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("projection down")),
        )
        failed = asyncio.run(
            execute_source_invocation(
                target.registry,
                target.descriptor,
                target.locator,
                plan,
                credentials=_credentials(),
                collector_factory=factory,
                clock=lambda: 12.0,
            )
        )
    assert isinstance(failed.terminal, BatchPostCommitProjectionFailed)
    assert failed.durable_tiers[0].commit is failed.terminal.commit
    assert failed.durable_tiers[0].outcome.projection is ProjectionOutcome.FAILED

    dispatch_target = _source_target(
        tmp_path / "dispatch",
        monkeypatch,
        keys,
        signer,
        (("a", ""),),
        boundary_by_kind={"a": 'boundary every=1 { run "captured-command" }'},
    )
    dispatch_plan = prepare_source_invocation(
        dispatch_target.registry,
        dispatch_target.descriptor,
        dispatch_target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=10.0,
    )
    calls = []

    def dispatcher(commit, intents):
        calls.append((commit, intents))
        raise OSError("dispatch down")

    dispatched = asyncio.run(
        execute_source_invocation(
            dispatch_target.registry,
            dispatch_target.descriptor,
            dispatch_target.locator,
            dispatch_plan,
            credentials=_credentials(),
            collector_factory=factory,
            dispatcher=dispatcher,
            clock=lambda: 12.0,
        )
    )
    assert isinstance(dispatched.terminal, DispatchFailed)
    assert len(calls) == 1 and len(dispatched.durable_tiers) == 1
    intent = calls[0][1][0]
    assert intent.command == "captured-command"
    assert intent.payload["items"][0]["_ts"] == 11.0
    assert dispatched.durable_tiers[0].dispatch_succeeded is False


def test_pending_boundary_is_first_record_of_first_source_commit(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", ""),),
        note_boundary='boundary when="seal" { run "pending-command" }',
    )
    _append_fact(target, "old-note", "note", 3.0, signer, {"value": "old"})
    _append_fact(target, "seal", "seal", 4.0, signer)
    _sync(target)
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        evaluated_at=5.0,
    )

    def factory(source):
        async def collect():
            if False:
                yield Fact("a", 6.0, {}, observer="kyle")

        return collect()

    calls = []
    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            dispatcher=lambda commit, intents: calls.append((commit, intents)),
            clock=lambda: 6.0,
        )
    )
    tier = result.durable_tiers[0]
    assert tier.commit.records[0]["k"] == "tick"
    assert tier.plan.pending_tick_ids == (tier.commit.records[0]["body"]["id"],)
    assert calls[0][1][0].command == "pending-command"
    assert tier.dispatch_intents == calls[0][1]


def test_packed_atomic_cap_is_checked_after_collection_before_append(
    tmp_path, monkeypatch, keys, signer
):
    target = _source_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        (("a", ""),),
        max_atomic_records=1,
    )
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="alice",
        credentials=_credentials(),
        evaluated_at=10.0,
    )
    before = FileLedger(target.log).head()

    def factory(source):
        async def collect():
            yield Fact("a", 11.0, {}, observer="kyle")

        return collect()

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
        )
    )
    assert isinstance(result.terminal, SourceTierPreparationRefused)
    assert result.durable_tiers == ()
    assert FileLedger(target.log).head() == before
