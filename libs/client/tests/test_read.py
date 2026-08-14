"""Integration and contract tests for client read operations."""

from __future__ import annotations

from pathlib import Path

import pytest
from client import (
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    ReadSummary,
    TargetUnsupported,
    emit_fact,
    read_fact_by_id,
    read_facts,
    read_state,
    read_summary,
    read_ticks,
)


@pytest.fixture
def populated_vertex(tmp_path: Path) -> tuple[Path, list[EmitReceipt]]:
    """Create a vertex populated with 15 facts across two kinds and two observers."""
    vertex_path = tmp_path / "multi.vertex"
    vertex_content = """
name "multi"
store ".loops/data/multi.db"

loops {
  task {
    fold {
      items "collect" 100
    }
  }
  note {
    fold {
      items "collect" 100
    }
  }
}
"""
    vertex_path.write_text(vertex_content.strip() + "\n", encoding="utf-8")

    receipts = []
    # Emit 10 tasks (alice) and 5 notes (bob)
    for i in range(10):
        r = emit_fact(
            vertex_path,
            "task",
            {"title": f"Task {i}", "priority": i},
            observer="alice",
            ts=1700000000.0 + i * 10,
        )
        receipts.append(r)

    for i in range(5):
        r = emit_fact(
            vertex_path,
            "note",
            {"body": f"Note {i}"},
            observer="bob",
            ts=1700000200.0 + i * 10,
        )
        receipts.append(r)

    return vertex_path, receipts


# =============================================================================
# 1. read_summary tests
# =============================================================================


def test_read_summary_fresh_vertex(sample_vertex: Path) -> None:
    """Reading summary of a fresh vertex returns zero counts and clean status."""
    summary = read_summary(sample_vertex)
    assert isinstance(summary, ReadSummary)
    assert summary.target_type == "vertex"
    assert summary.fact_total == 0
    assert summary.tick_total == 0
    assert summary.latest_ts is None
    assert summary.kinds == {}


def test_read_summary_populated_vertex(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """Summary of populated vertex reflects exact kind counts and timestamps."""
    vertex_path, _ = populated_vertex
    summary = read_summary(vertex_path)

    assert summary.target_type == "vertex"
    assert summary.fact_total == 15
    assert summary.tick_total >= 0
    assert summary.latest_ts == 1700000240.0
    assert "task" in summary.kinds
    assert summary.kinds["task"]["count"] == 10
    assert "note" in summary.kinds
    assert summary.kinds["note"]["count"] == 5
    assert summary.unfolded_kinds == []


def test_read_summary_unfolded_kinds(sample_vertex: Path) -> None:
    """Undeclared kinds admitted with admit_undeclared show up in unfolded_kinds."""
    emit_fact(
        sample_vertex,
        "ad_hoc_kind",
        {"custom": "value"},
        observer="tester",
        admit_undeclared=True,
    )
    summary = read_summary(sample_vertex)
    assert "ad_hoc_kind" in summary.unfolded_kinds
    assert summary.kinds["ad_hoc_kind"]["count"] == 1


# =============================================================================
# 2. read_facts tests (pagination, ordering, filters)
# =============================================================================


def test_read_facts_pagination(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """read_facts paginates using limit and cursors until exhausted."""
    vertex_path, _ = populated_vertex

    # First page: limit 5 (newest first)
    page1 = read_facts(vertex_path, limit=5, order="newest")
    assert isinstance(page1, FactPageResult)
    assert len(page1.items) == 5
    assert page1.truncated is True
    assert page1.next_cursor is not None

    # Second page: pass next_cursor as 'before' for 'newest' order
    page2 = read_facts(vertex_path, limit=5, before=page1.next_cursor, order="newest")
    assert len(page2.items) == 5
    assert page2.truncated is True
    assert page2.next_cursor is not None

    # Third page
    page3 = read_facts(vertex_path, limit=5, before=page2.next_cursor, order="newest")
    assert len(page3.items) == 5
    assert page3.truncated is False
    assert page3.next_cursor is None

    # Ensure all 15 unique items were read
    all_ids = [item["id"] for item in page1.items + page2.items + page3.items]
    assert len(set(all_ids)) == 15


def test_read_facts_filters(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """read_facts accurately filters by kind and observer."""
    vertex_path, _ = populated_vertex

    # Filter by kind "note"
    note_page = read_facts(vertex_path, kind="note", limit=50)
    assert len(note_page.items) == 5
    assert all(it["kind"] == "note" for it in note_page.items)

    # Filter by observer "alice"
    alice_page = read_facts(vertex_path, observer="alice", limit=50)
    assert len(alice_page.items) == 10
    assert all(it["observer"] == "alice" for it in alice_page.items)


def test_read_facts_ordering(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """read_facts respects order='newest' vs order='oldest'."""
    vertex_path, _ = populated_vertex

    newest_page = read_facts(vertex_path, limit=2, order="newest")
    oldest_page = read_facts(vertex_path, limit=2, order="oldest")

    # Newest items should have higher timestamps than oldest items
    assert newest_page.items[0]["ts"] > oldest_page.items[0]["ts"]


# =============================================================================
# 3. read_state tests
# =============================================================================


def test_read_state_vertex(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """read_state returns declared fold sections and generation metadata."""
    vertex_path, _ = populated_vertex
    state = read_state(vertex_path)

    assert isinstance(state, FoldStateResult)
    assert state.vertex_name == "multi"
    assert "task" in state.sections
    assert "note" in state.sections
    assert state.sections["task"]["count"] == 10
    assert state.sections["note"]["count"] == 5
    assert len(state.sections["task"]["items"]) == 10


def test_read_state_filtered_kind(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """read_state with kind filter extracts only the requested section."""
    vertex_path, _ = populated_vertex
    state = read_state(vertex_path, kind="task")

    assert "task" in state.sections
    assert "note" not in state.sections


def test_read_state_unsupported_on_non_vertex(tmp_path: Path) -> None:
    """read_state raises TargetUnsupported when target is not a .vertex file."""
    log_path = tmp_path / "standalone.jsonl"
    log_path.write_text('{"kind": "test"}\n', encoding="utf-8")

    with pytest.raises(TargetUnsupported):
        read_state(log_path)


# =============================================================================
# 4. read_ticks & read_fact_by_id tests
# =============================================================================


def test_read_ticks(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """read_ticks extracts store ticks and supports optional name filtering."""
    vertex_path, _ = populated_vertex
    ticks = read_ticks(vertex_path)
    assert isinstance(ticks, list)

    # Filter with non-existent tick name
    empty_ticks = read_ticks(vertex_path, name="nonexistent_tick_mark")
    assert empty_ticks == []


def test_read_fact_by_id(populated_vertex: tuple[Path, list[EmitReceipt]]) -> None:
    """read_fact_by_id retrieves facts by full ID and validates prefix behavior."""
    vertex_path, receipts = populated_vertex
    target_receipt = receipts[0]

    # Full ID lookup
    fact = read_fact_by_id(vertex_path, target_receipt.id)
    assert fact is not None
    assert fact["id"] == target_receipt.id
    assert fact["payload"]["title"] == "Task 0"

    # Non-existent ID lookup returns None
    assert read_fact_by_id(vertex_path, "00000000000000000000000000") is None

    # Ambiguous prefix raises ValueError from engine reader
    short_prefix = target_receipt.id[:4]
    with pytest.raises(ValueError) as exc_info:
        read_fact_by_id(vertex_path, short_prefix)
    assert "Ambiguous ID prefix" in str(exc_info.value)
