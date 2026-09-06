"""SDK types, models, and exceptions for the Loops composition library."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from typing import Any

from engine.arrival_contract import Commit, Continuation, Head, ReadBasis, StoreDescriptor


def _as_serializable(value: Any) -> Any:
    """Turn nested aggregate evidence values into JSON-shaped SDK output."""
    if hasattr(value, "__dataclass_fields__"):
        return _as_serializable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _as_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_serializable(item) for item in value]
    return value

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SdkError(Exception):
    """Base exception for all high-level SDK operations."""


class TargetError(SdkError):
    """Target resolution or probe error."""


class TargetNotFound(TargetError):
    """The requested target path does not exist."""


class TargetUnsupported(TargetError):
    """The target exists but is not a recognized loops artifact."""


class TargetNotWritable(TargetError):
    """The target or its store is not writable for the requested operation."""


class AdmissionFailed(SdkError):
    """Declared admission policy rejected the operation."""

    def __init__(
        self,
        message: str,
        *,
        observer: str | None = None,
        kind: str | None = None,
        vertex: str | None = None,
    ) -> None:
        super().__init__(message)
        self.observer = observer
        self.kind = kind
        self.vertex = vertex


class EmissionFailed(SdkError):
    """Fact emission failed before committing to the store."""


class SdkValueError(SdkError, ValueError):
    """Invalid input parameter or missing required argument for an SDK operation."""


class InvalidEmissionRequest(SdkValueError, EmissionFailed):
    """Invalid parameters supplied for fact emission (e.g. missing observer)."""


class LegacyBatchPartialFailure(EmissionFailed):
    """A sequential legacy batch failed after storing an observable prefix."""

    outcome = "legacy-partial"

    def __init__(
        self,
        message: str,
        *,
        failed_index: int,
        items: list[EmitReceipt],
        cause: BaseException,
        committed_fact_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failed_index = failed_index
        self.items = tuple(items)
        self.cause = cause
        self.committed_fact_id = committed_fact_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "loops.sdk/error/v1",
            "type": type(self).__name__,
            "message": str(self),
            "outcome": self.outcome,
            "failed_index": self.failed_index,
            "items": [item.as_dict() for item in self.items],
            "committed_fact_id": self.committed_fact_id,
            "cause_type": type(self.cause).__name__,
        }


class CommittedEmissionError(EmissionFailed):
    """The fact was successfully committed to the canonical store, but a
    compound post-commit operation (e.g. tick computation or index sync) failed.

    The fact ID is preserved so callers know not to blindly retry.
    """

    def __init__(self, message: str, *, fact_id: str) -> None:
        super().__init__(message)
        self.fact_id = fact_id


class CeremonyFailed(SdkError):
    """Declaration update ceremony failed."""


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoreDescriptorInfo:
    """Serializable store identity for descriptor-first SDK operations."""

    backend: str
    location: str
    lineage: str | None = None
    role: str | None = None
    query: str | None = None
    witness: str | None = None

    @classmethod
    def from_descriptor(cls, descriptor: StoreDescriptor) -> StoreDescriptorInfo:
        return cls(
            backend=descriptor.backend,
            location=descriptor.location,
            lineage=descriptor.lineage,
            role=descriptor.role.value if descriptor.role is not None else None,
            query=descriptor.query,
            witness=descriptor.witness,
        )


@dataclass(frozen=True)
class ArrivalTarget:
    """A vertex target resolved to the descriptor its named adapter opens."""

    schema: str = "loops.sdk/arrival-target/v1"
    target_path: str = ""
    vertex_name: str = ""
    store: StoreDescriptorInfo | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReadSummary:
    """Statistical summary of a target artifact (inventory view)."""

    schema: str = "loops.sdk/read-summary/v2"
    read_path: str = "legacy"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    target_type: str = ""
    target_path: str = ""
    canonical_mode: str | None = None
    canonical_path: str | None = None
    index_path: str | None = None
    fact_total: int = 0
    tick_total: int = 0
    latest_ts: float | None = None
    kinds: dict[str, dict[str, Any]] = field(default_factory=dict)
    ticks: dict[str, Any] = field(default_factory=dict)
    agreement: bool | None = None
    declaration_status: str | None = None
    unfolded_kinds: list[str] = field(default_factory=list)
    signed_count: int | None = None
    unsigned_count: int | None = None
    aggregate_members: list[dict[str, Any]] = field(default_factory=list)
    aggregate_definitions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.latest_ts is not None:
            d["latest_iso"] = datetime.fromtimestamp(self.latest_ts, tz=UTC).isoformat()
        return d


@dataclass(frozen=True)
class FactPageResult:
    """Bounded, cursor-bearing page of facts."""

    schema: str = "loops.sdk/facts-page/v2"
    read_path: str = "legacy"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: str | Continuation | None = None
    prev_cursor: str | Continuation | None = None
    truncated: bool = False
    order: str = "newest"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # Engine Continuation is deliberately an in-memory value, not a wire
        # token. Never make an unprotected, non-round-trippable token appear in
        # the SDK's process-boundary serialization.
        result["has_continuation"] = isinstance(self.next_cursor, Continuation)
        if isinstance(self.next_cursor, Continuation):
            result["next_cursor"] = None
        if isinstance(self.prev_cursor, Continuation):
            result["prev_cursor"] = None
        return result


@dataclass(frozen=True)
class FoldStateResult:
    """Declared folded state of a vertex."""

    schema: str = "loops.sdk/fold-state/v2"
    read_path: str = "legacy"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    vertex_name: str = ""
    target_path: str = ""
    declaration_status: str = ""
    generation: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, Any] = field(default_factory=dict)
    aggregate_members: list[dict[str, Any]] = field(default_factory=list)
    aggregate_definitions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TickReadResult:
    """Ticks returned from one read path and, for Arrival, one read basis."""

    schema: str = "loops.sdk/tick-read/v1"
    read_path: str = "legacy"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    items: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FactLookupResult:
    """An exact fact lookup that retains its basis even when no fact matched."""

    schema: str = "loops.sdk/fact-lookup/v1"
    read_path: str = "legacy"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    fact: dict[str, Any] | None = None

    @property
    def found(self) -> bool:
        return self.fact is not None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["found"] = self.found
        return result


def _commit_dict(commit: Commit | None) -> dict[str, Any] | None:
    """Serialize commit identity without copying backend record bodies."""
    if commit is None:
        return None
    return {
        "before": asdict(commit.before),
        "after": asdict(commit.after),
        "record_count": len(commit.records),
        "durability": {
            "profile": commit.durability.profile.value,
            "mechanism": commit.durability.mechanism,
        },
    }


def _payload_issues(value: Any, path: str = "$") -> list[dict[str, str]]:
    """Describe values json cannot encode without replacing them with repr/str."""
    if value is None or isinstance(value, (str, int, bool)):
        return []
    if isinstance(value, float):
        return [] if math.isfinite(value) else [
            {"path": path, "type": "float", "issue": "non-finite"}
        ]
    if isinstance(value, Mapping):
        issues: list[dict[str, str]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                issues.append({"path": path, "type": type(key).__name__})
                continue
            issues.extend(_payload_issues(item, f"{path}.{key}"))
        return issues
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        issues = []
        for index, item in enumerate(value):
            issues.extend(_payload_issues(item, f"{path}[{index}]"))
        return issues
    return [{"path": path, "type": type(value).__name__}]


def _payload_dict(value: Any) -> tuple[Any | None, bool, list[dict[str, str]]]:
    """Return exact JSON-shaped payload plus typed shape/encoding evidence."""
    issues = []
    if not isinstance(value, Mapping):
        issues.append(
            {"path": "$", "type": type(value).__name__, "issue": "expected-object"}
        )
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        issues.extend(_payload_issues(value))
        return None, False, issues
    return decoded, True, issues


def _wire_float(value: Any, field_name: str) -> tuple[float | None, list[dict[str, str]]]:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value), []
    return None, [
        {"field": field_name, "type": type(value).__name__, "issue": "non-finite"}
    ]


@dataclass(frozen=True)
class EmitReceipt:
    """Persisted receipt for an emitted fact or dry-run simulation."""

    schema: str = "loops.sdk/emit-receipt/v2"
    write_path: str = "legacy"
    store: StoreDescriptorInfo | None = None
    id: str = ""
    stored: bool = True
    signed: bool | None = None
    observer: str = ""
    tick_mark: str | None = None
    tick_id: str | None = None
    state_change: bool | None = False
    affected_sections: list[str] = field(default_factory=list)
    delta_count: int | None = 0
    predicted_state_change: bool = False
    captured_head: Head | None = None
    commit: Commit | None = None
    witnessed: bool | None = None
    projection: str | None = None

    def as_dict(self) -> dict[str, Any]:
        # Do not call asdict on the full Commit: third-party backend record
        # mappings need not support deepcopy, and record bodies are not part
        # of this process receipt's identity contract.
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        result["store"] = None if self.store is None else asdict(self.store)
        result["affected_sections"] = list(self.affected_sections)
        result["captured_head"] = None if self.captured_head is None else asdict(self.captured_head)
        result["commit"] = _commit_dict(self.commit)
        return result


@dataclass(frozen=True)
class BatchEmitResult:
    """Receipts and shared custody evidence for one SDK batch request."""

    schema: str = "loops.sdk/batch-emit/v2"
    write_path: str = "legacy"
    store: StoreDescriptorInfo | None = None
    items: list[EmitReceipt] = field(default_factory=list)
    atomic: bool = False
    atomicity: str = "legacy-sequential"
    captured_head: Head | None = None
    commit: Commit | None = None
    witnessed: bool | None = None
    projection: str | None = None

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> EmitReceipt:
        return self.items[index]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "write_path": self.write_path,
            "store": None if self.store is None else asdict(self.store),
            "items": [item.as_dict() for item in self.items],
            "item_count": len(self.items),
            "stored_count": sum(item.stored for item in self.items),
            "atomic": self.atomic,
            "atomicity": self.atomicity,
            "captured_head": (None if self.captured_head is None else asdict(self.captured_head)),
            "commit": _commit_dict(self.commit),
            "witnessed": self.witnessed,
            "projection": self.projection,
        }


@dataclass(frozen=True)
class SourceFactResult:
    """One exact collected fact identity and body retained for reconciliation."""

    id: str = ""
    kind: str = ""
    ts: float = 0.0
    observer: str = ""
    origin: str = ""
    payload: Any = field(default_factory=dict)
    payload_snapshot: bool = True

    def as_dict(self) -> dict[str, Any]:
        payload, serializable, payload_issues = _payload_dict(self.payload)
        ts, envelope_issues = _wire_float(self.ts, "ts")
        result: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "ts": ts,
            "observer": self.observer,
            "origin": self.origin,
            "payload": payload,
            "payload_type": type(self.payload).__name__,
            "payload_serializable": serializable,
            "payload_valid_object": isinstance(self.payload, Mapping),
            "payload_snapshot": self.payload_snapshot,
        }
        if payload_issues:
            result["payload_issues"] = payload_issues
        if envelope_issues:
            result["envelope_issues"] = envelope_issues
        return result


@dataclass(frozen=True)
class SourceCadenceResult:
    """Serializable evidence for one source qualification decision."""

    source_index: int = 0
    kind: str = ""
    mode: str = ""
    evaluated_at: float = 0.0
    latest_success_id: str | None = None
    latest_success_ts: float | None = None
    trigger_fact_ids: tuple[str, ...] = ()
    interval_seconds: float | None = None
    forced: bool = False
    qualified: bool = False

    def as_dict(self) -> dict[str, Any]:
        evaluated_at, evaluated_issues = _wire_float(
            self.evaluated_at, "evaluated_at"
        )
        latest, latest_issues = (
            (None, [])
            if self.latest_success_ts is None
            else _wire_float(self.latest_success_ts, "latest_success_ts")
        )
        interval, interval_issues = (
            (None, [])
            if self.interval_seconds is None
            else _wire_float(self.interval_seconds, "interval_seconds")
        )
        return {
            "source_index": self.source_index,
            "kind": self.kind,
            "mode": self.mode,
            "evaluated_at": evaluated_at,
            "latest_success_id": self.latest_success_id,
            "latest_success_ts": latest,
            "trigger_fact_ids": list(self.trigger_fact_ids),
            "interval_seconds": interval,
            "forced": self.forced,
            "qualified": self.qualified,
            "value_issues": [
                *evaluated_issues,
                *latest_issues,
                *interval_issues,
            ],
        }


@dataclass(frozen=True)
class SourceCollectedResult:
    """One collector attempt, its exact yielded facts, and lifecycle identity."""

    source_index: int = 0
    kind: str = ""
    command: str = ""
    source_observer: str = ""
    facts: tuple[SourceFactResult, ...] = ()
    lifecycle_fact: SourceFactResult | None = None
    lifecycle_id: str = ""
    status: str = "ok"
    attempt_count: int = 1
    stderr: str = ""
    returncode: int | None = None
    error_type: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_index": self.source_index,
            "kind": self.kind,
            "command": self.command,
            "source_observer": self.source_observer,
            "facts": [fact.as_dict() for fact in self.facts],
            "lifecycle_fact": (
                None if self.lifecycle_fact is None else self.lifecycle_fact.as_dict()
            ),
            "lifecycle_id": self.lifecycle_id,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class SourceDispatchResult:
    """A frozen tick run intent and whether this invocation attempted it."""

    tick_id: str = ""
    tick_name: str = ""
    command: str = ""
    attempted: bool = False
    succeeded: bool | None = None
    ts: float = 0.0
    since: float | None = None
    origin: str = ""
    payload_text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    fact_cursor: str | None = None
    window_start: str | None = None
    window_hash: str | None = None
    vertex_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload, serializable, issues = _payload_dict(self.payload)
        ts, ts_issues = _wire_float(self.ts, "ts")
        since, since_issues = (
            (None, [])
            if self.since is None
            else _wire_float(self.since, "since")
        )
        result: dict[str, Any] = {
            "tick_id": self.tick_id,
            "tick_name": self.tick_name,
            "command": self.command,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "ts": ts,
            "since": since,
            "origin": self.origin,
            "payload_text": self.payload_text,
            "payload": payload,
            "payload_serializable": serializable,
            "fact_cursor": self.fact_cursor,
            "window_start": self.window_start,
            "window_hash": self.window_hash,
            "vertex_path": self.vertex_path,
        }
        if issues:
            result["payload_issues"] = issues
        if ts_issues or since_issues:
            result["envelope_issues"] = [*ts_issues, *since_issues]
        return result


@dataclass(frozen=True)
class SourceTierResult:
    """Collected and custody evidence for one dependency tier."""

    tier_index: int = 0
    outcome: str = "uncommitted"
    basis: ReadBasis | None = None
    sources: tuple[SourceCollectedResult, ...] = ()
    fact_ids: tuple[str, ...] = ()
    tick_ids: tuple[str, ...] = ()
    pending_tick_ids: tuple[str, ...] = ()
    lifecycle_ids: tuple[str, ...] = ()
    commit: Commit | None = None
    witnessed: bool | None = None
    projection: str | None = None
    dispatch_status: str = "none"
    dispatches: tuple[SourceDispatchResult, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier_index": self.tier_index,
            "outcome": self.outcome,
            "basis": None if self.basis is None else asdict(self.basis),
            "sources": [source.as_dict() for source in self.sources],
            "fact_ids": list(self.fact_ids),
            "tick_ids": list(self.tick_ids),
            "pending_tick_ids": list(self.pending_tick_ids),
            "lifecycle_ids": list(self.lifecycle_ids),
            "commit": _commit_dict(self.commit),
            "witnessed": self.witnessed,
            "projection": self.projection,
            "dispatch_status": self.dispatch_status,
            "dispatches": [dispatch.as_dict() for dispatch in self.dispatches],
        }


@dataclass(frozen=True)
class SourceTerminalResult:
    """Whitelisted terminal evidence for an interrupted source invocation."""

    category: str = "failed"
    source_type: str = ""
    message: str = ""
    cause_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "source_type": self.source_type,
            "message": self.message,
            "cause_type": self.cause_type,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SourceRunResult:
    """Serializable outcome of one captured Arrival source invocation."""

    schema: str = "loops.sdk/source-run/v1"
    write_path: str = "arrival"
    store: StoreDescriptorInfo | None = None
    target_path: str = ""
    invocation_id: str = ""
    status: str = "incomplete"
    initial_basis: ReadBasis | None = None
    bases: tuple[ReadBasis, ...] = ()
    cadence: tuple[SourceCadenceResult, ...] = ()
    tier_decisions: tuple[tuple[int, ...], ...] = ()
    tiers: tuple[SourceTierResult, ...] = ()
    known_uncommitted: SourceTierResult | None = None
    unknown: SourceTierResult | None = None
    error_lifecycle_ids: tuple[str, ...] = ()
    durable_error_lifecycle_ids: tuple[str, ...] = ()
    overall_sync_id: str = ""
    terminal: SourceTerminalResult | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "write_path": self.write_path,
            "store": None if self.store is None else asdict(self.store),
            "target_path": self.target_path,
            "invocation_id": self.invocation_id,
            "status": self.status,
            "initial_basis": (
                None if self.initial_basis is None else asdict(self.initial_basis)
            ),
            "bases": [asdict(basis) for basis in self.bases],
            "cadence": [evidence.as_dict() for evidence in self.cadence],
            "tier_decisions": [list(tier) for tier in self.tier_decisions],
            "tiers": [tier.as_dict() for tier in self.tiers],
            "known_uncommitted": (
                None if self.known_uncommitted is None else self.known_uncommitted.as_dict()
            ),
            "unknown": None if self.unknown is None else self.unknown.as_dict(),
            "error_lifecycle_ids": list(self.error_lifecycle_ids),
            "durable_error_lifecycle_ids": list(self.durable_error_lifecycle_ids),
            "overall_sync_id": self.overall_sync_id,
            "terminal": None if self.terminal is None else self.terminal.as_dict(),
        }


@dataclass(frozen=True)
class EmitPreviewResult:
    """Preflight simulation of an emission request."""

    schema: str = "loops.sdk/emit-preview/v2"
    read_path: str = "legacy"
    store: StoreDescriptorInfo | None = None
    captured_head: Head | None = None
    target: str = ""
    kind: str = ""
    observer: str = ""
    origin: str = ""
    ts: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)
    kind_declared: bool = False
    fold_key_field: str | None = None
    fold_key_present: bool = True
    fold_key_value: Any | None = None
    admitted: bool = True
    reason: str | None = None
    strict: bool = False
    would_store: bool = True
    would_fold: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EntityResolutionResult:
    """One entity lookup result, with Arrival read basis when available."""

    schema: str = "loops.sdk/entity-resolution/v1"
    found: bool = False
    fact_id: str | None = None
    address: dict[str, Any] = field(default_factory=dict)
    read_path: str = "legacy"
    store: StoreDescriptorInfo | None = None
    basis: Any | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResultItem:
    """Individual match within a full-text search query."""

    id: str
    kind: str
    ts: float
    observer: str
    origin: str
    payload: dict[str, Any]
    rank: float = 0.0
    snippet: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    """Full-text search result with Arrival corpus evidence when available."""

    schema: str = "loops.sdk/search-result/v2"
    read_path: str = "legacy"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    query: str = ""
    matches: list[SearchResultItem] = field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False
    ranking: str | None = None
    ranking_through: Head | None = None
    fields_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "read_path": self.read_path,
            "basis": asdict(self.basis) if self.basis is not None else None,
            "store": asdict(self.store) if self.store is not None else None,
            "query": self.query,
            "matches": [m.as_dict() for m in self.matches],
            "total_matches": self.total_matches,
            "truncated": self.truncated,
            "ranking": self.ranking,
            "ranking_through": (
                asdict(self.ranking_through) if self.ranking_through is not None else None
            ),
            "fields_hash": self.fields_hash,
        }


@dataclass(frozen=True)
class SearchIndexResult:
    """Evidence from explicit Arrival full-prefix FTS maintenance."""

    schema: str = "loops.sdk/search-index/v1"
    read_path: str = "arrival"
    store: StoreDescriptorInfo | None = None
    basis: ReadBasis | None = None
    coordinator_captured_head: Head | None = None
    target: Head | None = None
    coverage_before: dict[str, Any] | None = None
    coverage_after: dict[str, Any] | None = None
    changed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "read_path": self.read_path,
            "store": asdict(self.store) if self.store is not None else None,
            "basis": asdict(self.basis) if self.basis is not None else None,
            "coordinator_captured_head": (
                asdict(self.coordinator_captured_head)
                if self.coordinator_captured_head is not None
                else None
            ),
            "target": asdict(self.target) if self.target is not None else None,
            "coverage_before": self.coverage_before,
            "coverage_after": self.coverage_after,
            "changed": self.changed,
        }


@dataclass(frozen=True)
class TimelineEvent:
    """Chronological event (fact or tick) in an interleaved timeline stream."""

    event_type: str = "fact"
    id: str = ""
    kind_or_name: str = ""
    ts: float = 0.0
    observer: str = ""
    origin: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TimelineResult:
    """Interleaved chronological stream of facts and tick seals."""

    schema: str = "loops.sdk/timeline-result/v2"
    read_path: str = "legacy"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    events: list[TimelineEvent] = field(default_factory=list)
    start_ts: float | None = None
    end_ts: float | None = None
    total_events: int = 0
    truncated: bool = False
    order: str = "oldest"
    aggregate_members: list[dict[str, Any]] = field(default_factory=list)
    aggregate_definitions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "read_path": self.read_path,
            "basis": asdict(self.basis) if self.basis is not None else None,
            "store": asdict(self.store) if self.store is not None else None,
            "events": [e.as_dict() for e in self.events],
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "total_events": self.total_events,
            "truncated": self.truncated,
            "order": self.order,
            "aggregate_members": _as_serializable(self.aggregate_members),
            "aggregate_definitions": _as_serializable(self.aggregate_definitions),
        }


@dataclass(frozen=True)
class SyncResult:
    """Result of one explicit derived-projection synchronization."""

    schema: str = "loops.sdk/sync-result/v2"
    read_path: str = "legacy"
    store: StoreDescriptorInfo | None = None
    target_path: str = ""
    status: str = "synced"
    captured_head: Head | None = None
    target: Head | None = None
    projected_before: Head | None = None
    projected_after: Head | None = None
    view_generation: str | None = None
    changed: bool | None = None
    rebuilt: bool = False
    indexed_facts: int | None = 0
    agreement: bool | None = True
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerifyResult:
    """One Full custody-prefix verification result."""

    schema: str = "loops.sdk/verify-result/v1"
    store: StoreDescriptorInfo | None = None
    captured_head: Head | None = None
    verified_through: Head | None = None
    level: str = "full"
    claims: tuple[str, ...] = ("grammar", "density", "lineage", "hash-chain")
    excludes: tuple[str, ...] = ("signature-authorship", "external-key-trust", "projection")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KindMutationResult:
    """Result of a declaration update / kind mutation ceremony."""

    schema: str = "loops.sdk/kind-mutation/v1"
    status: str = ""
    reason: str = ""
    mode: str = ""
    vertex_path: str = ""
    generation_before: dict[str, Any] | None = None
    generation_after: dict[str, Any] | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    file_written: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InitVertexResult:
    """Outcome of legacy scaffolding or registry-backed Arrival bootstrap.

    Arrival initialization fills ``lineage``, ``head`` and ``phase``;
    aggregate and legacy scaffolding leaves those optional fields empty.
    """

    schema: str = "loops.sdk/init-vertex/v2"
    read_path: str = "legacy"
    store: StoreDescriptorInfo | None = None
    target_path: str = ""
    name: str = ""
    store_path: str | None = None
    store_type: str = "sqlite"
    is_root: bool = False
    file_written: bool = True
    lineage: str | None = None
    head: dict[str, Any] | None = None
    phase: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeclarationInspectionResult:
    """Root declaration evidence without aggregate-member capture.

    An Arrival result has one root ``basis`` only; unexpanded combine/discover
    fields describe that captured effective root and never assert member
    custody. ``read_path="local-frozen"`` has no adopted store or basis and
    reports the one parsed storeless aggregate definition instead.
    """

    schema: str = "loops.sdk/declaration-inspection/v2"
    read_path: str = "legacy"
    store: StoreDescriptorInfo | None = None
    basis: ReadBasis | None = None
    target_path: str = ""
    name: str = ""
    status: str = ""
    local_status: str | None = None
    effective_status: str | None = None
    local_fingerprint: str | None = None
    effective_fingerprint: str | None = None
    store_mode: str | None = None
    store_path: str | None = None
    declared_kinds: list[str] = field(default_factory=list)
    declared_observers: list[str] = field(default_factory=list)
    cadence_ticks: list[str] = field(default_factory=list)
    strict: bool = False
    is_aggregate: bool = False
    syntax_valid: bool = True
    errors: list[str] = field(default_factory=list)
    local_combine: list[dict[str, str | None]] | None = None
    local_discover: str | None = None
    effective_combine: list[dict[str, str | None]] | None = None
    effective_discover: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeclarationPlanResult:
    """Dry-run preview of a proposed declaration update ceremony."""

    schema: str = "loops.sdk/declaration-plan/v1"
    applicable: bool = True
    reason: str = ""
    mode: str = ""
    vertex_path: str = ""
    generation_before: dict[str, Any] | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
