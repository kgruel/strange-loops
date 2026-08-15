"""SDK types, models, and exceptions for the Loops composition library."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

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
class ReadSummary:
    """Statistical summary of a target artifact (inventory view)."""

    schema: str = "loops.sdk/read-summary/v1"
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

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.latest_ts is not None:
            d["latest_iso"] = datetime.fromtimestamp(self.latest_ts, tz=UTC).isoformat()
        return d


@dataclass(frozen=True)
class FactPageResult:
    """Bounded, cursor-bearing page of facts."""

    schema: str = "loops.sdk/facts-page/v1"
    items: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: str | None = None
    prev_cursor: str | None = None
    truncated: bool = False
    order: str = "newest"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FoldStateResult:
    """Declared folded state of a vertex."""

    schema: str = "loops.sdk/fold-state/v1"
    vertex_name: str = ""
    target_path: str = ""
    declaration_status: str = ""
    generation: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmitReceipt:
    """Persisted receipt for an emitted fact or dry-run simulation."""

    schema: str = "loops.sdk/emit-receipt/v1"
    id: str = ""
    stored: bool = True
    signed: bool | None = None
    observer: str = ""
    tick_mark: str | None = None
    tick_id: str | None = None
    state_change: bool = False
    affected_sections: list[str] = field(default_factory=list)
    delta_count: int = 0
    predicted_state_change: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmitPreviewResult:
    """Preflight simulation of an emission request."""

    schema: str = "loops.sdk/emit-preview/v1"
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
    """Full-text search query result."""

    schema: str = "loops.sdk/search-result/v1"
    query: str = ""
    matches: list[SearchResultItem] = field(default_factory=list)
    total_matches: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "query": self.query,
            "matches": [m.as_dict() for m in self.matches],
            "total_matches": self.total_matches,
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

    schema: str = "loops.sdk/timeline-result/v1"
    events: list[TimelineEvent] = field(default_factory=list)
    start_ts: float | None = None
    end_ts: float | None = None
    total_events: int = 0
    truncated: bool = False
    order: str = "oldest"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "events": [e.as_dict() for e in self.events],
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "total_events": self.total_events,
            "truncated": self.truncated,
            "order": self.order,
        }


@dataclass(frozen=True)
class SyncResult:
    """Result of an index synchronization or reindex operation."""

    schema: str = "loops.sdk/sync-result/v1"
    target_path: str = ""
    status: str = "synced"
    indexed_facts: int = 0
    agreement: bool = True
    duration_ms: float = 0.0

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
    """Outcome of vertex scaffolding operation."""

    schema: str = "loops.sdk/init-vertex/v1"
    target_path: str = ""
    name: str = ""
    store_path: str | None = None
    store_type: str = "sqlite"
    is_root: bool = False
    file_written: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeclarationInspectionResult:
    """Deep structural inspection of a .vertex file."""

    schema: str = "loops.sdk/declaration-inspection/v1"
    target_path: str = ""
    name: str = ""
    status: str = ""
    store_mode: str | None = None
    store_path: str | None = None
    declared_kinds: list[str] = field(default_factory=list)
    declared_observers: list[str] = field(default_factory=list)
    cadence_ticks: list[str] = field(default_factory=list)
    strict: bool = False
    is_aggregate: bool = False
    syntax_valid: bool = True
    errors: list[str] = field(default_factory=list)

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
