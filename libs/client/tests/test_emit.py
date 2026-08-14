"""Integration and contract tests for client fact emission operations."""

from __future__ import annotations

from pathlib import Path

import pytest
from client import (
    AdmissionFailed,
    EmitReceipt,
    TargetNotFound,
    TargetUnsupported,
    emit_fact,
    read_facts,
    read_summary,
)
from custody import ensure_signing_key


def test_emit_fact_declared_kind(sample_vertex: Path) -> None:
    """Emitting a declared kind persists the fact and returns an EmitReceipt."""
    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Declared Note", "content": "Hello World"},
        observer="alice",
    )

    assert isinstance(receipt, EmitReceipt)
    assert receipt.stored is True
    assert receipt.id != ""
    assert receipt.observer == "alice"
    assert receipt.state_change is True

    # Verify fact appears in store
    page = read_facts(sample_vertex, limit=10)
    assert len(page.items) == 1
    assert page.items[0]["id"] == receipt.id
    assert page.items[0]["payload"]["title"] == "Declared Note"


def test_emit_fact_undeclared_kind_rejected_by_default(strict_vertex: Path) -> None:
    """Emitting an undeclared kind on a strict vertex without admit_undeclared raises AdmissionFailed."""
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_fact(
            strict_vertex,
            "undeclared_custom_kind",
            {"key": "value"},
            observer="alice",
        )
    assert "undeclared" in str(exc_info.value).lower() or "admission" in str(exc_info.value).lower()


def test_emit_fact_admit_undeclared_override(sample_vertex: Path) -> None:
    """Emitting undeclared kind with admit_undeclared=True succeeds."""
    receipt = emit_fact(
        sample_vertex,
        "custom_kind",
        {"metric": 42},
        observer="alice",
        admit_undeclared=True,
    )
    assert receipt.stored is True
    assert receipt.id != ""

    summary = read_summary(sample_vertex)
    assert "custom_kind" in summary.unfolded_kinds
    assert summary.kinds["custom_kind"]["count"] == 1


def test_emit_fact_signed_with_custody_key(sample_vertex: Path) -> None:
    """Emitting when custody keys exist produces signed receipts."""
    ensure_signing_key(sample_vertex, "trusted_observer")

    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Signed note"},
        observer="trusted_observer",
    )
    assert receipt.stored is True
    assert receipt.signed is True
    assert receipt.observer == "trusted_observer"


def test_emit_fact_unsupported_on_non_vertex(tmp_path: Path) -> None:
    """emit_fact raises TargetUnsupported when given a non-vertex target."""
    log_path = tmp_path / "standalone.jsonl"
    log_path.write_text('{"kind": "note"}\n', encoding="utf-8")

    with pytest.raises(TargetUnsupported):
        emit_fact(
            log_path,
            "note",
            {"body": "test"},
            observer="tester",
        )


def test_emit_fact_nonexistent_vertex_raises_target_not_found(tmp_path: Path) -> None:
    """emit_fact raises TargetNotFound when the target vertex file does not exist."""
    missing = tmp_path / "ghost.vertex"
    with pytest.raises(TargetNotFound):
        emit_fact(
            missing,
            "note",
            {"body": "test"},
            observer="tester",
        )
