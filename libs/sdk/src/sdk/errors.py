"""Normalize engine boundary failures for SDK process callers.

Engine deliberately keeps backend and witness refusal families separate.  The
SDK is the process boundary, so it translates those families into stable SDK
errors while retaining the identity evidence an operator needs to reconcile a
refusal or an outcome that may already have committed.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePath
from typing import Any

from engine.admission import AdmissionError
from engine.arrival import ArrivalError
from engine.arrival_contract import ContractRefusal
from engine.arrival_declarations import (
    DeclarationCommittedIncomplete,
    DeclarationOutcomeUnknown,
    DeclarationStale,
    DeclarationUnwitnessed,
)
from engine.arrival_head_attestation import AttestationRefusal
from engine.arrival_head_seam import NotWitnessed
from engine.arrival_initialization import (
    InitializationCommittedIncomplete,
    InitializationOutcomeUnknown,
    InitializationUnwitnessed,
)
from engine.arrival_maintenance import ProjectionSyncError
from engine.arrival_restore import RestoreForwardIncomplete, RestoreForwardUnknown
from engine.arrival_search import SearchIndexSyncError
from engine.runtime_write import (
    BatchPostCommitProjectionFailed,
    BatchWriteCommitUnknown,
    BatchWritePreparationRefused,
    PostCommitProjectionFailed,
    RuntimeWriteRefused,
    WriteCommitUnknown,
)

from .types import AdmissionFailed, SdkError

__all__ = [
    "ArrivalRefusal",
    "AdmissionRefusal",
    "CommittedOutcome",
    "CommittedProjectionFailed",
    "CommittedIncomplete",
    "CommittedUnwitnessed",
    "CommittedOutcomeUnknown",
    "ProjectionOutcomeUnknown",
    "normalize_exception",
]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, PurePath):
        return str(value)
    # Identity diagnostics must never stringify arbitrary record/payload objects.
    return None


def _head_dict(value: Any) -> dict[str, Any] | None:
    fields = ("lineage", "ordinal", "record_hash")
    if not all(hasattr(value, field) for field in fields):
        return None
    return {field: _json_value(getattr(value, field)) for field in fields}


def _coverage_dict(value: Any) -> dict[str, Any] | None:
    """Serialize explicit search-index coverage without backend row bodies."""
    through = _head_dict(getattr(value, "through", None))
    fields_hash = getattr(value, "fields_hash", None)
    schema_version = getattr(value, "schema_version", None)
    if through is None or not isinstance(fields_hash, str) or not isinstance(schema_version, str):
        return None
    return {
        "through": through,
        "fields_hash": fields_hash,
        "schema_version": schema_version,
    }


def _identity_details(exc: BaseException) -> dict[str, Any]:
    """Copy stable coordinates without serializing mutable record payloads."""
    details: dict[str, Any] = {}
    for name in (
        "fact_id",
        "tick_id",
        "ordinal",
        "observer",
        "kind",
        "vertex",
        "item_index",
        "source_type",
        "lineage",
        "intent_path",
        "phase",
        "fields_hash",
        "view_generation",
        "tier_index",
    ):
        value = getattr(exc, name, None)
        if value is not None:
            coordinate = _json_value(value)
            if coordinate is not None:
                details[name] = coordinate
    for name in ("fact_ids", "tick_ids"):
        value = getattr(exc, name, None)
        if value is not None:
            details[name] = [_json_value(item) for item in value]
    items = getattr(exc, "items", None)
    if items is not None:
        details["items"] = [
            {
                "fact_id": _json_value(item.fact_id),
                "tick_id": _json_value(item.tick_id),
                "tick_name": _json_value(item.tick_name),
                "already_present": bool(item.already_present),
            }
            for item in items
        ]
    for name in (
        "head",
        "captured_head",
        "presented",
        "before",
        "after",
        "target",
        "projected_before",
        "observed_after",
        "projected_head",
    ):
        value = getattr(exc, name, None)
        if value is None:
            continue
        head = _head_dict(value)
        if head is not None:
            details[name] = head
    for name in ("coverage_before", "coverage_after", "observed_after"):
        value = getattr(exc, name, None)
        coverage = _coverage_dict(value)
        if coverage is not None:
            details[name] = coverage
    # Preserve an explicitly unavailable coordinate without claiming a head or
    # coverage. Missing attributes on older wrappers still remain omitted.
    for name in (
        "captured_head", "projected_head", "projected_before", "observed_after",
        "coverage_before", "coverage_after",
    ):
        if hasattr(exc, name) and getattr(exc, name) is None:
            details[name] = None
    commit = getattr(exc, "commit", None)
    if commit is not None:
        before = _head_dict(getattr(commit, "before", None))
        after = _head_dict(getattr(commit, "after", None))
        commit_details: dict[str, Any] = {}
        if before is not None:
            commit_details["before"] = before
        if after is not None:
            commit_details["after"] = after
        if commit_details:
            details["commit"] = commit_details
    return details


def _causal_exception(exc: BaseException) -> BaseException | None:
    cause = getattr(exc, "cause", None)
    if isinstance(cause, BaseException):
        return cause
    return exc.__cause__ if isinstance(exc.__cause__, BaseException) else None


def _cause_details(exc: BaseException) -> dict[str, Any] | None:
    """Two explicit causal nodes, never implicit context or record bodies."""
    seen = {id(exc)}
    result: dict[str, Any] | None = None
    parent: dict[str, Any] | None = None
    for _ in range(2):
        cause = _causal_exception(exc)
        if cause is None or id(cause) in seen:
            break
        seen.add(id(cause))
        try:
            message = str(cause)
        except Exception:
            message = "<message unavailable>"
        node: dict[str, Any] = {
            "type": type(cause).__name__,
            "message": message[:512],
            "details": _identity_details(cause),
        }
        if len(message) > 512:
            node["truncated"] = True
        if parent is None:
            result = node
        else:
            parent["cause"] = node
        parent = node
        exc = cause
    return result


def _evidence_details(exc: BaseException, details: Mapping[str, Any]) -> dict[str, Any] | None:
    """Expose coordinator proofs without deriving effects from error classes."""
    evidence: dict[str, Any] = {}
    phase = getattr(exc, "coordinator_phase", None)
    if isinstance(phase, str):
        evidence["phase"] = phase
    effects = getattr(exc, "effects", None)
    if isinstance(effects, Mapping):
        safe_effects = {}
        for resource in ("custody", "witness", "derived", "cache", "artifact", "dispatch"):
            effect = effects.get(resource)
            if not isinstance(effect, Mapping):
                continue
            state = effect.get("state")
            attempt = effect.get("attempt")
            if state not in (
                "not-attempted", "known-none", "committed", "unknown", "completed", "incomplete"
            ):
                continue
            if attempt == "not-entered" and state != "not-attempted":
                continue
            if attempt == "entered" and state == "not-attempted":
                continue
            safe_effect = {"state": state}
            if attempt in ("not-entered", "entered"):
                safe_effect["attempt"] = attempt
            safe_effects[resource] = safe_effect
        if safe_effects:
            evidence["effects"] = safe_effects
    cause = _cause_details(exc)
    if cause is not None:
        evidence["cause"] = cause
    if not evidence:
        return None
    evidence["schema"] = "loops.sdk/evidence/v1"
    basis_fields = (
        "head", "captured_head", "presented", "target", "projected_before", "projected_head",
        "observed_after", "coverage_before", "coverage_after", "fields_hash", "view_generation",
    )
    identity_fields = (
        "fact_id", "tick_id", "fact_ids", "tick_ids", "items", "item_index", "tier_index",
        "ordinal", "observer", "kind", "vertex", "lineage", "commit",
    )
    basis = {name: details[name] for name in basis_fields if name in details}
    identities = {name: details[name] for name in identity_fields if name in details}
    if basis:
        evidence["basis"] = basis
    if identities:
        evidence["identities"] = identities
    return evidence


def _context_detail(name: str, value: Any) -> Any:
    """Serialize only stable identity fields supplied by an SDK operation."""
    if name in {"fact_ids", "tick_ids"}:
        return [_json_value(item) for item in value]
    if name == "items":
        return [
            {
                "fact_id": _json_value(item.fact_id),
                "tick_id": _json_value(item.tick_id),
                "tick_name": _json_value(item.tick_name),
                "already_present": bool(item.already_present),
            }
            for item in value
        ]
    head = _head_dict(value)
    return head if head is not None else _json_value(value)


class ArrivalRefusal(SdkError):
    """A typed, non-committing Arrival diagnostic refusal."""

    def __init__(self, message: str, *, source_type: str, details: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.source_type = source_type
        self.details = dict(details)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "loops.sdk/error/v1",
            "type": type(self).__name__,
            "message": str(self),
            "source_type": self.source_type,
            "outcome": "refused",
            "details": dict(self.details),
        }


class AdmissionRefusal(AdmissionFailed):
    """An engine admission refusal retaining its source and diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        source_type: str,
        details: Mapping[str, Any],
        observer: str | None = None,
        kind: str | None = None,
        vertex: str | None = None,
    ) -> None:
        super().__init__(message, observer=observer, kind=kind, vertex=vertex)
        self.source_type = source_type
        self.details = dict(details)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "loops.sdk/error/v1",
            "type": type(self).__name__,
            "message": str(self),
            "source_type": self.source_type,
            "outcome": "admission-refused",
            "details": dict(self.details),
        }


class CommittedOutcome(SdkError):
    """A durable or possibly durable operation with explicit reconciliation evidence."""

    outcome = "committed"

    def __init__(self, message: str, *, source_type: str, details: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.source_type = source_type
        self.details = dict(details)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "loops.sdk/error/v1",
            "type": type(self).__name__,
            "message": str(self),
            "source_type": self.source_type,
            "outcome": self.outcome,
            "details": dict(self.details),
        }


class CommittedOutcomeUnknown(CommittedOutcome):
    """The append outcome is unknown; reconcile before retrying."""

    outcome = "unknown"


class CommittedUnwitnessed(CommittedOutcome):
    """Custody committed, but witnessing failed."""

    outcome = "committed-unwitnessed"


class CommittedProjectionFailed(CommittedOutcome):
    """Custody committed, but post-commit projection publication failed."""

    outcome = "committed-projection-failed"


class CommittedIncomplete(CommittedOutcome):
    """A known commit exists while a later initialization phase is incomplete."""

    outcome = "committed-incomplete"


class ProjectionOutcomeUnknown(SdkError):
    """Projection maintenance may have changed derived state; reconcile it."""

    outcome = "projection-unknown"

    def __init__(self, message: str, *, source_type: str, details: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.source_type = source_type
        self.details = dict(details)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "loops.sdk/error/v1",
            "type": type(self).__name__,
            "message": str(self),
            "source_type": self.source_type,
            "outcome": self.outcome,
            "details": dict(self.details),
        }


def normalize_exception(
    exc: BaseException, *, context: Mapping[str, Any] | None = None
) -> BaseException:
    """Return a stable SDK exception for engine boundary failures.

    Existing SDK errors are returned unchanged.  Classification is by the
    engine's public exception types, never by message text.
    """
    if not isinstance(exc, Exception) or isinstance(exc, SdkError):
        return exc
    details = _identity_details(exc)
    context_fields = {
        "captured_head",
        "fact_id",
        "tick_id",
        "fact_ids",
        "tick_ids",
        "items",
        "item_index",
    }
    for name, value in (context or {}).items():
        if name in details or name not in context_fields:
            continue
        coordinate = _context_detail(name, value)
        if coordinate is not None or value is None:
            details[name] = coordinate
    details["source_type"] = type(exc).__name__
    evidence = _evidence_details(exc, details)
    if evidence is not None:
        details["evidence"] = evidence
    if isinstance(exc, (BatchWriteCommitUnknown, WriteCommitUnknown)):
        return CommittedOutcomeUnknown(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, InitializationOutcomeUnknown):
        return CommittedOutcomeUnknown(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, (DeclarationOutcomeUnknown, RestoreForwardUnknown)):
        return CommittedOutcomeUnknown(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, InitializationUnwitnessed):
        return CommittedUnwitnessed(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, DeclarationUnwitnessed):
        return CommittedUnwitnessed(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, InitializationCommittedIncomplete):
        return CommittedIncomplete(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, (DeclarationCommittedIncomplete, RestoreForwardIncomplete)):
        return CommittedIncomplete(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, NotWitnessed):
        return CommittedUnwitnessed(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, DeclarationStale):
        return ArrivalRefusal(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, BatchPostCommitProjectionFailed):
        return CommittedProjectionFailed(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, PostCommitProjectionFailed):
        return CommittedProjectionFailed(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, ProjectionSyncError):
        return ProjectionOutcomeUnknown(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, SearchIndexSyncError):
        return ProjectionOutcomeUnknown(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, BatchWritePreparationRefused):
        fact = exc.item.fact
        if exc.item.fact_id is not None:
            details.setdefault("fact_id", exc.item.fact_id)
        details.setdefault("observer", fact.observer)
        details.setdefault("kind", fact.kind)
        details.setdefault("vertex", exc.effective_declaration.name)
        if exc.admission_refused:
            return AdmissionRefusal(
                str(exc),
                source_type=type(exc).__name__,
                details=details,
                observer=fact.observer,
                kind=fact.kind,
                vertex=exc.effective_declaration.name,
            )
        return ArrivalRefusal(str(exc), source_type=type(exc).__name__, details=details)
    if isinstance(exc, AdmissionError):
        return AdmissionRefusal(
            str(exc),
            source_type=type(exc).__name__,
            details=details,
            observer=getattr(exc, "observer", None),
            kind=getattr(exc, "kind", None),
            vertex=getattr(exc, "vertex", None),
        )
    if isinstance(
        exc,
        (
            AttestationRefusal,
            ContractRefusal,
            ArrivalError,
            RuntimeWriteRefused,
        ),
    ):
        return ArrivalRefusal(str(exc), source_type=type(exc).__name__, details=details)
    return exc
