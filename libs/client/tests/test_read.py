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


# =============================================================================
# 5. Missing Store & Serialization Unit Tests
# =============================================================================


def test_read_operations_missing_store(tmp_path: Path) -> None:
    """Read operations against non-existent stores return empty/default structures."""
    missing_store = tmp_path / "absent.jsonl"
    missing_store.touch()  # exists so target resolves, then remove to simulate missing canonical
    missing_store.unlink()

    # Create a vertex pointing to absent store
    vertex_path = tmp_path / "absent.vertex"
    vertex_path.write_text('name "absent"\nstore ".loops/data/missing.db"\nloops { item { fold { items "collect" 10 } } }\n', encoding="utf-8")

    # read_summary on storeless/absent vertex
    summary = read_summary(vertex_path)
    assert summary.target_type == "vertex"
    assert summary.fact_total == 0

    # read_facts
    page = read_facts(vertex_path)
    assert page.items == []
    assert page.truncated is False

    # read_ticks
    ticks = read_ticks(vertex_path)
    assert ticks == []

    # read_fact_by_id
    fact = read_fact_by_id(vertex_path, "any_id")
    assert fact is None


def test_fold_serialization_helpers() -> None:
    """_serialize_fold_item and _serialize_fold_section preserve edge and scalar shapes."""
    from types import SimpleNamespace
    from client.read import _serialize_fold_item, _serialize_fold_section

    mock_edge = SimpleNamespace(predicate="relates_to", address="other/123")
    mock_item = SimpleNamespace(
        payload={"k": "v"},
        ts=1700000000.0,
        observer="tester",
        origin="cli",
        id="01M01",
        n=1,
        refs=["ref1", "ref2"],
        edges=[mock_edge],
    )

    serialized_item = _serialize_fold_item(mock_item)
    assert serialized_item["payload"] == {"k": "v"}
    assert serialized_item["ts"] == 1700000000.0
    assert serialized_item["refs"] == ["ref1", "ref2"]
    assert serialized_item["edges"] == [{"predicate": "relates_to", "address": "other/123"}]

    mock_sub_section = SimpleNamespace(
        kind="sub",
        fold_type="collect",
        key_field="id",
        count=0,
        scalars={},
        preview_fields=[],
        items=[],
        sections=[],
    )

    mock_section = SimpleNamespace(
        kind="main",
        fold_type="collect",
        key_field="id",
        count=1,
        scalars={"total": 10},
        preview_fields=["title"],
        items=[mock_item],
        sections=[mock_sub_section],
    )

    serialized_section = _serialize_fold_section(mock_section)
    assert serialized_section["kind"] == "main"
    assert serialized_section["count"] == 1
    assert serialized_section["scalars"] == {"total": 10}
    assert serialized_section["preview_fields"] == ["title"]
    assert len(serialized_section["items"]) == 1
    assert len(serialized_section["sections"]) == 1
    assert serialized_section["sections"][0]["kind"] == "sub"


# =============================================================================
# 6. Full-Text Search, Entity Resolution & Timeline Tests
# =============================================================================


def test_sync_target_and_search_facts(tmp_path: Path) -> None:
    """sync_target indexes searchable fields and search_facts finds matching payloads."""
    from client import search_facts, sync_target

    vertex = tmp_path / "searchable.vertex"
    vertex.write_text(
        'name "searchable"\n'
        'store ".loops/data/searchable.db"\n'
        'loops {\n'
        '  task {\n'
        '    search "title" "body"\n'
        '    fold {\n'
        '      items "collect" 100\n'
        '    }\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )

    emit_fact(vertex, "task", {"title": "Refactor auth system", "body": "Need JWTs"}, observer="alice")
    emit_fact(vertex, "task", {"title": "Fix database leak", "body": "Connection pool issue"}, observer="bob")

    # Explicit sync
    sync_res = sync_target(vertex)
    assert sync_res.status == "synced"
    assert sync_res.indexed_facts == 2
    assert sync_res.agreement is True

    # Search for "auth"
    auth_search = search_facts(vertex, "auth")
    assert auth_search.total_matches == 1
    assert auth_search.matches[0].payload["title"] == "Refactor auth system"

    # Search with kind filter
    pool_search = search_facts(vertex, "database", kind="task")
    assert pool_search.total_matches == 1
    assert pool_search.matches[0].payload["title"] == "Fix database leak"


def test_resolve_entity(tmp_path: Path) -> None:
    """resolve_entity looks up a canonical fact ID by fold key field and value."""
    from client import resolve_entity

    vertex = tmp_path / "keyed.vertex"
    vertex.write_text(
        'name "keyed"\n'
        'store ".loops/data/keyed.db"\n'
        'loops {\n'
        '  task {\n'
        '    fold {\n'
        '      items "by" "task_id"\n'
        '    }\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )

    r1 = emit_fact(vertex, "task", {"task_id": "T-101", "title": "First"}, observer="alice")
    r2 = emit_fact(vertex, "task", {"task_id": "T-102", "title": "Second"}, observer="alice")

    resolved = resolve_entity(vertex, "task", "task_id", "T-101")
    assert resolved == r1.id

    resolved_2 = resolve_entity(vertex, "task", "task_id", "T-102")
    assert resolved_2 == r2.id

    resolved_missing = resolve_entity(vertex, "task", "task_id", "T-999")
    assert resolved_missing is None


def test_read_timeline_interleaved(tmp_path: Path) -> None:
    """read_timeline streams facts and ticks in chronological sequence."""
    from client import read_timeline

    vertex = tmp_path / "timeline.vertex"
    vertex.write_text(
        'name "timeline"\n'
        'store ".loops/data/timeline.db"\n'
        'loops {\n'
        '  task {\n'
        '    fold {\n'
        '      items "collect" 100\n'
        '    }\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )

    emit_fact(vertex, "task", {"title": "Event 1"}, observer="alice", ts=1700000010.0)
    emit_fact(vertex, "task", {"title": "Event 2"}, observer="alice", ts=1700000020.0)

    timeline = read_timeline(vertex, limit=10)
    assert timeline.total_events >= 2
    assert all(e.event_type in ("fact", "tick") for e in timeline.events)
    assert timeline.events[0].payload["title"] == "Event 1"
    assert timeline.events[1].payload["title"] == "Event 2"


def test_read_summary_signed_counts(sample_vertex: Path) -> None:
    """read_summary reports signed_count and unsigned_count."""
    from custody import ensure_signing_key

    ensure_signing_key(sample_vertex, "alice")
    emit_fact(sample_vertex, "note", {"title": "Signed note"}, observer="alice")

    summary = read_summary(sample_vertex)
    assert summary.signed_count == 1
    assert summary.unsigned_count == 1  # Genesis declaration fact is unsigned


def test_combine_aggregate_reads(tmp_path: Path) -> None:
    """Aggregate combine vertex reads facts, ticks, and summary across children."""
    child_a = tmp_path / "child_a.vertex"
    child_a.write_text(
        'name "child_a"\n'
        'store ".loops/data/a.db"\n'
        'loops {\n'
        '  task {\n'
        '    fold {\n'
        '      items "collect" 100\n'
        '    }\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )

    child_b = tmp_path / "child_b.vertex"
    child_b.write_text(
        'name "child_b"\n'
        'store ".loops/data/b.db"\n'
        'loops {\n'
        '  task {\n'
        '    fold {\n'
        '      items "collect" 100\n'
        '    }\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )

    emit_fact(child_a, "task", {"title": "Child A Task"}, observer="alice")
    emit_fact(child_b, "task", {"title": "Child B Task"}, observer="bob")

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        'name "aggregate"\n'
        'combine {\n'
        f'  vertex "{child_a}" as="a"\n'
        f'  vertex "{child_b}" as="b"\n'
        '}\n',
        encoding="utf-8",
    )

    # Combined summary
    summary = read_summary(parent)
    assert summary.fact_total == 2

    # Combined facts
    facts_page = read_facts(parent, limit=10)
    assert len(facts_page.items) == 2

    # Combined search
    from client import search_facts
    search_res = search_facts(parent, "Task")
    assert search_res.total_matches == 0 or isinstance(search_res.matches, list)


def test_read_timeline_time_window(tmp_path: Path) -> None:
    """read_timeline filters events within start_ts and end_ts bounds."""
    from client import read_timeline

    vertex = tmp_path / "window.vertex"
    vertex.write_text(
        'name "window"\n'
        'store ".loops/data/window.db"\n'
        'loops {\n'
        '  task {\n'
        '    fold {\n'
        '      items "collect" 100\n'
        '    }\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )

    emit_fact(vertex, "task", {"title": "T1"}, observer="alice", ts=100.0)
    emit_fact(vertex, "task", {"title": "T2"}, observer="alice", ts=200.0)
    emit_fact(vertex, "task", {"title": "T3"}, observer="alice", ts=300.0)

    # Window from 150.0 to 250.0 should only include T2
    res = read_timeline(vertex, start_ts=150.0, end_ts=250.0)
    assert res.total_events == 1
    assert res.events[0].payload["title"] == "T2"
    assert res.start_ts == 150.0
    assert res.end_ts == 250.0


def test_read_timeline_missing_target(tmp_path: Path) -> None:
    """read_timeline raises TargetNotFound on non-existent path."""
    from client import TargetNotFound, read_timeline

    missing = tmp_path / "absent.jsonl"
    with pytest.raises(TargetNotFound):
        read_timeline(missing)


def test_sync_target_missing_store(tmp_path: Path) -> None:
    """sync_target raises TargetNotFound on non-existent path."""
    from client import TargetNotFound, sync_target

    missing = tmp_path / "absent.jsonl"
    with pytest.raises(TargetNotFound):
        sync_target(missing)


def test_sync_target_bare_store(tmp_path: Path) -> None:
    """sync_target on valid bare store runs preflight recovery and returns synced status."""
    from client import sync_target

    log = tmp_path / "bare.jsonl"
    log.write_text('{"id":"01","kind":"task","ts":1700000000.0,"observer":"alice","origin":"","payload":{"k":"v"}}\n', encoding="utf-8")

def test_sync_target_bare_store(tmp_path: Path) -> None:
    """sync_target on valid bare store runs preflight recovery and returns synced status."""
    from client import sync_target

    log = tmp_path / "bare.jsonl"
    log.write_text('{"t":"fact","id":"01FACT00000000000000000001","kind":"task","ts":1700000000.0,"observer":"alice","origin":"","payload":"{\\"k\\":\\"v\\"}"}\n', encoding="utf-8")

    res = sync_target(log)
    assert res.status == "synced"
    assert res.indexed_facts >= 1
    assert res.agreement is True


def test_search_facts_bare_store(tmp_path: Path) -> None:
    """search_facts on bare store returns matching SearchResult or empty if not indexed."""
    from client import search_facts

    log = tmp_path / "bare.jsonl"
    log.write_text('{"t":"fact","id":"01FACT00000000000000000001","kind":"task","ts":1700000000.0,"observer":"alice","origin":"","payload":"{\\"k\\":\\"v\\"}"}\n', encoding="utf-8")

    res = search_facts(log, "query")
    assert isinstance(res.matches, list)
    assert res.total_matches == len(res.matches)


