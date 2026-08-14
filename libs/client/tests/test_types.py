"""Contract and unit tests for client types, models, and exceptions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from client import (
    AdmissionFailed,
    CeremonyFailed,
    ClientError,
    CommittedEmissionError,
    EmissionFailed,
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    KindMutationResult,
    ReadSummary,
    TargetError,
    TargetNotFound,
    TargetNotWritable,
    TargetUnsupported,
)


# =============================================================================
# 1. Exception Hierarchy Contracts
# =============================================================================


def test_exception_hierarchy() -> None:
    """Exception classes follow strict inheritance under ClientError."""
    # Target errors
    assert issubclass(TargetError, ClientError)
    assert issubclass(TargetNotFound, TargetError)
    assert issubclass(TargetUnsupported, TargetError)
    assert issubclass(TargetNotWritable, TargetError)

    # Emission & Admission errors
    assert issubclass(AdmissionFailed, ClientError)
    assert issubclass(EmissionFailed, ClientError)
    assert issubclass(CommittedEmissionError, EmissionFailed)

    # Ceremony errors
    assert issubclass(CeremonyFailed, ClientError)


def test_committed_emission_error_preserves_fact_id() -> None:
    """CommittedEmissionError retains the fact_id attribute for recovery."""
    err = CommittedEmissionError("Post-commit hook failed", fact_id="fact-0123456789")
    assert str(err) == "Post-commit hook failed"
    assert err.fact_id == "fact-0123456789"
    assert isinstance(err, EmissionFailed)
    assert isinstance(err, ClientError)


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
    assert isinstance(err, ClientError)


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
        kinds={"note": {"count": 10, "earliest": "2023-11-14T22:13:20+00:00", "latest": "2023-11-14T22:13:20+00:00"}},
        agreement=True,
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        summary.fact_total = 20  # type: ignore[misc]

    # Serialization
    d = summary.as_dict()
    assert d["schema"] == "loops.cli/read-summary/v1"
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
    assert d["schema"] == "loops.cli/facts-page/v1"
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
    assert d["schema"] == "loops.cli/fold-state/v1"
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
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        receipt.stored = False  # type: ignore[misc]

    # Serialization
    d = receipt.as_dict()
    assert d["schema"] == "loops.cli/emit-receipt/v1"
    assert d["id"] == "01JABCD12345"
    assert d["stored"] is True
    assert d["signed"] is True
    assert d["observer"] == "tester"
    assert d["tick_mark"] == "v1"
    assert d["tick_id"] == "tick-01"
    assert d["state_change"] is True


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
    assert d["schema"] == "loops.cli/kind-mutation/v1"
    assert d["status"] == "applied"
    assert d["reason"] == "ok"
    assert d["mode"] == "clean"
    assert d["file_written"] is True
    assert d["generation_after"] == {"generation": 2}
