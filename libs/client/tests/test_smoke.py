"""End-to-end smoke tests for client operations (read, emit, kind mutations)."""

from __future__ import annotations

from pathlib import Path

import pytest

from client import (
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    KindMutationResult,
    ReadSummary,
    TargetNotFound,
    TargetUnsupported,
    add_kind,
    emit_fact,
    read_facts,
    read_state,
    read_summary,
    resolve_target,
)


def test_target_resolution(sample_vertex: Path, tmp_path: Path):
    # Valid vertex
    info = resolve_target(sample_vertex)
    assert info.target_type == "vertex"
    assert info.exists is True

    # Missing target
    missing = tmp_path / "nonexistent.vertex"
    with pytest.raises(TargetNotFound):
        resolve_target(missing)

    # Unsupported target
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello", encoding="utf-8")
    with pytest.raises(TargetUnsupported):
        resolve_target(text_file)


def test_emit_and_read_roundtrip(sample_vertex: Path):
    # Initial read summary before emit
    summary = read_summary(sample_vertex)
    assert isinstance(summary, ReadSummary)
    assert summary.target_type == "vertex"

    # Emit a fact
    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "First Note", "body": "Testing client emit"},
        observer="tester",
    )
    assert isinstance(receipt, EmitReceipt)
    assert receipt.stored is True
    assert receipt.id != ""
    assert receipt.observer == "tester"

    # Read summary after emit
    summary_after = read_summary(sample_vertex)
    assert summary_after.fact_total >= 1
    assert "note" in summary_after.kinds
    assert summary_after.kinds["note"]["count"] == 1

    # Read facts page
    page = read_facts(sample_vertex, limit=10)
    assert isinstance(page, FactPageResult)
    assert len(page.items) == 1
    assert page.items[0]["kind"] == "note"
    assert page.items[0]["payload"]["title"] == "First Note"

    # Read fold state
    state = read_state(sample_vertex)
    assert isinstance(state, FoldStateResult)
    assert "note" in state.sections


def test_jsonl_emit_and_read(jsonl_vertex: Path):
    receipt = emit_fact(
        jsonl_vertex,
        "entry",
        {"message": "JSONL test"},
        observer="tester",
    )
    assert receipt.stored is True

    summary = read_summary(jsonl_vertex)
    assert summary.canonical_mode == "jsonl"
    assert summary.fact_total >= 1
    assert summary.agreement is True

    # Read bare jsonl log directly
    log_path = Path(summary.canonical_path)
    bare_summary = read_summary(log_path)
    assert bare_summary.target_type == "jsonl_log"
    assert bare_summary.fact_total >= 1


def test_add_kind_ceremony(sample_vertex: Path):
    from custody import ensure_signing_key

    ensure_signing_key(sample_vertex, "admin")

    # Add a new kind 'task'
    result = add_kind(
        sample_vertex,
        "task",
        observer="admin",
    )
    assert isinstance(result, KindMutationResult)
    assert result.status in ("applied", "noop")
    assert result.file_written is True

    # Check updated text and fold state
    state = read_state(sample_vertex)
    assert "task" in state.sections
    assert "note" in state.sections
