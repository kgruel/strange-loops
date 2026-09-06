"""C8b collector ownership and coordinator bookkeeping contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from atoms import Fact

from engine.arrival_sources import SourceTierCollectionFailed, collect_source_tier


class _Stream:
    def __init__(self, *steps: object, close_error: BaseException | None = None):
        self._steps = list(steps)
        self.closed = 0
        self.close_error = close_error

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._steps:
            raise StopAsyncIteration
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    async def aclose(self):
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error


class _DistinctStream:
    def __init__(self, value: Fact, *, iterator_close_error: BaseException | None = None):
        self.value = value
        self.stream_closed = 0
        self.iterator_closed = 0
        self.iterator_close_error = iterator_close_error

    def __aiter__(self):
        return _DistinctIterator(self)

    async def aclose(self):
        self.stream_closed += 1


class _DistinctIterator:
    def __init__(self, owner: _DistinctStream):
        self.owner = owner
        self.done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.done:
            raise StopAsyncIteration
        self.done = True
        return self.owner.value

    async def aclose(self):
        self.owner.iterator_closed += 1
        if self.owner.iterator_close_error is not None:
            raise self.owner.iterator_close_error


def _collect(stream: _Stream, *, id_factory=lambda: "fact-id"):
    invocation = SimpleNamespace(
        invocation_id="invocation-id",
        observer="runner",
        lifecycle_ids=("life-id",),
        tiers=((0,),),
    )
    source = SimpleNamespace(kind="note", command="collect-note", observer="alice")
    capture = SimpleNamespace(
        basis="basis",
        initial_capture=SimpleNamespace(sources=((source, None),)),
    )
    invocation.initial_capture = capture.initial_capture
    return asyncio.run(
        collect_source_tier(
            invocation,
            capture,
            0,
            lambda _source: stream,
            clock=lambda: 2.0,
            id_factory=id_factory,
        )
    ).sources[0]


def test_owned_stream_is_closed_after_normal_exhaustion():
    stream = _Stream(Fact("note", 1.0, {"n": 1}, observer="alice"))

    result = _collect(stream)

    assert stream.closed == 1
    assert result.status == "ok"
    assert len(result.facts) == len(result.fact_ids) == 1


def test_distinct_stream_owner_and_iterator_are_both_closed():
    stream = _DistinctStream(Fact("note", 1.0, {"n": 1}, observer="alice"))

    result = _collect(stream)  # type: ignore[arg-type]

    assert result.status == "ok"
    assert stream.iterator_closed == 1
    assert stream.stream_closed == 1


def test_owned_stream_is_closed_after_collector_error_and_output_is_retained():
    stream = _Stream(
        Fact("note", 1.0, {"n": 1}, observer="alice"),
        RuntimeError("collector failed"),
    )

    result = _collect(stream)

    assert stream.closed == 1
    assert result.status == "error"
    assert result.error_type == "RuntimeError"
    assert result.error_message == "collector failed"
    assert len(result.facts) == len(result.fact_ids) == 1


def test_owned_stream_is_closed_on_cancellation_and_cancellation_is_preserved():
    stream = _Stream(asyncio.CancelledError())
    invocation = SimpleNamespace(
        invocation_id="invocation-id",
        observer="runner",
        lifecycle_ids=("life-id",),
        tiers=((0,),),
    )
    source = SimpleNamespace(kind="note", command="collect-note", observer="alice")
    capture = SimpleNamespace(
        basis="basis",
        initial_capture=SimpleNamespace(sources=((source, None),)),
    )
    invocation.initial_capture = capture.initial_capture

    with pytest.raises(asyncio.CancelledError) as raised:
        asyncio.run(
            collect_source_tier(
                invocation,
                capture,
                0,
                lambda _source: stream,
                clock=lambda: 2.0,
                id_factory=lambda: "fact-id",
            )
        )

    assert raised.value.__cause__ is None
    assert stream.closed == 1


def test_cleanup_failure_does_not_replace_collector_primary_error():
    stream = _Stream(
        RuntimeError("collector primary"),
        close_error=OSError("cleanup secondary"),
    )

    result = _collect(stream)

    assert stream.closed == 1
    assert result.status == "error"
    assert result.error_type == "RuntimeError"
    assert result.error_message == "collector primary"


def test_normal_close_failure_is_terminal_cleanup_with_paired_output():
    stream = _Stream(
        Fact("note", 1.0, {"n": 1}, observer="alice"),
        close_error=OSError("cleanup failed"),
    )

    invocation = SimpleNamespace(
        invocation_id="invocation-id",
        observer="runner",
        lifecycle_ids=("life-id",),
        tiers=((0,),),
    )
    source = SimpleNamespace(kind="note", command="collect-note", observer="alice")
    capture = SimpleNamespace(
        basis="basis",
        initial_capture=SimpleNamespace(sources=((source, None),)),
    )
    invocation.initial_capture = capture.initial_capture

    with pytest.raises(SourceTierCollectionFailed) as raised:
        asyncio.run(
            collect_source_tier(
                invocation,
                capture,
                0,
                lambda _source: stream,
                clock=lambda: 2.0,
                id_factory=lambda: "fact-id",
            )
        )

    failure = raised.value
    assert stream.closed == 1
    assert failure.failed_sources[0].phase == "cleanup"
    assert failure.failed_sources[0].pairs == (
        (failure.failed_sources[0].facts[0], "fact-id"),
    )


def test_iterator_cleanup_cancellation_does_not_replace_primary_control_flow():
    primary = asyncio.CancelledError("collector cancellation")
    invocation = SimpleNamespace(
        invocation_id="invocation-id",
        observer="runner",
        lifecycle_ids=("life-id",),
        tiers=((0,),),
    )
    source = SimpleNamespace(kind="note", command="collect-note", observer="alice")
    capture = SimpleNamespace(
        basis="basis",
        initial_capture=SimpleNamespace(sources=((source, None),)),
    )
    invocation.initial_capture = capture.initial_capture

    class _CancellingStream(_DistinctStream):
        def __aiter__(self):
            owner = self

            class Iterator(_DistinctIterator):
                async def __anext__(self):
                    if self.done:
                        raise StopAsyncIteration
                    self.done = True
                    raise primary

            return Iterator(owner)

    stream = _CancellingStream(
        Fact("note", 1.0, {"n": 1}, observer="alice"),
        iterator_close_error=asyncio.CancelledError("cleanup cancellation"),
    )
    with pytest.raises(asyncio.CancelledError) as raised:
        asyncio.run(
            collect_source_tier(
                invocation,
                capture,
                0,
                lambda _source: stream,
                clock=lambda: 2.0,
                id_factory=lambda: "fact-id",
            )
        )

    assert raised.value is primary
    assert stream.iterator_closed == 1
    assert stream.stream_closed == 1


def test_id_factory_failure_is_coordinator_terminal_without_lifecycle_append(
    tmp_path, monkeypatch, keys, signer
):
    from engine.arrival_file_backend import FileLedger
    from engine.arrival_sources import execute_source_invocation, prepare_source_invocation
    from tests.test_arrival_sources import _credentials, _source_target

    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
    plan = prepare_source_invocation(
        target.registry,
        target.descriptor,
        target.locator,
        observer="kyle",
        credentials=_credentials(),
        force=True,
        evaluated_at=10.0,
    )
    calls = 0

    def fail_id_factory():
        nonlocal calls
        calls += 1
        raise OSError("id allocation unavailable")

    def factory(_source):
        async def collect():
            yield Fact("a", 11.0, {"value": 1}, observer="kyle")

        return collect()

    before = FileLedger(target.log).head()
    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
            id_factory=fail_id_factory,
        )
    )

    assert calls == 1
    assert isinstance(result.terminal, SourceTierCollectionFailed)
    failure = result.terminal
    assert failure.completed_sources == ()
    assert failure.cancelled_sources == ()
    assert len(failure.failed_sources) == 1
    partial = failure.failed_sources[0]
    assert partial.phase == "bookkeeping"
    assert partial.error_type == "OSError"
    assert partial.error_message == "id allocation unavailable"
    assert partial.pairs == ()
    assert result.durable_tiers == ()
    assert FileLedger(target.log).head() == before


def test_collection_failure_preserves_prior_durable_tiers(
    tmp_path, monkeypatch, keys, signer
):
    from engine.arrival_file_backend import FileLedger
    from engine.arrival_sources import execute_source_invocation, prepare_source_invocation
    from tests.test_arrival_sources import _credentials, _facts_at, _source_target

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
    calls = 0

    def id_factory():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second-tier ID allocation unavailable")
        return f"fact-id-{calls}"

    def factory(source):
        return _Stream(Fact(source.kind, 11.0, {"source": source.kind}, observer="kyle"))

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=lambda: 12.0,
            id_factory=id_factory,
        )
    )

    assert plan.tiers == ((0,), (1,))
    assert len(result.durable_tiers) == 1
    assert result.durable_tiers[0].tier_index == 0
    assert isinstance(result.terminal, SourceTierCollectionFailed)
    assert result.terminal.tier_index == 1
    assert result.terminal.failed_sources[0].phase == "bookkeeping"
    assert result.terminal.failed_sources[0].pairs == ()
    assert result.collected_tiers == (result.durable_tiers[0].collected,)
    persisted = _facts_at(target, result.durable_tiers[0].commit.after)
    assert any(fact.kind == "a" for fact in persisted)
    assert FileLedger(target.log).head() == result.durable_tiers[0].commit.after


def test_collection_failure_retains_cancelled_sibling_partial_pairs():
    invocation = SimpleNamespace(
        invocation_id="invocation-id",
        observer="runner",
        lifecycle_ids=("life-a", "life-b"),
        tiers=((0, 1),),
    )
    source_a = SimpleNamespace(kind="a", command="collect-a", observer="alice")
    source_b = SimpleNamespace(kind="b", command="collect-b", observer="alice")
    capture = SimpleNamespace(
        basis="basis",
        initial_capture=SimpleNamespace(
            sources=((source_a, None), (source_b, None))
        ),
    )
    invocation.initial_capture = capture.initial_capture
    release = asyncio.Event()
    streams = {}

    class BlockingStream(_Stream):
        async def __anext__(self):
            if not self._steps:
                await release.wait()
                raise StopAsyncIteration
            return await super().__anext__()

    calls = 0

    def id_factory():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sibling bookkeeping failure")
        return "a-fact-id"

    def factory(source):
        if source.kind == "a":
            streams["a"] = BlockingStream(Fact("a", 1.0, {}, observer="alice"))
            return streams["a"]
        streams["b"] = _Stream(Fact("b", 1.0, {}, observer="alice"))
        return streams["b"]

    with pytest.raises(SourceTierCollectionFailed) as raised:
        asyncio.run(
            collect_source_tier(
                invocation,
                capture,
                0,
                factory,
                clock=lambda: 2.0,
                id_factory=id_factory,
            )
        )

    failure = raised.value
    assert failure.cause.args == ("sibling bookkeeping failure",)
    assert len(failure.failed_sources) == 1
    assert failure.failed_sources[0].phase == "bookkeeping"
    assert failure.failed_sources[0].pairs == ()
    assert len(failure.cancelled_sources) == 1
    assert failure.cancelled_sources[0].phase == "cancelled"
    assert failure.cancelled_sources[0].pairs == (
        (failure.cancelled_sources[0].facts[0], "a-fact-id"),
    )
    assert streams["a"].closed == 1
    assert streams["b"].closed == 1


def test_collection_bookkeeping_failure_does_not_drop_sibling_control_flow():
    class CoordinatorInterrupt(BaseException):
        pass

    interrupt_cause = RuntimeError("control origin")
    interrupt = CoordinatorInterrupt("stop collection")
    interrupt.__cause__ = interrupt_cause
    source_a = SimpleNamespace(kind="a", command="collect-a", observer="alice")
    source_b = SimpleNamespace(kind="b", command="collect-b", observer="alice")
    invocation = SimpleNamespace(
        invocation_id="invocation-id",
        observer="runner",
        lifecycle_ids=("life-a", "life-b"),
        tiers=((0, 1),),
        initial_capture=SimpleNamespace(
            sources=((source_a, None), (source_b, None))
        ),
    )
    capture = SimpleNamespace(basis="basis")
    streams = {
        "a": _Stream(Fact("a", 1.0, {}, observer="alice")),
        "b": _Stream(interrupt),
    }

    def id_factory():
        raise OSError("ID allocation unavailable")

    with pytest.raises(CoordinatorInterrupt) as raised:
        asyncio.run(
            collect_source_tier(
                invocation,
                capture,
                0,
                lambda source: streams[source.kind],
                clock=lambda: 2.0,
                id_factory=id_factory,
            )
        )

    assert raised.value is interrupt
    assert raised.value.__cause__ is interrupt_cause
    assert streams["a"].closed == streams["b"].closed == 1


def test_overall_bookkeeping_failure_keeps_collected_tier_uncommitted(
    tmp_path, monkeypatch, keys, signer
):
    from engine.arrival_file_backend import FileLedger
    from engine.arrival_sources import execute_source_invocation, prepare_source_invocation
    from tests.test_arrival_sources import _credentials, _source_target

    target = _source_target(tmp_path, monkeypatch, keys, signer, (("a", ""),))
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
    clock_calls = 0

    def clock():
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 2:
            raise OSError("overall timestamp unavailable")
        return 12.0

    def factory(_source):
        return _Stream(Fact("a", 11.0, {"value": 1}, observer="kyle"))

    result = asyncio.run(
        execute_source_invocation(
            target.registry,
            target.descriptor,
            target.locator,
            plan,
            credentials=_credentials(),
            collector_factory=factory,
            clock=clock,
        )
    )

    assert clock_calls == 2
    assert result.status == "incomplete"
    assert isinstance(result.terminal, OSError)
    assert result.terminal_tier is result.collected_tiers[0]
    assert result.collected_uncommitted is result.terminal_tier
    assert result.terminal_tier.sources[0].status == "ok"
    assert len(result.terminal_tier.sources[0].facts) == len(
        result.terminal_tier.sources[0].fact_ids
    ) == 1
    assert result.durable_tiers == ()
    assert FileLedger(target.log).head() == before
