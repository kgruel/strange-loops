"""C2: SDK evidence is bounded, phase-aware, and receipt-honest."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from engine.arrival_contract import Head, Profile, ProjectionBehind, ReadBasis, StoreDescriptor
from engine.arrival_declarations import DeclarationPreparationRefused
from engine.arrival_head_seam import NotWitnessed
from engine.arrival_initialization import InitializationOutcomeUnknown
from engine.arrival_maintenance import ProjectionSyncError
from engine.arrival_search import SearchIndexSyncError

from sdk.errors import (
    ArrivalRefusal,
    CommittedUnwitnessed,
    ProjectionOutcomeUnknown,
    normalize_exception,
)


def _head() -> Head:
    return Head("evidence-lineage", 7, "evidence-hash")


def _projection_error(cause: BaseException) -> ProjectionSyncError:
    error = ProjectionSyncError(
        "projection failed",
        target=_head(),
        projected_before=None,
        observed_after=None,
        cause=cause,
    )
    error.coordinator_phase = "derived-sync"
    error.effects = {"derived": {"attempt": "entered", "state": "unknown"}}
    return error


def _search_error(cause: BaseException) -> SearchIndexSyncError:
    error = SearchIndexSyncError(
        "search build failed",
        target=_head(),
        coverage_before=None,
        observed_after=None,
        fields_hash="fields-hash",
        cause=cause,
    )
    error.coordinator_phase = "derived-sync"
    error.effects = {
        "derived": {"attempt": "not-entered", "state": "not-attempted"}
    }
    return error


def _descriptor() -> StoreDescriptor:
    return StoreDescriptor(
        backend="file",
        location="/not-opened-by-this-test.arrival",
        lineage="evidence-lineage",
        role=Profile.AUTHORITY,
    )


def test_evidence_prefers_explicit_cause_and_bounds_serialization() -> None:
    class PayloadTrap:
        def __str__(self) -> str:
            raise AssertionError("payload must not be stringified")

    explicit = OSError("x" * 600)
    explicit.payload = PayloadTrap()
    explicit.observer = PayloadTrap()
    second = RuntimeError("second cause")
    third = ValueError("third cause must be outside the two-node bound")
    explicit.__cause__ = second
    second.__cause__ = third
    explicit.__context__ = ValueError("explicit context must not be serialized")
    ignored = LookupError("outer implicit cause")
    error = _projection_error(explicit)
    error.phase = "legacy-phase"
    error.__cause__ = ignored

    normalized = normalize_exception(error)

    assert isinstance(normalized, ProjectionOutcomeUnknown)
    assert normalized.details["phase"] == "legacy-phase"
    evidence = normalized.details["evidence"]
    assert evidence["schema"] == "loops.sdk/evidence/v1"
    assert evidence["phase"] == "derived-sync"
    assert evidence["effects"] == {
        "derived": {"state": "unknown", "attempt": "entered"}
    }
    assert evidence["basis"]["target"]["ordinal"] == 7
    first = evidence["cause"]
    assert first["type"] == "OSError"
    assert first["message"] == "x" * 512
    assert first["truncated"] is True
    assert first["details"] == {}
    assert first["cause"] == {
        "type": "RuntimeError",
        "message": "second cause",
        "details": {},
    }
    assert "cause" not in first["cause"]
    assert "outer implicit cause" not in json.dumps(evidence)
    assert "explicit context" not in json.dumps(evidence)
    assert "third cause" not in json.dumps(evidence)
    assert "payload" not in json.dumps(evidence)


@pytest.mark.parametrize(
    "effect",
    (
        {"attempt": "not-entered", "state": "unknown"},
        {"attempt": "entered", "state": "not-attempted"},
    ),
)
def test_evidence_cause_cycle_and_invalid_attempt_are_safe(
    effect: dict[str, str]
) -> None:
    cycle = RuntimeError("cycle")
    cycle.__cause__ = cycle
    error = _projection_error(cycle)
    error.effects = {"derived": effect}

    normalized = normalize_exception(error)

    assert isinstance(normalized, ProjectionOutcomeUnknown)
    evidence = normalized.details["evidence"]
    assert evidence["cause"] == {
        "type": "RuntimeError", "message": "cycle", "details": {}
    }
    assert "cause" not in evidence["cause"]
    assert "effects" not in evidence


def test_legacy_error_omits_unsupported_phase_and_effect_proof() -> None:
    error = ProjectionSyncError(
        "legacy maintenance failure",
        target=_head(),
        projected_before=None,
        observed_after=None,
        cause=ValueError("old adapter"),
    )

    normalized = normalize_exception(error)

    assert isinstance(normalized, ProjectionOutcomeUnknown)
    evidence = normalized.details["evidence"]
    assert "phase" not in evidence
    assert "effects" not in evidence
    assert evidence["cause"]["type"] == "ValueError"


def test_declaration_preparation_evidence_keeps_chained_projection_coordinates() -> None:
    captured = _head()
    projected = Head(captured.lineage, 5, "older-projection")
    behind = ProjectionBehind("projection is behind")
    behind.captured_head = captured
    behind.projected_head = projected
    refused = DeclarationPreparationRefused(
        "declaration preparation refused",
        coordinator_phase="prepare",
        effects={"custody": {"attempt": "not-entered", "state": "not-attempted"}},
        captured_head=captured,
        projected_head=projected,
    )
    refused.__cause__ = behind

    normalized = normalize_exception(refused)

    assert isinstance(normalized, ArrivalRefusal)
    evidence = normalized.details["evidence"]
    assert evidence["phase"] == "prepare"
    assert evidence["effects"] == {
        "custody": {"state": "not-attempted", "attempt": "not-entered"}
    }
    assert evidence["basis"]["captured_head"]["ordinal"] == captured.ordinal
    assert evidence["basis"]["projected_head"]["ordinal"] == projected.ordinal
    assert evidence["cause"] == {
        "type": "ProjectionBehind",
        "message": "projection is behind",
        "details": {
            "captured_head": {
                "lineage": captured.lineage,
                "ordinal": captured.ordinal,
                "record_hash": captured.record_hash,
            },
            "projected_head": {
                "lineage": projected.lineage,
                "ordinal": projected.ordinal,
                "record_hash": projected.record_hash,
            },
        },
    }

    legacy = normalize_exception(DeclarationPreparationRefused("legacy refusal"))
    assert isinstance(legacy, ArrivalRefusal)
    assert "evidence" not in legacy.details
    assert "phase" not in legacy.details


def test_preopen_declaration_context_keeps_actual_head_and_explicit_null_is_preserved() -> None:
    context_head = _head()
    preopen = normalize_exception(
        DeclarationPreparationRefused("pre-open refusal"),
        context={"captured_head": context_head},
    )
    assert isinstance(preopen, ArrivalRefusal)
    assert preopen.details["captured_head"] == {
        "lineage": context_head.lineage,
        "ordinal": context_head.ordinal,
        "record_hash": context_head.record_hash,
    }
    assert "projected_head" not in preopen.details

    explicit_unknown = normalize_exception(
        InitializationOutcomeUnknown(
            "mint transport failed",
            phase="reserved",
            lineage="evidence-lineage",
            fact_id="evidence-lineage",
            captured_head=None,
            intent_path=Path("/tmp/evidence.intent"),
            cause=OSError("transport"),
        ),
        context={"captured_head": context_head},
    )
    assert explicit_unknown.details["captured_head"] is None


def test_unwitnessed_mint_retains_head_without_fabricated_commit() -> None:
    normalized = normalize_exception(
        NotWitnessed("mint witness failed", head=_head(), commit=None)
    )

    assert isinstance(normalized, CommittedUnwitnessed)
    assert normalized.details["head"] == {
        "lineage": "evidence-lineage", "ordinal": 7, "record_hash": "evidence-hash"
    }
    assert "commit" not in normalized.details
    assert "evidence" not in normalized.details


def test_normalize_exception_preserves_cancellation_identity() -> None:
    cancelled = asyncio.CancelledError()
    assert normalize_exception(cancelled) is cancelled


def test_sync_target_and_search_sync_normalize_same_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import engine.arrival_maintenance as maintenance
    import engine.arrival_search as search

    import sdk.read as read

    target = tmp_path / "evidence.vertex"
    descriptor = _descriptor()
    basis = ReadBasis(
        lineage=_head().lineage,
        captured_head=_head(),
        projected_through=_head(),
        view_generation="generation",
    )

    monkeypatch.setattr(read, "_arrival_descriptor", lambda _target: (target, object(), descriptor))
    sync_error = _projection_error(OSError("sync"))
    monkeypatch.setattr(
        maintenance,
        "sync_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sync_error),
    )
    with pytest.raises(ProjectionOutcomeUnknown) as sync_failure:
        read.sync_target(target)

    @contextmanager
    def fake_open(*_args, **_kwargs):
        yield object(), descriptor, SimpleNamespace(basis=basis)

    monkeypatch.setattr(read, "_open_arrival_read", fake_open)
    monkeypatch.setattr(read, "_arrival_search_spec", lambda *_args: object())
    search_error = _search_error(OSError("search"))
    monkeypatch.setattr(
        search,
        "sync_search_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(search_error),
    )
    with pytest.raises(ProjectionOutcomeUnknown) as search_failure:
        read.sync_search_index(target)

    assert sync_failure.value.__cause__ is sync_error
    assert search_failure.value.__cause__ is search_error
    assert sync_failure.value.details == normalize_exception(sync_error).details
    assert search_failure.value.details == normalize_exception(search_error).details
    assert sync_failure.value.details["evidence"]["effects"] == {
        "derived": {"state": "unknown", "attempt": "entered"}
    }
    assert search_failure.value.details["evidence"]["effects"] == {
        "derived": {"state": "not-attempted", "attempt": "not-entered"}
    }


@pytest.mark.parametrize(
    "operation, raw",
    (("target", TypeError("bad target")), ("search", ValueError("bad spec"))),
)
def test_maintenance_wrappers_leave_unmatched_errors_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, raw: Exception
) -> None:
    import engine.arrival_maintenance as maintenance
    import engine.arrival_search as search

    import sdk.read as read

    target = tmp_path / "unchanged.vertex"
    descriptor = _descriptor()
    monkeypatch.setattr(read, "_arrival_descriptor", lambda _target: (target, object(), descriptor))
    if operation == "target":
        monkeypatch.setattr(
            maintenance,
            "sync_projection",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(raw),
        )
        with pytest.raises(TypeError) as caught:
            read.sync_target(target)
    else:
        basis = ReadBasis(
            lineage=_head().lineage,
            captured_head=_head(),
            projected_through=_head(),
            view_generation="generation",
        )

        @contextmanager
        def fake_open(*_args, **_kwargs):
            yield object(), descriptor, SimpleNamespace(basis=basis)

        monkeypatch.setattr(read, "_open_arrival_read", fake_open)
        monkeypatch.setattr(read, "_arrival_search_spec", lambda *_args: object())
        monkeypatch.setattr(
            search,
            "sync_search_index",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(raw),
        )
        with pytest.raises(ValueError) as caught:
            read.sync_search_index(target)
    assert caught.value is raw


@pytest.mark.parametrize("operation", ("target", "search"))
def test_maintenance_wrappers_preserve_cancellation_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    import engine.arrival_maintenance as maintenance
    import engine.arrival_search as search

    import sdk.read as read

    target = tmp_path / "cancelled.vertex"
    descriptor = _descriptor()
    cancelled = asyncio.CancelledError()
    monkeypatch.setattr(read, "_arrival_descriptor", lambda _target: (target, object(), descriptor))
    if operation == "target":
        monkeypatch.setattr(
            maintenance,
            "sync_projection",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(cancelled),
        )
        with pytest.raises(asyncio.CancelledError) as caught:
            read.sync_target(target)
    else:
        basis = ReadBasis(
            lineage=_head().lineage,
            captured_head=_head(),
            projected_through=_head(),
            view_generation="generation",
        )

        @contextmanager
        def fake_open(*_args, **_kwargs):
            yield object(), descriptor, SimpleNamespace(basis=basis)

        monkeypatch.setattr(read, "_open_arrival_read", fake_open)
        monkeypatch.setattr(read, "_arrival_search_spec", lambda *_args: object())
        monkeypatch.setattr(
            search,
            "sync_search_index",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(cancelled),
        )
        with pytest.raises(asyncio.CancelledError) as caught:
            read.sync_search_index(target)
    assert caught.value is cancelled
