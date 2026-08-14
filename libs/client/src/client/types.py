"""Client types, models, and exceptions for the Loops composition library."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ClientError(Exception):
    """Base exception for all high-level client operations."""


class TargetError(ClientError):
    """Target resolution or probe error."""


class TargetNotFound(TargetError):
    """The requested target path does not exist."""


class TargetUnsupported(TargetError):
    """The target exists but is not a recognized loops artifact."""


class TargetNotWritable(TargetError):
    """The target or its store is not writable for the requested operation."""


class AdmissionFailed(ClientError):
    """Declared admission policy rejected the operation."""


class EmissionFailed(ClientError):
    """Fact emission failed before committing to the store."""


class CommittedEmissionError(EmissionFailed):
    """The fact was successfully committed to the canonical store, but a
    compound post-commit operation (e.g. tick computation or index sync) failed.

    The fact ID is preserved so callers know not to blindly retry.
    """

    def __init__(self, message: str, *, fact_id: str) -> None:
        super().__init__(message)
        self.fact_id = fact_id


class CeremonyFailed(ClientError):
    """Declaration update ceremony failed."""


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadSummary:
    """Statistical summary of a target artifact (inventory view)."""

    schema: str = "loops.cli/read-summary/v1"
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

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.latest_ts is not None:
            d["latest_iso"] = datetime.fromtimestamp(self.latest_ts, tz=UTC).isoformat()
        return d


@dataclass(frozen=True)
class FactPageResult:
    """Bounded, cursor-bearing page of facts."""

    schema: str = "loops.cli/facts-page/v1"
    items: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: str | None = None
    truncated: bool = False
    order: str = "newest"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FoldStateResult:
    """Declared folded state of a vertex."""

    schema: str = "loops.cli/fold-state/v1"
    vertex_name: str = ""
    target_path: str = ""
    declaration_status: str = ""
    generation: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmitReceipt:
    """Persisted receipt for an emitted fact."""

    schema: str = "loops.cli/emit-receipt/v1"
    id: str = ""
    stored: bool = True
    signed: bool | None = None
    observer: str = ""
    tick_mark: str | None = None
    tick_id: str | None = None
    state_change: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KindMutationResult:
    """Result of a declaration update / kind mutation ceremony."""

    schema: str = "loops.cli/kind-mutation/v1"
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
