"""Captured Arrival source execution at the SDK process boundary."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterable, Callable, Mapping
from pathlib import Path
from typing import Any

from atoms import Fact
from engine.arrival_contract import Commit, Profile
from engine.arrival_head_seam import NotWitnessed
from engine.arrival_registry import BackendRegistry
from engine.arrival_sources import (
    CollectedSource,
    CollectedTier,
    DeclarationChangedDuringInvocation,
    DispatchFailed,
    DispatchIntent,
    InvalidSourceOutput,
    PartialCollectedSource,
    SourceInvocationResult,
    SourcePreparationRefused,
    SourceTierCollectionFailed,
    SourceTierPreparationRefused,
    TierCommitted,
    execute_source_invocation,
    prepare_source_invocation,
)
from engine.credentials import CredentialProvider
from engine.runtime_write import (
    BatchPostCommitProjectionFailed,
    BatchWriteCommitUnknown,
    BatchWritePlan,
    BatchWritePreparationRefused,
)

from .emit import CustodyCredentialProvider
from .errors import ArrivalRefusal, normalize_exception
from .target import _arrival_descriptor, _refuse_arrival_aggregate_members
from .types import (
    SdkError,
    SourceCadenceResult,
    SourceCollectedResult,
    SourceDispatchResult,
    SourceFactResult,
    SourceRunResult,
    SourceTerminalResult,
    SourceTierResult,
    StoreDescriptorInfo,
    TargetUnsupported,
)

__all__ = ["run_sources"]

CollectorFactory = Callable[[Any], AsyncIterable[Fact]]
RunDispatcher = Callable[[Commit, tuple[DispatchIntent, ...]], None]


def _source_fact(fact: Fact, fact_id: str) -> SourceFactResult:
    try:
        payload = copy.deepcopy(
            dict(fact.payload) if isinstance(fact.payload, Mapping) else fact.payload
        )
        payload_snapshot = True
    except Exception:  # retain type/value without claiming a detached snapshot
        payload = fact.payload
        payload_snapshot = False
    return SourceFactResult(
        id=fact_id,
        kind=fact.kind,
        ts=fact.ts,
        observer=fact.observer,
        origin=fact.origin,
        payload=payload,
        payload_snapshot=payload_snapshot,
    )


def _collected_source(source: CollectedSource) -> SourceCollectedResult:
    facts = tuple(
        _source_fact(fact, fact_id)
        for fact, fact_id in zip(source.facts, source.fact_ids, strict=True)
    )
    return SourceCollectedResult(
        source_index=source.source_index,
        kind=source.kind,
        command=source.command,
        source_observer=source.source_observer,
        facts=facts,
        lifecycle_fact=_source_fact(source.lifecycle_fact, source.lifecycle_id),
        lifecycle_id=source.lifecycle_id,
        status=source.status,
        attempt_count=source.attempt_count,
        stderr=source.stderr,
        returncode=source.returncode,
        error_type=(
            type(source.invalid_output).__name__
            if source.invalid_output is not None
            else source.error_type
        ),
        error_message=(
            str(source.invalid_output)
            if source.invalid_output is not None
            else source.error_message
        ),
    )


def _dispatch_result(
    intent: DispatchIntent, committed: TierCommitted
) -> SourceDispatchResult:
    try:
        payload = copy.deepcopy(dict(intent.payload))
    except Exception:  # pragma: no cover - engine intent payloads are JSON mappings
        payload = dict(intent.payload)
    attempted = committed.dispatch_succeeded is not None
    return SourceDispatchResult(
        tick_id=intent.tick_id,
        tick_name=intent.tick_name,
        command=intent.command,
        attempted=attempted,
        succeeded=committed.dispatch_succeeded,
        ts=intent.ts,
        since=intent.since,
        origin=intent.origin,
        payload_text=intent.payload_text,
        payload=payload,
        fact_cursor=intent.fact_cursor,
        window_start=intent.window_start,
        window_hash=intent.window_hash,
        vertex_path=None if intent.vertex_path is None else str(intent.vertex_path),
    )


def _dispatch_status(
    committed: TierCommitted, *, dispatcher_requested: bool
) -> str:
    if not committed.dispatch_intents:
        return "none"
    if committed.dispatch_succeeded is True:
        return "succeeded"
    if committed.dispatch_succeeded is False:
        return "failed"
    return "withheld" if dispatcher_requested else "not-requested"


def _plan_ids(plan: BatchWritePlan | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if plan is None:
        return (), ()
    facts = tuple(item.fact_id for item in plan.items)
    ticks = plan.pending_tick_ids + tuple(
        item.tick_id for item in plan.items if item.tick_id is not None
    )
    return facts, ticks


def _unplanned_fact_ids(
    result: SourceInvocationResult, tier: CollectedTier
) -> tuple[str, ...]:
    ids = tuple(
        identifier
        for source in tier.sources
        for identifier in (*source.fact_ids, source.lifecycle_id)
    )
    last_index = len(result.plan.tiers or ((),)) - 1
    if tier.tier_index == last_index:
        ids = (*ids, result.overall_sync_id)
    return ids


def _committed_outcome(committed: TierCommitted) -> str:
    if not committed.witnessed:
        return "committed-unwitnessed"
    if committed.outcome.projection.value == "failed":
        return "committed-projection-failed"
    if committed.dispatch_succeeded is False:
        return "dispatch-failed"
    return "committed"


def _tier_result(
    result: SourceInvocationResult,
    collected: CollectedTier,
    *,
    dispatcher_requested: bool,
) -> SourceTierResult:
    committed = next(
        (
            item
            for item in result.durable_tiers
            if item.tier_index == collected.tier_index
        ),
        None,
    )
    plan = (
        committed.plan
        if committed is not None
        else result.terminal_plan
        if result.terminal_tier is collected
        else None
    )
    fact_ids, tick_ids = _plan_ids(plan)
    if not fact_ids:
        fact_ids = _unplanned_fact_ids(result, collected)
    pending_tick_ids = () if plan is None else plan.pending_tick_ids
    sources = tuple(_collected_source(source) for source in collected.sources)
    lifecycle_ids = tuple(source.lifecycle_id for source in collected.sources)
    if committed is not None:
        dispatches = tuple(
            _dispatch_result(intent, committed) for intent in committed.dispatch_intents
        )
        return SourceTierResult(
            tier_index=collected.tier_index,
            outcome=_committed_outcome(committed),
            basis=collected.basis,
            sources=sources,
            fact_ids=fact_ids,
            tick_ids=tick_ids,
            pending_tick_ids=pending_tick_ids,
            lifecycle_ids=lifecycle_ids,
            commit=committed.commit,
            witnessed=committed.witnessed,
            projection=committed.outcome.projection.value,
            dispatch_status=_dispatch_status(
                committed, dispatcher_requested=dispatcher_requested
            ),
            dispatches=dispatches,
        )
    return SourceTierResult(
        tier_index=collected.tier_index,
        outcome=("unknown" if result.collected_unknown is collected else "uncommitted"),
        basis=collected.basis,
        sources=sources,
        fact_ids=fact_ids,
        tick_ids=tick_ids,
        pending_tick_ids=pending_tick_ids,
        lifecycle_ids=lifecycle_ids,
    )


def _safe_detail(value: Any) -> Any | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return list(value)
    if all(hasattr(value, name) for name in ("lineage", "ordinal", "record_hash")):
        return {
            "lineage": value.lineage,
            "ordinal": value.ordinal,
            "record_hash": value.record_hash,
        }
    if all(
        hasattr(value, name)
        for name in ("lineage", "captured_head", "projected_through", "view_generation")
    ):
        return {
            "lineage": value.lineage,
            "captured_head": _safe_detail(value.captured_head),
            "projected_through": _safe_detail(value.projected_through),
            "view_generation": value.view_generation,
        }
    return None


def _terminal_result(exc: BaseException | None) -> SourceTerminalResult | None:
    if exc is None:
        return None
    category = "failed"
    if isinstance(exc, SourceTierCollectionFailed):
        category = "collection-failed"
    elif isinstance(exc, BatchWriteCommitUnknown):
        category = "unknown"
    elif isinstance(exc, NotWitnessed):
        category = "committed-unwitnessed" if exc.commit is not None else "unwitnessed"
    elif isinstance(exc, BatchPostCommitProjectionFailed):
        category = "committed-projection-failed"
    elif isinstance(exc, DispatchFailed):
        category = "dispatch-failed"
    elif isinstance(exc, DeclarationChangedDuringInvocation):
        category = "declaration-changed"
    elif isinstance(exc, SourceTierPreparationRefused):
        if isinstance(exc.cause, InvalidSourceOutput):
            category = "invalid-output"
        elif isinstance(exc.cause, BatchWritePreparationRefused) and exc.cause.admission_refused:
            category = "admission-refused"
        else:
            category = "refused"

    cause = getattr(exc, "cause", None)
    details: dict[str, Any] = {}
    if isinstance(exc, SourceTierCollectionFailed):
        def partial_source(source: PartialCollectedSource) -> dict[str, Any]:
            return SourceCollectedResult(
                source_index=source.source_index,
                kind=source.kind,
                command=source.command,
                source_observer=source.source_observer,
                facts=tuple(_source_fact(fact, identifier) for fact, identifier in source.pairs),
                status=source.phase,
                error_type=source.error_type,
                error_message=source.error_message,
            ).as_dict()

        details["collection"] = {
            "tier_index": exc.tier_index,
            "basis": _safe_detail(exc.basis),
            "custody": "not-attempted",
            "completed_sources": [
                _collected_source(source).as_dict() for source in exc.completed_sources
            ],
            "failed_sources": [partial_source(source) for source in exc.failed_sources],
            "cancelled_sources": [partial_source(source) for source in exc.cancelled_sources],
        }
    for name in (
        "captured_head",
        "head",
        "initial_basis",
        "observed_basis",
        "source_index",
        "value_type",
        "item_index",
        "fact_ids",
        "tick_ids",
        "tick_names",
        "commands",
    ):
        value = getattr(exc, name, None)
        safe = _safe_detail(value)
        if safe is not None:
            details[name] = safe
    if cause is not None:
        details["cause_type"] = type(cause).__name__
        for source_name, public_name in (
            ("input_index", "item_index"),
            ("source_index", "source_index"),
            ("value_type", "value_type"),
        ):
            safe = _safe_detail(getattr(cause, source_name, None))
            if safe is not None:
                details[public_name] = safe
        if isinstance(cause, BatchWritePreparationRefused):
            details["admission_refused"] = cause.admission_refused
            details["observer"] = cause.item.fact.observer
            details["kind"] = cause.item.fact.kind
    commit = getattr(exc, "commit", None)
    if commit is not None:
        from .types import _commit_dict

        details["commit"] = _commit_dict(commit)
    return SourceTerminalResult(
        category=category,
        source_type=type(exc).__name__,
        message=str(exc),
        cause_type=None if cause is None else type(cause).__name__,
        details=details,
    )


def _sdk_result(
    target_path: Path,
    store: StoreDescriptorInfo,
    result: SourceInvocationResult,
    *,
    dispatcher_requested: bool,
) -> SourceRunResult:
    cadence = tuple(
        SourceCadenceResult(
            source_index=item.source_index,
            kind=item.kind,
            mode=item.mode,
            evaluated_at=item.evaluated_at,
            latest_success_id=item.latest_success_id,
            latest_success_ts=item.latest_success_ts,
            trigger_fact_ids=item.trigger_fact_ids,
            interval_seconds=item.interval_seconds,
            forced=item.forced,
            qualified=item.qualified,
        )
        for item in result.plan.cadence
    )
    tiers = tuple(
        _tier_result(result, tier, dispatcher_requested=dispatcher_requested)
        for tier in result.collected_tiers
    )
    tier_by_index = {tier.tier_index: tier for tier in tiers}
    known_uncommitted = (
        None
        if result.collected_uncommitted is None
        else tier_by_index[result.collected_uncommitted.tier_index]
    )
    unknown = (
        None
        if result.collected_unknown is None
        else tier_by_index[result.collected_unknown.tier_index]
    )
    return SourceRunResult(
        store=store,
        target_path=str(target_path),
        invocation_id=result.invocation_id,
        status=result.status,
        initial_basis=result.plan.initial_capture.basis,
        bases=result.bases,
        cadence=cadence,
        tier_decisions=result.plan.tiers,
        tiers=tiers,
        known_uncommitted=known_uncommitted,
        unknown=unknown,
        error_lifecycle_ids=result.error_lifecycle_ids,
        durable_error_lifecycle_ids=result.durable_error_lifecycle_ids,
        overall_sync_id=result.overall_sync_id,
        terminal=_terminal_result(result.terminal),
    )


def _raise_preparation(exc: BaseException) -> None:
    normalized = normalize_exception(exc)
    if normalized is not exc:
        raise normalized from exc
    details: dict[str, Any] = {"phase": "source-preparation"}
    cause = getattr(exc, "cause", None)
    if cause is not None:
        details["cause_type"] = type(cause).__name__
    raise ArrivalRefusal(
        str(exc), source_type=type(exc).__name__, details=details
    ) from exc


async def run_sources(
    target: Path | str,
    *,
    observer: str,
    force: bool = False,
    credentials: CredentialProvider | None = None,
    registry: BackendRegistry | None = None,
    collector_factory: CollectorFactory | None = None,
    dispatcher: RunDispatcher | None = None,
    evaluated_at: float | None = None,
) -> SourceRunResult:
    """Collect and tier-atomically commit one explicit Arrival source invocation."""
    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is None:
        _refuse_arrival_aggregate_members(target_path)
        raise TargetUnsupported(
            "run_sources requires a single-store Arrival Authority .vertex target"
        )
    _path, locator, descriptor = arrival
    if descriptor.role is not Profile.AUTHORITY:
        raise ArrivalRefusal(
            "source execution requires an Authority descriptor role",
            source_type="NotAuthority",
            details={"phase": "source-preparation"},
        )
    active_registry = registry or BackendRegistry.with_builtin_backends()
    provider = credentials or CustodyCredentialProvider()
    try:
        write_credentials = provider.for_write(target_path)
        invocation = prepare_source_invocation(
            active_registry,
            descriptor,
            locator,
            observer=observer,
            credentials=write_credentials,
            force=force,
            evaluated_at=evaluated_at,
        )
    except SdkError:
        raise
    except SourcePreparationRefused as exc:
        _raise_preparation(exc.cause)
    except Exception as exc:
        _raise_preparation(exc)
    result = await execute_source_invocation(
        active_registry,
        descriptor,
        locator,
        invocation,
        credentials=write_credentials,
        collector_factory=collector_factory,
        dispatcher=dispatcher,
    )
    return _sdk_result(
        target_path,
        StoreDescriptorInfo.from_descriptor(descriptor),
        result,
        dispatcher_requested=dispatcher is not None,
    )
