"""Contract and unit tests for SDK types, models, and exceptions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from sdk import (
    AdmissionFailed,
    CeremonyFailed,
    CommittedEmissionError,
    EmissionFailed,
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    InvalidEmissionRequest,
    KindMutationResult,
    ReadSummary,
    SdkError,
    SdkValueError,
    TargetError,
    TargetNotFound,
    TargetNotWritable,
    TargetUnsupported,
)

# =============================================================================
# 1. Exception Hierarchy Contracts
# =============================================================================


def test_exception_hierarchy() -> None:
    """Exception classes follow strict inheritance under SdkError."""
    # Target errors
    assert issubclass(TargetError, SdkError)
    assert issubclass(TargetNotFound, TargetError)
    assert issubclass(TargetUnsupported, TargetError)
    assert issubclass(TargetNotWritable, TargetError)

    # Emission & Admission errors
    assert issubclass(AdmissionFailed, SdkError)
    assert issubclass(EmissionFailed, SdkError)
    assert issubclass(SdkValueError, SdkError)
    assert issubclass(SdkValueError, ValueError)
    assert issubclass(InvalidEmissionRequest, SdkValueError)
    assert issubclass(InvalidEmissionRequest, EmissionFailed)
    assert issubclass(CommittedEmissionError, EmissionFailed)

    # Ceremony errors
    assert issubclass(CeremonyFailed, SdkError)


def test_committed_emission_error_preserves_fact_id() -> None:
    """CommittedEmissionError retains the fact_id attribute for recovery."""
    err = CommittedEmissionError("Post-commit hook failed", fact_id="fact-0123456789")
    assert str(err) == "Post-commit hook failed"
    assert err.fact_id == "fact-0123456789"
    assert isinstance(err, EmissionFailed)
    assert isinstance(err, SdkError)


def test_admission_failed_attributes() -> None:
    """AdmissionFailed preserves observer, kind, and vertex attributes."""
    err = AdmissionFailed(
        "Strict policy refusal",
        observer="alice",
        kind="unregistered_kind",
        vertex="main_vertex",
    )
    assert str(err) == "Strict policy refusal"
    assert err.observer == "alice"
    assert err.kind == "unregistered_kind"
    assert err.vertex == "main_vertex"
    assert isinstance(err, SdkError)


# =============================================================================
# 2. Model Immutability & Serialization Contracts
# =============================================================================


def test_read_summary_model() -> None:
    """ReadSummary defaults, frozenness, and as_dict conversion."""
    summary = ReadSummary(
        target_type="vertex",
        target_path="/tmp/test.vertex",
        canonical_mode="sqlite",
        canonical_path="/tmp/test.db",
        index_path="/tmp/test.db",
        fact_total=10,
        tick_total=2,
        latest_ts=1700000000.0,
        kinds={
            "note": {
                "count": 10,
                "earliest": "2023-11-14T22:13:20+00:00",
                "latest": "2023-11-14T22:13:20+00:00",
            }
        },
        agreement=True,
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        summary.fact_total = 20  # type: ignore[misc]

    # Serialization
    d = summary.as_dict()
    assert d["schema"] == "loops.sdk/read-summary/v1"
    assert d["target_type"] == "vertex"
    assert d["target_path"] == "/tmp/test.vertex"
    assert d["canonical_mode"] == "sqlite"
    assert d["fact_total"] == 10
    assert d["tick_total"] == 2
    assert d["latest_ts"] == 1700000000.0
    assert d["latest_iso"] == datetime.fromtimestamp(1700000000.0, tz=UTC).isoformat()
    assert d["agreement"] is True
    assert "note" in d["kinds"]

    # When latest_ts is None, latest_iso is omitted
    summary_empty = ReadSummary()
    d_empty = summary_empty.as_dict()
    assert "latest_iso" not in d_empty


def test_fact_page_result_model() -> None:
    """FactPageResult defaults, frozenness, and as_dict conversion."""
    page = FactPageResult(
        items=[{"kind": "note", "id": "01J..."}],
        next_cursor="cursor_token",
        truncated=True,
        order="newest",
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        page.truncated = False  # type: ignore[misc]

    # Serialization
    d = page.as_dict()
    assert d["schema"] == "loops.sdk/facts-page/v1"
    assert len(d["items"]) == 1
    assert d["next_cursor"] == "cursor_token"
    assert d["truncated"] is True
    assert d["order"] == "newest"


def test_fold_state_result_model() -> None:
    """FoldStateResult defaults, frozenness, and as_dict conversion."""
    state = FoldStateResult(
        vertex_name="my_vertex",
        target_path="/tmp/my_vertex.vertex",
        declaration_status="store",
        generation={"generation": 1},
        sections={"note": {"kind": "note", "count": 5}},
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        state.vertex_name = "other"  # type: ignore[misc]

    # Serialization
    d = state.as_dict()
    assert d["schema"] == "loops.sdk/fold-state/v1"
    assert d["vertex_name"] == "my_vertex"
    assert d["declaration_status"] == "store"
    assert d["sections"]["note"]["count"] == 5


def test_emit_receipt_model() -> None:
    """EmitReceipt defaults, frozenness, and as_dict conversion."""
    receipt = EmitReceipt(
        id="01JABCD12345",
        stored=True,
        signed=True,
        observer="tester",
        tick_mark="v1",
        tick_id="tick-01",
        state_change=True,
        affected_sections=["note"],
        delta_count=1,
        predicted_state_change=False,
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        receipt.stored = False  # type: ignore[misc]

    # Serialization
    d = receipt.as_dict()
    assert d["schema"] == "loops.sdk/emit-receipt/v1"
    assert d["id"] == "01JABCD12345"
    assert d["stored"] is True
    assert d["signed"] is True
    assert d["observer"] == "tester"
    assert d["tick_mark"] == "v1"
    assert d["tick_id"] == "tick-01"
    assert d["state_change"] is True
    assert d["affected_sections"] == ["note"]
    assert d["delta_count"] == 1
    assert d["predicted_state_change"] is False

    # Dry-run receipt uncommitted shape
    dry_receipt = EmitReceipt(
        id="",
        stored=False,
        signed=None,
        observer="tester",
        tick_mark=None,
        tick_id=None,
        state_change=False,
        affected_sections=["note"],
        delta_count=0,
        predicted_state_change=True,
    )
    d_dry = dry_receipt.as_dict()
    assert d_dry["stored"] is False
    assert d_dry["state_change"] is False
    assert d_dry["predicted_state_change"] is True
    assert d_dry["delta_count"] == 0
    assert d_dry["id"] == ""


def test_emit_preview_result_model() -> None:
    """EmitPreviewResult defaults, frozenness, and as_dict conversion."""
    from sdk import EmitPreviewResult

    preview = EmitPreviewResult(
        target="/tmp/test.vertex",
        kind="task",
        observer="alice",
        origin="agent-session",
        ts=1700000000.0,
        payload={"title": "Preview Task"},
        kind_declared=True,
        fold_key_field="id",
        fold_key_present=True,
        fold_key_value="task-1",
        admitted=True,
        strict=False,
        would_store=True,
        would_fold=True,
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        preview.admitted = False  # type: ignore[misc]

    # Serialization
    d = preview.as_dict()
    assert d["schema"] == "loops.sdk/emit-preview/v1"
    assert d["target"] == "/tmp/test.vertex"
    assert d["kind"] == "task"
    assert d["kind_declared"] is True
    assert d["would_fold"] is True


def test_kind_mutation_result_model() -> None:
    """KindMutationResult defaults, frozenness, and as_dict conversion."""
    result = KindMutationResult(
        status="applied",
        reason="ok",
        mode="clean",
        vertex_path="/tmp/test.vertex",
        generation_before={"generation": 1},
        generation_after={"generation": 2},
        changes=[{"op": "add_kind", "kind": "task"}],
        file_written=True,
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]

    # Serialization
    d = result.as_dict()
    assert d["schema"] == "loops.sdk/kind-mutation/v1"
    assert d["status"] == "applied"
    assert d["reason"] == "ok"
    assert d["mode"] == "clean"
    assert d["file_written"] is True
    assert d["generation_after"] == {"generation": 2}


def test_search_result_models() -> None:
    """SearchResult and SearchResultItem defaults, immutability, and serialization."""
    from sdk import SearchResult, SearchResultItem

    item = SearchResultItem(
        id="01FACT00000000000000000001",
        kind="task",
        ts=1700000000.0,
        observer="alice",
        origin="cli",
        payload={"title": "Test task"},
        rank=-1.25,
        snippet="Test <b>task</b>",
    )
    with pytest.raises(FrozenInstanceError):
        item.rank = 0.0  # type: ignore[misc]

    res = SearchResult(query="task", matches=[item], total_matches=1)
    with pytest.raises(FrozenInstanceError):
        res.total_matches = 2  # type: ignore[misc]

    d = res.as_dict()
    assert d["schema"] == "loops.sdk/search-result/v1"
    assert d["query"] == "task"
    assert d["total_matches"] == 1
    assert len(d["matches"]) == 1
    assert d["matches"][0]["id"] == "01FACT00000000000000000001"


def test_timeline_result_models() -> None:
    """TimelineResult and TimelineEvent defaults, immutability, and serialization."""
    from sdk import TimelineEvent, TimelineResult

    evt = TimelineEvent(
        event_type="fact",
        id="01FACT00000000000000000001",
        kind_or_name="task",
        ts=1700000000.0,
        observer="alice",
        origin="cli",
        payload={"title": "Test task"},
    )
    with pytest.raises(FrozenInstanceError):
        evt.ts = 0.0  # type: ignore[misc]

    res = TimelineResult(events=[evt], start_ts=1700000000.0, end_ts=1700000100.0, total_events=1)
    with pytest.raises(FrozenInstanceError):
        res.total_events = 2  # type: ignore[misc]

    d = res.as_dict()
    assert d["schema"] == "loops.sdk/timeline-result/v1"
    assert d["start_ts"] == 1700000000.0
    assert d["total_events"] == 1
    assert len(d["events"]) == 1


def test_sync_result_model() -> None:
    """SyncResult defaults, immutability, and serialization."""
    from sdk import SyncResult

    res = SyncResult(
        target_path="/tmp/test.vertex",
        status="synced",
        indexed_facts=42,
        agreement=True,
        duration_ms=12.5,
    )
    with pytest.raises(FrozenInstanceError):
        res.status = "failed"  # type: ignore[misc]

    d = res.as_dict()
    assert d["schema"] == "loops.sdk/sync-result/v1"
    assert d["target_path"] == "/tmp/test.vertex"
    assert d["status"] == "synced"
    assert d["indexed_facts"] == 42
    assert d["agreement"] is True


def test_init_vertex_result_model() -> None:
    """InitVertexResult defaults, immutability, and serialization."""
    from sdk import InitVertexResult

    res = InitVertexResult(
        target_path="/tmp/app.vertex",
        name="app",
        store_path=".loops/data/app.db",
        store_type="sqlite",
        is_root=False,
        file_written=True,
    )
    with pytest.raises(FrozenInstanceError):
        res.name = "other"  # type: ignore[misc]

    d = res.as_dict()
    assert d["schema"] == "loops.sdk/init-vertex/v1"
    assert d["name"] == "app"
    assert d["store_type"] == "sqlite"
    assert d["file_written"] is True


def test_declaration_inspection_result_model() -> None:
    """DeclarationInspectionResult defaults, immutability, and serialization."""
    from sdk import DeclarationInspectionResult

    res = DeclarationInspectionResult(
        target_path="/tmp/app.vertex",
        name="app",
        status="active",
        store_mode="sqlite",
        store_path=".loops/data/app.db",
        declared_kinds=["note", "task"],
        declared_observers=["alice"],
        cadence_ticks=["daily"],
        strict=True,
        is_aggregate=False,
        syntax_valid=True,
        errors=[],
    )
    with pytest.raises(FrozenInstanceError):
        res.strict = False  # type: ignore[misc]

    d = res.as_dict()
    assert d["schema"] == "loops.sdk/declaration-inspection/v1"
    assert d["declared_kinds"] == ["note", "task"]
    assert d["strict"] is True
    assert d["syntax_valid"] is True


def test_declaration_plan_result_model() -> None:
    """DeclarationPlanResult defaults, immutability, and serialization."""
    from sdk import DeclarationPlanResult

    res = DeclarationPlanResult(
        applicable=True,
        reason="",
        mode="clean",
        vertex_path="/tmp/app.vertex",
        generation_before={"generation": 1},
        changes=[{"op": "add", "kind": "task"}],
    )
    with pytest.raises(FrozenInstanceError):
        res.applicable = False  # type: ignore[misc]

    d = res.as_dict()
    assert d["schema"] == "loops.sdk/declaration-plan/v1"
    assert d["applicable"] is True
    assert d["mode"] == "clean"
    assert len(d["changes"]) == 1
