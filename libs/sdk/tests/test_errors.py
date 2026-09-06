"""Stable SDK classification of engine boundary outcomes."""

from __future__ import annotations

from pathlib import Path

from atoms import Fact
from engine.admission import UnknownObserver
from engine.arrival import ArrivalCorrupt
from engine.arrival_contract import Head, ProjectionBehind, ReadBasis
from engine.arrival_head_attestation import HeadRollback
from engine.arrival_head_seam import NotWitnessed
from engine.arrival_initialization import (
    InitializationCommittedIncomplete,
    InitializationOutcomeUnknown,
    InitializationUnwitnessed,
)
from engine.arrival_maintenance import ProjectionSyncError
from engine.runtime_write import (
    BatchFactInput,
    BatchItemResult,
    BatchPostCommitProjectionFailed,
    BatchWriteCommitUnknown,
    BatchWritePlan,
    BatchWritePreparationRefused,
    OrdinaryWritePlan,
    PostCommitProjectionFailed,
    WriteCommitUnknown,
)
from lang import parse_vertex

from sdk.errors import (
    ArrivalRefusal,
    CommittedIncomplete,
    CommittedOutcomeUnknown,
    CommittedUnwitnessed,
    ProjectionOutcomeUnknown,
    normalize_exception,
)


def test_corruption_and_projection_are_typed_refusals_with_source_identity() -> None:
    corrupt = normalize_exception(ArrivalCorrupt("bad record hash", 7))
    behind = normalize_exception(ProjectionBehind("projection is behind"))

    assert isinstance(corrupt, ArrivalRefusal)
    assert corrupt.details == {"ordinal": 7, "source_type": "ArrivalCorrupt"}
    assert isinstance(behind, ArrivalRefusal)
    assert behind.details["source_type"] == "ProjectionBehind"


def test_rollback_preserves_attestation_head_and_committed_outcome_identity() -> None:
    head = Head("lineage", 12, "hash")
    raw_rollback = HeadRollback("rollback")
    raw_rollback.presented = head
    rollback = normalize_exception(raw_rollback)
    committed = normalize_exception(
        NotWitnessed("journal unavailable", head=head),
        context={"captured_head": head, "fact_id": "fact", "tick_id": "tick"},
    )

    assert isinstance(rollback, ArrivalRefusal)
    assert rollback.details["source_type"] == "HeadRollback"
    assert rollback.details["presented"] == {
        "lineage": "lineage",
        "ordinal": 12,
        "record_hash": "hash",
    }
    assert isinstance(committed, CommittedUnwitnessed)
    assert committed.as_dict()["outcome"] == "committed-unwitnessed"
    assert committed.details["head"] == {
        "lineage": "lineage",
        "ordinal": 12,
        "record_hash": "hash",
    }
    assert committed.details["fact_id"] == "fact"
    assert committed.details["tick_id"] == "tick"


def test_admission_and_projection_failures_keep_their_process_categories() -> None:
    head = Head("lineage", 12, "hash")
    admission = normalize_exception(UnknownObserver("ada", "vertex"))
    projection = normalize_exception(
        ProjectionSyncError(
            "projection refused",
            target=head,
            projected_before=None,
            observed_after=head,
            cause=RuntimeError("test"),
        )
    )

    from sdk.types import AdmissionFailed

    assert isinstance(admission, AdmissionFailed)
    assert admission.source_type == "UnknownObserver"
    assert admission.details["observer"] == "ada"
    assert isinstance(projection, ProjectionOutcomeUnknown)
    assert projection.as_dict()["outcome"] == "projection-unknown"
    assert projection.details["target"] == {
        "lineage": "lineage",
        "ordinal": 12,
        "record_hash": "hash",
    }
    assert projection.details["observed_after"] == projection.details["target"]


def test_runtime_commit_unknown_and_postcommit_projection_keep_distinct_outcomes() -> None:
    head = Head("lineage", 12, "hash")
    plan = OrdinaryWritePlan(captured_head=head, fact_id="fact", tick_id="tick", drafts=())
    commit = type("Commit", (), {"before": head, "after": Head("lineage", 13, "next")})()

    unknown = normalize_exception(WriteCommitUnknown(plan, RuntimeError("adapter")))
    projection = normalize_exception(
        PostCommitProjectionFailed(commit, plan, RuntimeError("projection"))
    )

    assert type(unknown).__name__ == "CommittedOutcomeUnknown"
    assert unknown.as_dict()["outcome"] == "unknown"
    assert unknown.details["captured_head"]["ordinal"] == 12
    assert type(projection).__name__ == "CommittedProjectionFailed"
    assert projection.as_dict()["outcome"] == "committed-projection-failed"
    assert projection.details["commit"]["after"]["ordinal"] == 13


def test_initializer_outcomes_preserve_phase_lineage_and_commit_state() -> None:
    head = Head("lineage", 1, "hash")
    intent = "/tmp/arrival-init.intent"
    unknown = normalize_exception(
        InitializationOutcomeUnknown(
            "mint transport failed", phase="reserved", lineage="lineage",
            fact_id="lineage", captured_head=None, intent_path=Path(intent),
            cause=OSError("transport"),
        )
    )
    unwitnessed = normalize_exception(
        InitializationUnwitnessed(
            "append witness failed", phase="minted", lineage="lineage",
            fact_id="fact", head=head, commit=None,
            intent_path=Path(intent), cause=OSError("journal"),
        )
    )
    incomplete = normalize_exception(
        InitializationCommittedIncomplete(
            "publication failed", phase="published", lineage="lineage",
            fact_id="fact", captured_head=head, commit=None,
            intent_path=Path(intent), cause=OSError("fsync"),
        )
    )

    assert isinstance(unknown, CommittedOutcomeUnknown)
    assert unknown.as_dict()["outcome"] == "unknown"
    assert unknown.details["lineage"] == "lineage"
    assert unknown.details["captured_head"] is None
    assert isinstance(unwitnessed, CommittedUnwitnessed)
    assert unwitnessed.as_dict()["outcome"] == "committed-unwitnessed"
    assert unwitnessed.details["head"]["ordinal"] == 1
    assert isinstance(incomplete, CommittedIncomplete)
    assert incomplete.as_dict()["outcome"] == "committed-incomplete"
    assert incomplete.details["phase"] == "published"
    assert incomplete.details["captured_head"]["ordinal"] == 1


def test_batch_outcomes_keep_every_item_identity_and_commit_category() -> None:
    head = Head("lineage", 12, "hash")
    items = (
        BatchItemResult("one", "tick-one", "note", False),
        BatchItemResult("two", None, None, True),
    )
    plan = BatchWritePlan(head, items, ())
    commit = type("Commit", (), {"before": head, "after": Head("lineage", 14, "next")})()

    unknown = normalize_exception(
        BatchWriteCommitUnknown(plan, RuntimeError("adapter"))
    )
    projection = normalize_exception(
        BatchPostCommitProjectionFailed(commit, plan, RuntimeError("projection"))
    )

    assert unknown.as_dict()["outcome"] == "unknown"
    assert unknown.details["fact_ids"] == ["one", "two"]
    assert unknown.details["tick_ids"] == ["tick-one"]
    assert unknown.details["items"][1] == {
        "fact_id": "two",
        "tick_id": None,
        "tick_name": None,
        "already_present": True,
    }
    assert projection.as_dict()["outcome"] == "committed-projection-failed"
    assert projection.details["commit"]["after"]["ordinal"] == 14
    assert projection.details["fact_ids"] == ["one", "two"]


def test_batch_preparation_refusal_is_an_admission_category_with_item_address() -> None:
    head = Head("lineage", 12, "hash")
    effective = parse_vertex('name "effective"\nloops { note { } }\n')
    item = BatchFactInput(
        Fact("other", 1.0, {}, observer="ada"), fact_id="planned-id"
    )
    raw = BatchWritePreparationRefused(
        input_index=3,
        item=item,
        effective_declaration=effective,
        custodian="custodian",
        basis=ReadBasis("lineage", head, head, "view"),
        cause=UnknownObserver("ada", "effective"),
        admission_refused=True,
    )

    refusal = normalize_exception(raw)

    assert type(refusal).__name__ == "AdmissionRefusal"
    assert refusal.as_dict()["outcome"] == "admission-refused"
    assert refusal.details["item_index"] == 3
    assert refusal.details["fact_id"] == "planned-id"
    assert refusal.details["observer"] == "ada"
    assert refusal.details["kind"] == "other"
    assert refusal.details["captured_head"]["ordinal"] == 12

    generated_id_item = BatchFactInput(Fact("other", 1.0, {}, observer="ada"))
    generated_id_raw = BatchWritePreparationRefused(
        input_index=4,
        item=generated_id_item,
        effective_declaration=effective,
        custodian="custodian",
        basis=ReadBasis("lineage", head, head, "view"),
        cause=UnknownObserver("ada", "effective"),
        admission_refused=True,
    )
    generated_id_refusal = normalize_exception(generated_id_raw)
    assert "fact_id" not in generated_id_refusal.details
