"""Captured, tier-atomic source execution for an Arrival Authority.

Collection has no custody handle.  A CURRENT runtime capture is taken before
each tier's collectors run, and the resulting observations are planned against
that same head.  A completed tier uses one batch append and explicit projection
catch-up; failures retain collection and any durable commits without retrying a
collector.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from atoms import Fact, SourceError
from ulid import ULID

from .arrival_head_seam import NotWitnessed
from .arrival_maintenance import sync_projection
from .runtime_write import (
    BatchFactInput,
    BatchPostCommitProjectionFailed,
    BatchWriteCommitUnknown,
    BatchWritePlan,
    CommittedBatchWrite,
    ProjectionOutcome,
    RuntimeCapture,
    capture_runtime,
    execute_batch_write,
    plan_batch_from_capture,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .arrival_contract import Commit, ReadBasis, StoreDescriptor
    from .arrival_registry import BackendRegistry
    from .credentials import WriteCredentials

__all__ = [
    "CadenceEvidence",
    "CollectedSource",
    "CollectedTier",
    "DeclarationChangedDuringInvocation",
    "DispatchFailed",
    "DispatchIntent",
    "InvalidSourceOutput",
    "PartialCollectedSource",
    "SourceInvocationPlan",
    "SourceInvocationResult",
    "SourcePreparationRefused",
    "SourceTierCollectionFailed",
    "SourceTierPreparationRefused",
    "TierCommitted",
    "collect_source_tier",
    "execute_source_invocation",
    "prepare_collected_tier",
    "prepare_source_invocation",
]

CollectorFactory = Callable[[Any], AsyncIterable[Fact]]
RunDispatcher = Callable[["Commit", tuple["DispatchIntent", ...]], None]


class SourcePreparationRefused(Exception):
    """Known source/lifecycle admission refused before any collector ran."""

    def __init__(self, message: str, *, capture: RuntimeCapture, cause: Exception) -> None:
        super().__init__(message)
        self.capture = capture
        self.cause = cause


class InvalidSourceOutput(Exception):
    """A collector yielded a value that is not an observation Fact."""

    def __init__(self, source_index: int, value: object) -> None:
        super().__init__(
            f"source {source_index} yielded {type(value).__name__}, expected atoms.Fact"
        )
        self.source_index = source_index
        self.value_type = type(value).__name__
        self.value_repr = repr(value)


class SourceTierPreparationRefused(Exception):
    """A collected tier could not become an appendable all-or-nothing plan."""

    def __init__(self, collected: CollectedTier, cause: Exception) -> None:
        super().__init__(f"source tier {collected.tier_index} was refused: {cause}")
        self.collected = collected
        self.cause = cause


class DeclarationChangedDuringInvocation(Exception):
    """A later CURRENT capture no longer has the invocation's declaration."""

    def __init__(self, initial: RuntimeCapture, observed: RuntimeCapture) -> None:
        super().__init__(
            "effective declaration changed after a prior source tier committed; "
            "remaining collectors were not run"
        )
        self.initial_basis = initial.basis
        self.observed_basis = observed.basis
        self.initial_documents = initial.declaration_documents
        self.observed_documents = observed.declaration_documents


class DispatchFailed(Exception):
    """A run-clause dispatch failed after its tier commit became durable."""

    def __init__(
        self,
        commit: Commit,
        intents: tuple[DispatchIntent, ...],
        cause: Exception,
    ) -> None:
        super().__init__(
            "source tier committed but postcommit run-clause dispatch failed; "
            "the invocation is incomplete and is not retried"
        )
        self.commit = commit
        self.intents = intents
        self.tick_ids = tuple(intent.tick_id for intent in intents)
        self.tick_names = tuple(intent.tick_name for intent in intents)
        self.commands = tuple(intent.command for intent in intents)
        self.cause = cause


@dataclass(frozen=True)
class CadenceEvidence:
    """Why one captured source did or did not qualify at the initial H."""

    source_index: int
    kind: str
    mode: str
    evaluated_at: float
    latest_success_id: str | None
    latest_success_ts: float | None
    trigger_fact_ids: tuple[str, ...]
    interval_seconds: float | None
    forced: bool
    qualified: bool


@dataclass(frozen=True)
class SourceInvocationPlan:
    """Fixed qualification and source order built before collection."""

    invocation_id: str
    observer: str
    initial_capture: RuntimeCapture
    cadence: tuple[CadenceEvidence, ...]
    qualifying_indices: tuple[int, ...]
    tiers: tuple[tuple[int, ...], ...]
    lifecycle_ids: tuple[str, ...]
    overall_sync_id: str

    @property
    def skipped(self) -> tuple[CadenceEvidence, ...]:
        return tuple(evidence for evidence in self.cadence if not evidence.qualified)

    @property
    def source_kinds(self) -> tuple[str, ...]:
        sources = self.initial_capture.sources
        return tuple(source.kind for source, _cadence in sources)


@dataclass(frozen=True)
class CollectedSource:
    """One collector attempt, including output retained before an error."""

    source_index: int
    kind: str
    command: str
    source_observer: str
    facts: tuple[Fact, ...]
    fact_ids: tuple[str, ...]
    lifecycle_fact: Fact
    lifecycle_id: str
    status: Literal["ok", "error", "invalid"]
    attempt_count: int = 1
    stderr: str = ""
    returncode: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    invalid_output: InvalidSourceOutput | None = None


@dataclass(frozen=True)
class PartialCollectedSource:
    """Paired observations retained when coordinator collection did not finish."""

    source_index: int
    kind: str
    command: str
    source_observer: str
    pairs: tuple[tuple[Fact, str], ...]
    phase: Literal["bookkeeping", "cleanup", "cancelled"]
    error_type: str | None = None
    error_message: str | None = None

    @property
    def facts(self) -> tuple[Fact, ...]:
        return tuple(fact for fact, _fact_id in self.pairs)

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(fact_id for _fact, fact_id in self.pairs)


@dataclass(frozen=True)
class CollectedTier:
    """Deterministically ordered results from one concurrently collected tier."""

    tier_index: int
    basis: ReadBasis
    sources: tuple[CollectedSource, ...]
    include_pending_boundaries: bool


class SourceTierCollectionFailed(Exception):
    """Coordinator work failed after retaining an exactly paired partial tier."""

    def __init__(
        self,
        *,
        tier_index: int,
        basis: ReadBasis,
        completed_sources: tuple[CollectedSource, ...],
        failed_sources: tuple[PartialCollectedSource, ...],
        cancelled_sources: tuple[PartialCollectedSource, ...],
        cause: Exception,
    ) -> None:
        super().__init__(
            f"source tier {tier_index} collection coordinator failed: {cause}"
        )
        self.tier_index = tier_index
        self.basis = basis
        self.completed_sources = completed_sources
        self.failed_sources = failed_sources
        self.cancelled_sources = cancelled_sources
        self.cause = cause


@dataclass(frozen=True)
class _CollectionState:
    """Fixed source identity plus one coroutine-owned paired accumulator."""

    source_index: int
    kind: str
    command: str
    source_observer: str
    pairs: list[tuple[Fact, str]]

    def partial(
        self,
        phase: Literal["bookkeeping", "cleanup", "cancelled"],
        error: Exception | None = None,
    ) -> PartialCollectedSource:
        return PartialCollectedSource(
            source_index=self.source_index,
            kind=self.kind,
            command=self.command,
            source_observer=self.source_observer,
            pairs=tuple(self.pairs),
            phase=phase,
            error_type=None if error is None else type(error).__name__,
            error_message=None if error is None else str(error),
        )


class _CollectionStepFailed(Exception):
    def __init__(
        self,
        state: _CollectionState,
        phase: Literal["bookkeeping", "cleanup"],
        cause: Exception,
    ) -> None:
        super().__init__(str(cause))
        self.state = state
        self.phase = phase
        self.cause = cause


@dataclass(frozen=True)
class DispatchIntent:
    """Captured run-clause command plus the exact durable tick evidence."""

    tick_id: str
    tick_name: str
    command: str
    ts: float
    since: float | None
    origin: str
    payload_text: str
    payload: Mapping[str, Any]
    fact_cursor: str | None
    window_start: str | None
    window_hash: str | None
    vertex_path: Path | None


@dataclass(frozen=True)
class TierCommitted:
    """One actual custody commit and the collection it made durable."""

    tier_index: int
    basis: ReadBasis
    collected: CollectedTier
    plan: BatchWritePlan
    outcome: CommittedBatchWrite
    witnessed: bool
    dispatch_intents: tuple[DispatchIntent, ...] = ()
    dispatch_succeeded: bool | None = None

    @property
    def commit(self) -> Commit:
        assert self.outcome.commit is not None
        return self.outcome.commit


@dataclass(frozen=True)
class SourceInvocationResult:
    """Complete or interrupted source execution with durable evidence separated."""

    invocation_id: str
    status: Literal["ok", "error", "incomplete"]
    plan: SourceInvocationPlan
    bases: tuple[ReadBasis, ...]
    collected_tiers: tuple[CollectedTier, ...]
    durable_tiers: tuple[TierCommitted, ...]
    terminal_tier: CollectedTier | None
    terminal_plan: BatchWritePlan | None
    collected_uncommitted: CollectedTier | None
    collected_unknown: CollectedTier | None
    error_lifecycle_ids: tuple[str, ...]
    durable_error_lifecycle_ids: tuple[str, ...]
    overall_sync_id: str
    terminal: BaseException | None = None


def _new_id() -> str:
    return str(ULID())


def _latest_success(facts: Sequence[Any], kind: str) -> Any | None:
    matching = [
        fact
        for fact in facts
        if fact.kind == f"_sync.{kind}" and fact.payload.get("status") == "ok"
    ]
    return max(matching, key=lambda fact: (fact.ts, fact.id), default=None)


def _cadence_evidence(
    source_index: int,
    source: Any,
    cadence: Any,
    facts: Sequence[Any],
    *,
    evaluated_at: float,
    force: bool,
) -> CadenceEvidence:
    last = _latest_success(facts, source.kind)
    mode = cadence.mode
    trigger_ids: tuple[str, ...] = ()
    interval = getattr(cadence, "_interval", None)
    if mode == "always":
        qualified = True
    elif mode == "elapsed":
        qualified = last is None or evaluated_at - last.ts >= interval
    elif mode == "triggered":
        threshold = float("-inf") if last is None else last.ts
        trigger_ids = tuple(
            fact.id
            for fact in facts
            if fact.kind in cadence.trigger_kinds and fact.ts > threshold
        )
        qualified = bool(trigger_ids)
    else:
        qualified = False
    if force:
        qualified = True
    return CadenceEvidence(
        source_index=source_index,
        kind=source.kind,
        mode=mode,
        evaluated_at=evaluated_at,
        latest_success_id=None if last is None else last.id,
        latest_success_ts=None if last is None else last.ts,
        trigger_fact_ids=trigger_ids,
        interval_seconds=interval,
        forced=force,
        qualified=qualified,
    )


def _source_observers(source: Any) -> tuple[str, ...]:
    nested = getattr(source, "sources", None)
    if nested is not None:
        return tuple(observer for item in nested for observer in _source_observers(item))
    observer = getattr(source, "observer", "")
    return (observer,) if observer else ()


def _preflight_known_admission(
    capture: RuntimeCapture,
    sources: Sequence[tuple[Any, Any]],
    qualifying: Sequence[int],
    *,
    observer: str,
    credentials: WriteCredentials,
    lifecycle_ids: Sequence[str],
    overall_sync_id: str,
) -> None:
    from .admission import grant_for_observer

    effective = capture.effective_declaration
    try:
        grant_for_observer(effective, observer)
        for index in qualifying:
            for source_observer in _source_observers(sources[index][0]):
                grant_for_observer(effective, source_observer)
        known = [
            BatchFactInput(
                Fact.of(
                    f"_sync.{sources[index][0].kind}",
                    observer,
                    ts=capture.evaluated_at,
                    command=sources[index][0].command,
                    status="ok",
                ),
                fact_id=lifecycle_ids[index],
                admit_undeclared=True,
            )
            for index in qualifying
        ]
        known.append(
            BatchFactInput(
                Fact.of(
                    "_sync",
                    observer,
                    ts=capture.evaluated_at,
                    status="ok",
                    sources_run=len(qualifying),
                ),
                fact_id=overall_sync_id,
                admit_undeclared=True,
            )
        )
        # One at a time checks exact lifecycle grant/strict/tick-signing rules
        # without imposing a fictitious whole-invocation atomic limit.
        for item in known:
            plan_batch_from_capture(capture, (item,), credentials=credentials)
        if capture.pending_boundaries:
            # Pending ticks are already known at H and can require a tick signer
            # in a signed era. Refuse before any external collector runs.
            plan_batch_from_capture(
                capture,
                (),
                credentials=credentials,
                include_pending_boundaries=True,
            )
    except Exception as exc:
        raise SourcePreparationRefused(
            "source lifecycle admission refused before collection",
            capture=capture,
            cause=exc,
        ) from exc


def prepare_source_invocation(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    locator: Any,
    *,
    observer: str,
    credentials: WriteCredentials,
    force: bool = False,
    evaluated_at: float | None = None,
    id_factory: Callable[[], str] = _new_id,
) -> SourceInvocationPlan:
    """Capture H, cadence, source order and tiers before any collector runs."""
    from .executor import _build_dependency_graph, _toposort_tiers

    if not observer:
        raise ValueError("source lifecycle observer must be explicit and nonempty")
    capture = capture_runtime(
        registry,
        descriptor,
        locator,
        source_mode=True,
        evaluated_at=evaluated_at,
        credentials=credentials,
    )
    sources = capture.sources
    evidence = tuple(
        _cadence_evidence(
            index,
            source,
            cadence,
            capture.runtime_facts,
            evaluated_at=capture.evaluated_at,
            force=force,
        )
        for index, (source, cadence) in enumerate(sources)
    )
    qualifying = tuple(item.source_index for item in evidence if item.qualified)
    deps = _build_dependency_graph(list(sources))
    tiers = tuple(tuple(tier) for tier in _toposort_tiers(set(qualifying), deps))
    invocation_id = id_factory()
    lifecycle_ids = tuple(id_factory() for _ in sources)
    overall_sync_id = id_factory()
    _preflight_known_admission(
        capture,
        sources,
        qualifying,
        observer=observer,
        credentials=credentials,
        lifecycle_ids=lifecycle_ids,
        overall_sync_id=overall_sync_id,
    )
    return SourceInvocationPlan(
        invocation_id=invocation_id,
        observer=observer,
        initial_capture=capture,
        cadence=evidence,
        qualifying_indices=qualifying,
        tiers=tiers,
        lifecycle_ids=lifecycle_ids,
        overall_sync_id=overall_sync_id,
    )


async def _close_owned_streams(
    stream: object | None,
    iterator: object | None,
    *,
    primary: BaseException | None,
) -> Exception | None:
    """Attempt async close on the iterator and owner before propagating interruption.

    This releases Python iterator resources only. It does not claim that an
    underlying collector reversed or terminated any external effect.
    """
    failures: list[Exception] = []
    handles: list[object] = []
    deferred_interrupt: BaseException | None = None
    primary_is_interrupt = primary is not None and not isinstance(primary, Exception)
    for handle in (iterator, stream):
        if handle is None or any(handle is existing for existing in handles):
            continue
        handles.append(handle)
        try:
            close = getattr(handle, "aclose", None)
            if not callable(close):
                continue
            await close()
        except Exception as exc:
            failures.append(exc)
        except BaseException as exc:
            if not primary_is_interrupt and deferred_interrupt is None:
                deferred_interrupt = exc
    if deferred_interrupt is not None:
        raise deferred_interrupt
    return failures[0] if failures else None


async def _collect_one(
    invocation: SourceInvocationPlan,
    state: _CollectionState,
    source: Any,
    collector_factory: CollectorFactory | None,
    *,
    clock: Callable[[], float],
    id_factory: Callable[[], str],
) -> CollectedSource:
    status: Literal["ok", "error", "invalid"] = "ok"
    stderr = ""
    returncode: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    invalid: InvalidSourceOutput | None = None
    stream: object | None = None
    iterator: object | None = None
    primary: BaseException | None = None
    try:
        stream = source.collect() if collector_factory is None else collector_factory(source)
        iterator = aiter(stream)
        async for value in iterator:
            if not isinstance(value, Fact):
                invalid = InvalidSourceOutput(state.source_index, value)
                primary = invalid
                status = "invalid"
                break
            try:
                fact_id = id_factory()
                state.pairs.append((value, fact_id))
            except Exception as exc:
                failure = _CollectionStepFailed(state, "bookkeeping", exc)
                primary = failure
                raise failure from exc
    except _CollectionStepFailed:
        raise
    except asyncio.CancelledError as exc:
        primary = exc
        raise
    except SourceError as exc:
        primary = exc
        status = "error"
        stderr = exc.stderr
        returncode = exc.returncode
        error_type = type(exc).__name__
        error_message = str(exc)
    except Exception as exc:
        primary = exc
        status = "error"
        error_type = type(exc).__name__
        error_message = str(exc)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_error = await _close_owned_streams(
            stream, iterator, primary=primary
        )
        if cleanup_error is not None and primary is None:
            raise _CollectionStepFailed(state, "cleanup", cleanup_error) from cleanup_error

    try:
        payload: dict[str, Any] = {
            "command": state.command,
            "status": "error" if status != "ok" else "ok",
            "count": len(state.pairs),
            "invocation_id": invocation.invocation_id,
            "source_index": state.source_index,
        }
        if stderr:
            payload["stderr"] = stderr
        if returncode is not None:
            payload["returncode"] = returncode
        if error_type is not None:
            payload["error_type"] = error_type
        if error_message is not None:
            payload["error"] = error_message
        if invalid is not None:
            payload["error_type"] = type(invalid).__name__
            payload["error"] = str(invalid)
        lifecycle = Fact(
            f"_sync.{state.kind}",
            clock(),
            payload,
            observer=invocation.observer,
        )
        return CollectedSource(
            source_index=state.source_index,
            kind=state.kind,
            command=state.command,
            source_observer=state.source_observer,
            facts=tuple(fact for fact, _fact_id in state.pairs),
            fact_ids=tuple(fact_id for _fact, fact_id in state.pairs),
            lifecycle_fact=lifecycle,
            lifecycle_id=invocation.lifecycle_ids[state.source_index],
            status=status,
            stderr=stderr,
            returncode=returncode,
            error_type=error_type,
            error_message=error_message,
            invalid_output=invalid,
        )
    except Exception as exc:
        raise _CollectionStepFailed(state, "bookkeeping", exc) from exc


async def collect_source_tier(
    invocation: SourceInvocationPlan,
    capture: RuntimeCapture,
    tier_index: int,
    collector_factory: CollectorFactory | None = None,
    *,
    clock: Callable[[], float] = time.time,
    id_factory: Callable[[], str] = _new_id,
) -> CollectedTier:
    """Collect one fixed tier concurrently while retaining source-list order."""
    indices = invocation.tiers[tier_index]
    sources = invocation.initial_capture.sources
    states = [
        _CollectionState(
            source_index=index,
            kind=sources[index][0].kind,
            command=sources[index][0].command,
            source_observer=sources[index][0].observer,
            pairs=[],
        )
        for index in indices
    ]
    tasks = [
        asyncio.create_task(
            _collect_one(
                invocation,
                state,
                sources[state.source_index][0],
                collector_factory,
                clock=clock,
                id_factory=id_factory,
            )
        )
        for state in states
    ]
    try:
        collected = tuple(await asyncio.gather(*tasks))
    except _CollectionStepFailed as primary:
        for task in tasks:
            if not task.done():
                task.cancel()
        settled = await asyncio.gather(*tasks, return_exceptions=True)
        for result in settled:
            if isinstance(result, BaseException) and not isinstance(
                result, (_CollectionStepFailed, asyncio.CancelledError)
            ):
                # This sibling already owns its chaining evidence. Adding or
                # clearing a cause here would rewrite the control exception.
                raise result  # noqa: B904
        completed = tuple(
            result for result in settled if isinstance(result, CollectedSource)
        )
        failed = tuple(
            result.state.partial(result.phase, result.cause)
            for result in settled
            if isinstance(result, _CollectionStepFailed)
        )
        cancelled = tuple(
            state.partial("cancelled")
            for state, result in zip(states, settled, strict=True)
            if isinstance(result, asyncio.CancelledError)
        )
        raise SourceTierCollectionFailed(
            tier_index=tier_index,
            basis=capture.basis,
            completed_sources=completed,
            failed_sources=failed,
            cancelled_sources=cancelled,
            cause=primary.cause,
        ) from primary.cause
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return CollectedTier(
        tier_index=tier_index,
        basis=capture.basis,
        sources=collected,
        include_pending_boundaries=tier_index == 0,
    )


def _overall_fact(
    invocation: SourceInvocationPlan,
    collected: Sequence[CollectedTier],
    *,
    now: float,
) -> Fact:
    sources = [source for tier in collected for source in tier.sources]
    errors = sum(source.status != "ok" for source in sources)
    total = sum(len(source.facts) + 1 for source in sources)
    duration_ms = max(0, int((now - invocation.initial_capture.evaluated_at) * 1000))
    return Fact.of(
        "_sync",
        invocation.observer,
        ts=now,
        status="error" if errors else "ok",
        sources_run=len(invocation.qualifying_indices),
        sources_skipped=len(invocation.skipped),
        source_errors=errors,
        total_facts=total,
        duration_ms=duration_ms,
        invocation_id=invocation.invocation_id,
    )


def prepare_collected_tier(
    capture: RuntimeCapture,
    collected: CollectedTier,
    *,
    credentials: WriteCredentials,
    overall_fact: Fact | None = None,
    overall_sync_id: str | None = None,
) -> BatchWritePlan:
    """Turn retained collection into one exact-H tier batch plan."""
    try:
        if collected.basis != capture.basis:
            raise ValueError(
                "collected tier basis does not match the runtime capture basis"
            )
        invalid = next(
            (
                source.invalid_output
                for source in collected.sources
                if source.invalid_output is not None
            ),
            None,
        )
        if invalid is not None:
            raise invalid
        items: list[BatchFactInput] = []
        for source in collected.sources:
            items.extend(
                BatchFactInput(fact, fact_id=fact_id)
                for fact, fact_id in zip(source.facts, source.fact_ids, strict=True)
            )
            items.append(
                BatchFactInput(
                    source.lifecycle_fact,
                    fact_id=source.lifecycle_id,
                    admit_undeclared=True,
                )
            )
        if overall_fact is not None:
            if overall_sync_id is None:
                raise ValueError("overall_sync_id is required with overall_fact")
            items.append(
                BatchFactInput(
                    overall_fact,
                    fact_id=overall_sync_id,
                    admit_undeclared=True,
                )
            )
        return plan_batch_from_capture(
            capture,
            items,
            credentials=credentials,
            include_pending_boundaries=collected.include_pending_boundaries,
        )
    except Exception as exc:
        if isinstance(exc, SourceTierPreparationRefused):
            raise
        raise SourceTierPreparationRefused(collected, exc) from exc


def _dispatch_intents(
    capture: RuntimeCapture, plan: BatchWritePlan
) -> tuple[DispatchIntent, ...]:
    runs = {
        **dict(zip(plan.pending_tick_ids, plan.pending_tick_runs, strict=True)),
        **{
            item.tick_id: item.tick_run
            for item in plan.items
            if item.tick_id is not None
        },
    }
    vertex_path = capture.effective_declaration.path
    intents: list[DispatchIntent] = []
    for draft in plan.drafts:
        if draft.kind != "tick":
            continue
        body = draft.body
        tick_id = str(body["id"])
        command = runs.get(tick_id)
        if not command:
            continue
        payload_text = str(body["payload"])
        payload = json.loads(payload_text)
        intents.append(
            DispatchIntent(
                tick_id=tick_id,
                tick_name=str(body["name"]),
                command=command,
                ts=float(body["ts"]),
                since=None if body["since"] is None else float(body["since"]),
                origin=str(body["origin"]),
                payload_text=payload_text,
                payload=MappingProxyType(payload),
                fact_cursor=body.get("fact_cursor"),
                window_start=body.get("window_start"),
                window_hash=body.get("window_hash"),
                vertex_path=vertex_path,
            )
        )
    return tuple(intents)


def _result(
    invocation: SourceInvocationPlan,
    *,
    bases: Sequence[ReadBasis],
    collected: Sequence[CollectedTier],
    durable: Sequence[TierCommitted],
    terminal_tier: CollectedTier | None = None,
    terminal_plan: BatchWritePlan | None = None,
    collected_uncommitted: CollectedTier | None = None,
    collected_unknown: CollectedTier | None = None,
    terminal: BaseException | None = None,
) -> SourceInvocationResult:
    error_ids = tuple(
        source.lifecycle_id
        for tier in collected
        for source in tier.sources
        if source.status != "ok"
    )
    durable_indices = {tier.tier_index for tier in durable}
    durable_error_ids = tuple(
        source.lifecycle_id
        for tier in collected
        if tier.tier_index in durable_indices
        for source in tier.sources
        if source.status != "ok"
    )
    status: Literal["ok", "error", "incomplete"]
    if terminal is not None:
        status = "incomplete"
    elif error_ids:
        status = "error"
    else:
        status = "ok"
    return SourceInvocationResult(
        invocation_id=invocation.invocation_id,
        status=status,
        plan=invocation,
        bases=tuple(bases),
        collected_tiers=tuple(collected),
        durable_tiers=tuple(durable),
        terminal_tier=terminal_tier,
        terminal_plan=terminal_plan,
        collected_uncommitted=collected_uncommitted,
        collected_unknown=collected_unknown,
        error_lifecycle_ids=error_ids,
        durable_error_lifecycle_ids=durable_error_ids,
        overall_sync_id=invocation.overall_sync_id,
        terminal=terminal,
    )


async def execute_source_invocation(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    locator: Any,
    invocation: SourceInvocationPlan,
    *,
    credentials: WriteCredentials,
    collector_factory: CollectorFactory | None = None,
    dispatcher: RunDispatcher | None = None,
    clock: Callable[[], float] = time.time,
    id_factory: Callable[[], str] = _new_id,
) -> SourceInvocationResult:
    """Collect and commit fixed tiers once each; never retry external effects."""
    bases: list[ReadBasis] = []
    collected_tiers: list[CollectedTier] = []
    durable_tiers: list[TierCommitted] = []
    tiers: tuple[tuple[int, ...], ...] = invocation.tiers or ((),)
    current_capture = invocation.initial_capture
    frozen_locator = invocation.initial_capture._locator_copy()

    for tier_index, _indices in enumerate(tiers):
        if tier_index:
            try:
                current_capture = capture_runtime(
                    registry,
                    descriptor,
                    frozen_locator,
                    credentials=credentials,
                )
            except Exception as exc:
                return _result(
                    invocation,
                    bases=bases,
                    collected=collected_tiers,
                    durable=durable_tiers,
                    terminal=exc,
                )
            if (
                current_capture.declaration_documents
                != invocation.initial_capture.declaration_documents
            ):
                changed = DeclarationChangedDuringInvocation(
                    invocation.initial_capture, current_capture
                )
                return _result(
                    invocation,
                    bases=(*bases, current_capture.basis),
                    collected=collected_tiers,
                    durable=durable_tiers,
                    terminal=changed,
                )
        bases.append(current_capture.basis)

        if invocation.tiers:
            try:
                tier = await collect_source_tier(
                    invocation,
                    current_capture,
                    tier_index,
                    collector_factory,
                    clock=clock,
                    id_factory=id_factory,
                )
            except SourceTierCollectionFailed as exc:
                return _result(
                    invocation,
                    bases=bases,
                    collected=collected_tiers,
                    durable=durable_tiers,
                    terminal=exc,
                )
        else:
            tier = CollectedTier(
                tier_index=0,
                basis=current_capture.basis,
                sources=(),
                include_pending_boundaries=True,
            )
        collected_tiers.append(tier)
        final_tier = tier_index == len(tiers) - 1
        try:
            overall = (
                _overall_fact(invocation, collected_tiers, now=clock())
                if final_tier
                else None
            )
            batch_plan = prepare_collected_tier(
                current_capture,
                tier,
                credentials=credentials,
                overall_fact=overall,
                overall_sync_id=invocation.overall_sync_id if final_tier else None,
            )
        except Exception as exc:
            return _result(
                invocation,
                bases=bases,
                collected=collected_tiers,
                durable=durable_tiers,
                terminal_tier=tier,
                collected_uncommitted=tier,
                terminal=exc,
            )

        try:
            intents = _dispatch_intents(current_capture, batch_plan)
        except Exception as exc:
            return _result(
                invocation,
                bases=bases,
                collected=collected_tiers,
                durable=durable_tiers,
                terminal_tier=tier,
                terminal_plan=batch_plan,
                collected_uncommitted=tier,
                terminal=exc,
            )

        try:
            outcome = execute_batch_write(
                registry,
                descriptor,
                batch_plan,
                after_commit=lambda head: sync_projection(
                    registry, descriptor, through=head
                ),
            )
        except NotWitnessed as exc:
            if exc.commit is not None:
                outcome = CommittedBatchWrite(
                    exc.commit,
                    batch_plan.items,
                    ProjectionOutcome.PENDING,
                    batch_plan.pending_tick_ids,
                    batch_plan.pending_tick_names,
                    batch_plan.pending_tick_runs,
                )
                durable_tiers.append(
                    TierCommitted(
                        tier_index,
                        current_capture.basis,
                        tier,
                        batch_plan,
                        outcome,
                        witnessed=False,
                        dispatch_intents=intents,
                    )
                )
            return _result(
                invocation,
                bases=bases,
                collected=collected_tiers,
                durable=durable_tiers,
                terminal_tier=tier,
                terminal_plan=batch_plan,
                collected_uncommitted=None if exc.commit is not None else tier,
                terminal=exc,
            )
        except BatchPostCommitProjectionFailed as exc:
            outcome = CommittedBatchWrite(
                exc.commit,
                batch_plan.items,
                ProjectionOutcome.FAILED,
                batch_plan.pending_tick_ids,
                batch_plan.pending_tick_names,
                batch_plan.pending_tick_runs,
            )
            durable_tiers.append(
                TierCommitted(
                    tier_index,
                    current_capture.basis,
                    tier,
                    batch_plan,
                    outcome,
                    witnessed=True,
                    dispatch_intents=intents,
                )
            )
            return _result(
                invocation,
                bases=bases,
                collected=collected_tiers,
                durable=durable_tiers,
                terminal_tier=tier,
                terminal_plan=batch_plan,
                terminal=exc,
            )
        except BatchWriteCommitUnknown as exc:
            # The append was attempted exactly once, but its durability is unknown.
            # Calling this tier "uncommitted" would invite an unsafe retry.
            return _result(
                invocation,
                bases=bases,
                collected=collected_tiers,
                durable=durable_tiers,
                terminal_tier=tier,
                terminal_plan=batch_plan,
                collected_unknown=tier,
                terminal=exc,
            )
        except Exception as exc:
            return _result(
                invocation,
                bases=bases,
                collected=collected_tiers,
                durable=durable_tiers,
                terminal_tier=tier,
                terminal_plan=batch_plan,
                collected_uncommitted=tier,
                terminal=exc,
            )

        committed = TierCommitted(
            tier_index=tier_index,
            basis=current_capture.basis,
            collected=tier,
            plan=batch_plan,
            outcome=outcome,
            witnessed=True,
            dispatch_intents=intents,
        )
        if dispatcher is not None and intents:
            try:
                dispatcher(committed.commit, intents)
            except Exception as exc:
                committed = replace(committed, dispatch_succeeded=False)
                durable_tiers.append(committed)
                failed = DispatchFailed(committed.commit, intents, exc)
                return _result(
                    invocation,
                    bases=bases,
                    collected=collected_tiers,
                    durable=durable_tiers,
                    terminal_tier=tier,
                    terminal_plan=batch_plan,
                    terminal=failed,
                )
            committed = replace(committed, dispatch_succeeded=True)
        durable_tiers.append(committed)

    return _result(
        invocation,
        bases=bases,
        collected=collected_tiers,
        durable=durable_tiers,
    )
