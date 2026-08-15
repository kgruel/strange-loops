"""Mutation-testing survivor burn-down for sdk.read (second half).

Covers: search_facts, resolve_entity, read_timeline, sync_target.

Each test pins one specific behavioral claim (default parameter value,
boundary comparison, dict key, ordering, count arithmetic) that a mutmut
survivor showed was unpinned, through the public sdk surface only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sdk import (
    EmitReceipt,
    SearchResult,
    SyncResult,
    TimelineResult,
    emit_fact,
    read_timeline,
    resolve_entity,
    search_facts,
    sync_target,
)


@pytest.fixture
def populated_vertex(tmp_path: Path) -> tuple[Path, list[EmitReceipt]]:
    """Vertex with 10 task facts (alice) and 5 note facts (bob)."""
    vertex_path = tmp_path / "multi.vertex"
    vertex_content = """
name "multi"
store ".loops/data/multi.db"

loops {
  task {
    search "title"
    fold {
      items "collect" 100
    }
  }
  note {
    search "body"
    fold {
      items "collect" 100
    }
  }
}
"""
    vertex_path.write_text(vertex_content.strip() + "\n", encoding="utf-8")

    receipts = []
    for i in range(10):
        r = emit_fact(
            vertex_path,
            "task",
            {"title": f"Widget Task {i}", "priority": i},
            observer="alice",
            ts=1700000000.0 + i * 10,
        )
        receipts.append(r)

    for i in range(5):
        r = emit_fact(
            vertex_path,
            "note",
            {"body": f"Widget Note {i}"},
            observer="bob",
            ts=1700000200.0 + i * 10,
        )
        receipts.append(r)

    return vertex_path, receipts


# =============================================================================
# search_facts
# =============================================================================


def test_search_facts_returns_search_result_type_and_query_echo(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    sync_target(vertex_path)
    result = search_facts(vertex_path, "Task")
    assert isinstance(result, SearchResult)
    assert result.query == "Task"


def test_search_facts_total_matches_equals_len_matches(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    sync_target(vertex_path)
    result = search_facts(vertex_path, "Task")
    assert result.total_matches == len(result.matches)
    assert result.total_matches > 0


def test_search_facts_kind_filter_excludes_other_kinds(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    sync_target(vertex_path)
    unfiltered = search_facts(vertex_path, "Widget")
    filtered = search_facts(vertex_path, "Widget", kind="note")
    assert filtered.total_matches > 0
    assert all(item.kind == "note" for item in filtered.matches)
    # Both kinds mention "Widget"; the kind filter must actually narrow results.
    assert filtered.total_matches < unfiltered.total_matches


def test_search_facts_limit_caps_matches(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    sync_target(vertex_path)
    result = search_facts(vertex_path, "Widget", limit=2)
    assert len(result.matches) == 2
    assert result.total_matches == 2


def test_search_facts_default_limit_is_50(tmp_path: Path) -> None:
    """Pin the default limit=50 param value: 60 matching facts, no limit given."""
    vertex_path = tmp_path / "many.vertex"
    vertex_path.write_text(
        'name "many"\nstore ".loops/data/many.db"\n'
        'loops { item { search "label" fold { items "collect" 200 } } }\n',
        encoding="utf-8",
    )
    for i in range(60):
        emit_fact(
            vertex_path,
            "item",
            {"label": f"needle {i}"},
            observer="a",
            ts=1700000000.0 + i,
        )
    sync_target(vertex_path)
    result = search_facts(vertex_path, "needle")
    assert len(result.matches) == 50
    assert result.total_matches == 50


def test_search_facts_no_match_returns_empty(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    sync_target(vertex_path)
    result = search_facts(vertex_path, "zzz_nonexistent_zzz")
    assert result.matches == []
    assert result.total_matches == 0


def test_search_facts_item_fields_populated(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    sync_target(vertex_path)
    result = search_facts(vertex_path, "Task 3")
    assert result.total_matches >= 1
    item = result.matches[0]
    assert item.kind == "task"
    assert item.observer == "alice"
    assert isinstance(item.payload, dict)
    assert "Task 3" in item.payload.get("title", "")
    assert item.ts > 0
    assert item.rank == 0.0
    assert item.snippet == ""
    assert item.origin == ""


def test_search_facts_on_bare_jsonl_store(tmp_path: Path) -> None:
    """Exercise the non-vertex (bare store) branch of search_facts.

    StoreReader.search_facts returns list[dict] (not attribute-bearing
    objects), so this walks the m.get(...) fallback side of every
    hasattr(m, ...) branch in the bare-store loop -- and payload comes back
    as a JSON string, exercising the json.loads() decode path too.
    """
    store_path = tmp_path / "bare.jsonl"
    vertex_path = tmp_path / "bare.vertex"
    vertex_path.write_text(
        f'name "bare"\nstore "{store_path.name}"\n'
        'loops { widget { search "label" fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    emit_fact(vertex_path, "widget", {"label": "gizmo"}, observer="carol", ts=1700000000.0)
    sync_target(vertex_path)
    result = search_facts(store_path, "gizmo")
    assert isinstance(result, SearchResult)
    assert result.query == "gizmo"
    assert result.total_matches == len(result.matches)
    assert result.total_matches == 1
    item = result.matches[0]
    assert item.kind == "widget"
    assert item.observer == "carol"
    assert item.origin == ""
    assert item.ts == 1700000000.0
    assert isinstance(item.payload, dict)
    assert item.payload.get("label") == "gizmo"
    assert item.rank == 0.0
    assert item.snippet == ""


def test_search_facts_bare_store_kind_filter_narrows_results(tmp_path: Path) -> None:
    """kind= must be forwarded through to reader.search_facts on the bare
    (non-vertex) branch, not silently dropped or replaced with None.
    """
    store_path = tmp_path / "twokind.jsonl"
    vertex_path = tmp_path / "twokind.vertex"
    vertex_path.write_text(
        f'name "twokind"\nstore "{store_path.name}"\n'
        "loops {\n"
        '  alpha { search "label" fold { items "collect" 10 } }\n'
        '  beta { search "label" fold { items "collect" 10 } }\n'
        "}\n",
        encoding="utf-8",
    )
    emit_fact(vertex_path, "alpha", {"label": "shared term"}, observer="a", ts=1700000000.0)
    emit_fact(vertex_path, "beta", {"label": "shared term"}, observer="b", ts=1700000100.0)
    sync_target(vertex_path)

    unfiltered = search_facts(store_path, "shared")
    filtered = search_facts(store_path, "shared", kind="alpha")
    assert unfiltered.total_matches == 2
    assert filtered.total_matches == 1
    assert filtered.matches[0].kind == "alpha"


def test_search_facts_invalid_query_raises_sdk_error_with_context(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    """A malformed FTS5 query raises SdkError with the target path and
    underlying exception text folded into the message, not a bare/None one.
    """
    from sdk import SdkError

    vertex_path, _ = populated_vertex
    sync_target(vertex_path)
    with pytest.raises(SdkError, match="full-text search failed on"):
        search_facts(vertex_path, '"unbalanced')


def test_search_facts_bare_store_invalid_query_raises_sdk_error(tmp_path: Path) -> None:
    from sdk import SdkError

    store_path = tmp_path / "bare.jsonl"
    vertex_path = tmp_path / "bare.vertex"
    vertex_path.write_text(
        f'name "bare"\nstore "{store_path.name}"\n'
        'loops { widget { search "label" fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    emit_fact(vertex_path, "widget", {"label": "gizmo"}, observer="carol", ts=1700000000.0)
    sync_target(vertex_path)
    with pytest.raises(SdkError, match="full-text search failed on"):
        search_facts(store_path, '"unbalanced')


def test_search_facts_bare_store_no_fts_generation_returns_empty(tmp_path: Path) -> None:
    """A never-synced bare store (no facts_fts table) short-circuits to empty."""
    store_path = tmp_path / "unindexed.jsonl"
    store_path.write_text(
        '{"t":"fact","id":"01FACT00000000000000000001","kind":"task",'
        '"ts":1700000000.0,"observer":"alice","origin":"","payload":"{}"}\n',
        encoding="utf-8",
    )
    result = search_facts(store_path, "anything")
    assert result.matches == []
    assert result.total_matches == 0
    assert result.query == "anything"


# =============================================================================
# resolve_entity
# =============================================================================


def test_resolve_entity_finds_matching_fact_id(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, receipts = populated_vertex
    fact_id = resolve_entity(vertex_path, "task", "title", "Widget Task 3")
    assert fact_id == receipts[3].id


def test_resolve_entity_no_match_returns_none(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    assert resolve_entity(vertex_path, "task", "title", "does-not-exist") is None


def test_resolve_entity_missing_canonical_returns_none(tmp_path: Path) -> None:
    """A declared-but-never-emitted vertex has no canonical store -> None."""
    vertex_path = tmp_path / "ghost.vertex"
    vertex_path.write_text(
        'name "ghost"\nstore ".loops/data/ghost.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    assert resolve_entity(vertex_path, "item", "key", "value") is None


def test_resolve_entity_aggregate_combine_finds_latest_across_children(
    tmp_path: Path,
) -> None:
    """Combine vertex: is_aggregate branch resolves entities across member
    stores, walking facts in reverse to find the LATEST match by kind/key.
    """
    child_a = tmp_path / "child_a.vertex"
    child_a.write_text(
        'name "child_a"\nstore ".loops/data/a.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    child_b = tmp_path / "child_b.vertex"
    child_b.write_text(
        'name "child_b"\nstore ".loops/data/b.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    r1 = emit_fact(
        child_a, "task", {"key": "x", "v": 1}, observer="alice", ts=1700000000.0
    )
    r2 = emit_fact(
        child_b, "task", {"key": "x", "v": 2}, observer="bob", ts=1700000100.0
    )

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        'name "aggregate"\n'
        "combine {\n"
        f'  vertex "{child_a}" as="a"\n'
        f'  vertex "{child_b}" as="b"\n'
        "}\n",
        encoding="utf-8",
    )

    fact_id = resolve_entity(parent, "task", "key", "x")
    # Reversed iteration means the last-appended (most recent) fact wins.
    assert fact_id == r2.id
    assert fact_id != r1.id


def test_resolve_entity_aggregate_combine_kind_filter_and_zero_ts_boundary(
    tmp_path: Path,
) -> None:
    """The aggregate branch's vertex_facts(kind=kind) call must actually
    filter by kind, and its since_ts=0.0 lower bound must include a fact
    emitted exactly at ts=0.0 (a since_ts=1.0 mutant would exclude it).
    """
    child_a = tmp_path / "child_a.vertex"
    child_a.write_text(
        'name "child_a"\nstore ".loops/data/a.db"\n'
        "loops {\n"
        '  task { fold { items "collect" 100 } }\n'
        '  note { fold { items "collect" 100 } }\n'
        "}\n",
        encoding="utf-8",
    )
    task_r = emit_fact(child_a, "task", {"key": "x"}, observer="alice", ts=0.0)
    emit_fact(child_a, "note", {"key": "x"}, observer="alice", ts=1700000000.0)

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        'name "aggregate"\ncombine {\n' f'  vertex "{child_a}" as="a"\n' "}\n",
        encoding="utf-8",
    )
    # kind filter must exclude the "note" fact even though it shares key "x".
    assert resolve_entity(parent, "task", "key", "x") == task_r.id
    # since_ts=0.0 lower bound must include the ts=0.0 fact.
    assert resolve_entity(parent, "task", "key", "x") is not None


def test_resolve_entity_aggregate_combine_no_match_returns_none(
    tmp_path: Path,
) -> None:
    child_a = tmp_path / "child_a.vertex"
    child_a.write_text(
        'name "child_a"\nstore ".loops/data/a.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    emit_fact(child_a, "task", {"key": "x"}, observer="alice", ts=1700000000.0)

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        'name "aggregate"\ncombine {\n' f'  vertex "{child_a}" as="a"\n' "}\n",
        encoding="utf-8",
    )
    assert resolve_entity(parent, "task", "key", "does-not-exist") is None


def test_resolve_entity_returns_latest_when_multiple_match(tmp_path: Path) -> None:
    """Multiple facts sharing the same key value: resolve to the most recent."""
    vertex_path = tmp_path / "dup.vertex"
    vertex_path.write_text(
        'name "dup"\nstore ".loops/data/dup.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    emit_fact(vertex_path, "item", {"key": "x", "v": 1}, observer="a", ts=1700000000.0)
    r2 = emit_fact(vertex_path, "item", {"key": "x", "v": 2}, observer="a", ts=1700000100.0)
    fact_id = resolve_entity(vertex_path, "item", "key", "x")
    assert fact_id == r2.id


# =============================================================================
# read_timeline
# =============================================================================


def test_read_timeline_invalid_order_raises() -> None:
    from sdk import SdkValueError

    with pytest.raises(SdkValueError, match="invalid order 'sideways'"):
        read_timeline(Path("does-not-matter.vertex"), order="sideways")


def test_read_timeline_default_limit_is_100(tmp_path: Path) -> None:
    """Pin the default limit=100 param value with 120 facts, no limit given."""
    vertex_path = tmp_path / "many.vertex"
    vertex_path.write_text(
        'name "many"\nstore ".loops/data/many.db"\n'
        'loops { item { fold { items "collect" 200 } } }\n',
        encoding="utf-8",
    )
    for i in range(120):
        emit_fact(vertex_path, "item", {"n": i}, observer="a", ts=1700000000.0 + i)
    result = read_timeline(vertex_path)
    assert len(result.events) == 100
    assert result.total_events == 120
    assert result.truncated is True


def test_read_timeline_aggregate_combine_merges_children(tmp_path: Path) -> None:
    """The is_aggregate branch (decl_ast.combine is not None) must actually
    trigger on a combine vertex -- a mutant flipping `and` -> `or` or
    `is not None` -> `is None` on the is_aggregate computation would make
    a plain non-aggregate store take this branch (or vice versa), which
    empty-vs-nonempty totals will catch.
    """
    child_a = tmp_path / "child_a.vertex"
    child_a.write_text(
        'name "child_a"\nstore ".loops/data/a.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    child_b = tmp_path / "child_b.vertex"
    child_b.write_text(
        'name "child_b"\nstore ".loops/data/b.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    emit_fact(child_a, "task", {"title": "A"}, observer="alice", ts=1700000000.0)
    emit_fact(child_b, "task", {"title": "B"}, observer="bob", ts=1700000100.0)

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        'name "aggregate"\n'
        "combine {\n"
        f'  vertex "{child_a}" as="a"\n'
        f'  vertex "{child_b}" as="b"\n'
        "}\n",
        encoding="utf-8",
    )
    result = read_timeline(parent, limit=1000)
    assert result.total_events == 2
    assert {e.observer for e in result.events} == {"alice", "bob"}


def test_read_timeline_missing_canonical_returns_empty_result(tmp_path: Path) -> None:
    vertex_path = tmp_path / "ghost.vertex"
    vertex_path.write_text(
        'name "ghost"\nstore ".loops/data/ghost.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    result = read_timeline(vertex_path)
    assert isinstance(result, TimelineResult)
    assert result.events == []
    assert result.total_events == 0
    assert result.truncated is False
    assert result.order == "oldest"


def test_read_timeline_returns_all_fact_events_in_oldest_order(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, receipts = populated_vertex
    result = read_timeline(vertex_path, limit=1000)
    assert result.total_events == len(receipts)
    assert len(result.events) == len(receipts)
    fact_events = [e for e in result.events if e.event_type == "fact"]
    assert len(fact_events) == len(receipts)
    # oldest first: timestamps should be non-decreasing
    timestamps = [e.ts for e in result.events]
    assert timestamps == sorted(timestamps)


def test_read_timeline_newest_order_reverses(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    result = read_timeline(vertex_path, limit=1000, order="newest")
    timestamps = [e.ts for e in result.events]
    assert timestamps == sorted(timestamps, reverse=True)
    assert result.order == "newest"


def test_read_timeline_limit_truncates_and_flags_truncated(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, receipts = populated_vertex
    result = read_timeline(vertex_path, limit=3)
    assert len(result.events) == 3
    assert result.total_events == len(receipts)
    assert result.truncated is True


def test_read_timeline_no_truncation_when_limit_covers_all(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, receipts = populated_vertex
    result = read_timeline(vertex_path, limit=len(receipts))
    assert result.truncated is False
    assert len(result.events) == len(receipts)


def test_read_timeline_start_end_ts_filters_events(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    # task facts run ts 1700000000..1700000090; note facts 1700000200..1700000240
    result = read_timeline(
        vertex_path, start_ts=1700000200.0, end_ts=1700000240.0, limit=1000
    )
    assert result.total_events == 5
    assert all(e.kind_or_name == "note" for e in result.events)
    assert result.start_ts == 1700000200.0
    assert result.end_ts == 1700000240.0


def test_read_timeline_event_fields_populated(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, receipts = populated_vertex
    result = read_timeline(vertex_path, limit=1000)
    task_events = [e for e in result.events if e.kind_or_name == "task"]
    assert task_events
    ev = task_events[0]
    assert ev.event_type == "fact"
    assert ev.observer == "alice"
    assert ev.origin == ""
    assert ev.id == receipts[0].id
    assert ev.ts == 1700000000.0
    assert isinstance(ev.payload, dict)
    assert ev.payload == {"title": "Widget Task 0", "priority": 0}


def test_read_timeline_vertex_tick_event_fields_pinned(tmp_path: Path) -> None:
    """A sealed boundary tick produces a 'tick' TimelineEvent alongside the
    fact event; pin every field the tick-extraction branch derives (this
    was entirely unexercised by fact-only fixtures).
    """
    vertex_path = tmp_path / "tick.vertex"
    vertex_path.write_text(
        'name "tick"\nstore ".loops/data/t.db"\n'
        "loops {\n"
        "  task {\n"
        '    fold { items "collect" 100 }\n'
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    emit_fact(vertex_path, "task", {"title": "a"}, observer="alice", ts=1700000000.0)
    result = read_timeline(vertex_path, limit=1000)
    assert result.total_events == 2

    fact_events = [e for e in result.events if e.event_type == "fact"]
    tick_events = [e for e in result.events if e.event_type == "tick"]
    assert len(fact_events) == 1
    assert len(tick_events) == 1

    fe = fact_events[0]
    assert fe.kind_or_name == "task"
    assert fe.ts == 1700000000.0
    assert fe.observer == "alice"
    assert fe.origin == ""
    assert fe.payload == {"title": "a"}

    te = tick_events[0]
    assert te.kind_or_name == "task"
    assert te.ts == 1700000000.0
    assert te.observer == ""
    assert te.origin == ""
    assert te.payload == {"items": [{"title": "a", "_ts": 1700000000.0}]}


def test_read_timeline_bare_store_tick_event_fields_pinned(tmp_path: Path) -> None:
    """Same tick-field pin as the vertex branch, but through the bare-store
    (reader.ticks_between) code path, which is a separately mutated block.
    """
    store_path = tmp_path / "tick.jsonl"
    vertex_path = tmp_path / "tick.vertex"
    vertex_path.write_text(
        f'name "tick"\nstore "{store_path.name}"\n'
        "loops {\n"
        "  task {\n"
        '    fold { items "collect" 100 }\n'
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    emit_fact(vertex_path, "task", {"title": "a"}, observer="alice", ts=1700000000.0)
    result = read_timeline(store_path, limit=1000)
    assert result.total_events == 2

    fact_events = [e for e in result.events if e.event_type == "fact"]
    tick_events = [e for e in result.events if e.event_type == "tick"]
    assert len(fact_events) == 1
    assert len(tick_events) == 1

    fe = fact_events[0]
    assert fe.kind_or_name == "task"
    assert fe.ts == 1700000000.0
    assert fe.observer == "alice"
    assert fe.origin == ""
    assert fe.payload == {"title": "a"}

    te = tick_events[0]
    assert te.kind_or_name == "task"
    assert te.ts == 1700000000.0
    assert te.observer == ""
    assert te.origin == ""
    assert te.payload == {"items": [{"title": "a", "_ts": 1700000000.0}]}


def test_read_timeline_on_bare_jsonl_store(tmp_path: Path) -> None:
    """Exercise the non-vertex (bare store) branch of read_timeline."""
    store_path = tmp_path / "bare.jsonl"
    vertex_path = tmp_path / "bare.vertex"
    vertex_path.write_text(
        f'name "bare"\nstore "{store_path.name}"\n'
        'loops { widget { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    r = emit_fact(vertex_path, "widget", {"label": "gizmo"}, observer="carol", ts=1700000000.0)
    sync_target(store_path)
    result = read_timeline(store_path, limit=1000)
    assert result.total_events == 1
    ev = result.events[0]
    assert ev.kind_or_name == "widget"
    assert ev.observer == "carol"
    assert ev.origin == ""
    assert ev.id == r.id
    assert ev.ts == 1700000000.0
    assert ev.payload == {"label": "gizmo"}


# =============================================================================
# sync_target
# =============================================================================


def test_sync_target_vertex_returns_sync_result(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, receipts = populated_vertex
    result = sync_target(vertex_path)
    assert isinstance(result, SyncResult)
    assert result.target_path == str(vertex_path.resolve())
    assert result.agreement is True
    assert result.duration_ms >= 0.0


def test_sync_target_bare_store_status_and_agreement(tmp_path: Path) -> None:
    store_path = tmp_path / "bare.jsonl"
    vertex_path = tmp_path / "bare.vertex"
    vertex_path.write_text(
        f'name "bare"\nstore "{store_path.name}"\n'
        'loops { widget { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    emit_fact(vertex_path, "widget", {"label": "gizmo"}, observer="carol", ts=1700000000.0)
    result = sync_target(store_path)
    assert result.status == "synced"
    assert result.target_path == str(store_path.resolve())
    assert result.indexed_facts == 1
    assert result.agreement is True
    assert result.duration_ms >= 0.0


def test_sync_target_bare_store_indexed_facts_matches_total(tmp_path: Path) -> None:
    """indexed_facts reflects reader.fact_total, not a hardcoded literal."""
    store_path = tmp_path / "three.jsonl"
    vertex_path = tmp_path / "three.vertex"
    vertex_path.write_text(
        f'name "three"\nstore "{store_path.name}"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    for i in range(3):
        emit_fact(vertex_path, "item", {"n": i}, observer="a", ts=1700000000.0 + i)
    result = sync_target(store_path)
    assert result.status == "synced"
    assert result.indexed_facts == 3
    assert result.target_path == str(store_path.resolve())


def test_sync_target_vertex_kind_without_search_is_unindexed(tmp_path: Path) -> None:
    """A vertex with no `search` field declared on any kind: vertex_reindex
    reports reindexed=False, so status is 'unindexed' (not 'synced'), and
    indexed_facts stays 0 -- pins the ternary AND its false-branch literal.
    """
    vertex_path = tmp_path / "nosearch.vertex"
    vertex_path.write_text(
        'name "nosearch"\nstore ".loops/data/n.db"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    emit_fact(vertex_path, "item", {"label": "x"}, observer="a", ts=1700000000.0)
    result = sync_target(vertex_path)
    assert result.status == "unindexed"
    assert result.indexed_facts == 0
    assert result.agreement is True


def test_sync_target_vertex_with_search_is_synced_and_counts_facts(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, receipts = populated_vertex
    result = sync_target(vertex_path)
    assert result.status == "synced"
    assert result.indexed_facts == len(receipts)
