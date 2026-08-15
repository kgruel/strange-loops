"""Mutation-testing survivor burn-down for sdk.read (first half).

Covers: read_summary, read_facts, read_state, read_ticks, read_fact_by_id,
and the private helpers _ensure_reader, _compute_summary_stats,
_serialize_fold_item, _serialize_fold_section.

Each test pins one specific behavioral claim (default parameter value,
boundary comparison, dict key, ordering, count arithmetic) that a mutmut
survivor showed was unpinned, through the public sdk.read surface only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from custody import ensure_signing_key

from sdk import (
    EmitReceipt,
    FoldStateResult,
    add_kind,
    emit_batch,
    emit_fact,
    read_fact_by_id,
    read_facts,
    read_state,
    read_summary,
    read_ticks,
)


@pytest.fixture
def populated_vertex(tmp_path: Path) -> tuple[Path, list[EmitReceipt]]:
    """Create a vertex populated with 15 facts across two kinds and two observers.

    Mirrors the fixture of the same name in test_read.py (fixtures are not
    shared across test modules without a conftest entry).
    """
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
# read_summary: missing-store early-return field-by-field pin
# =============================================================================


def test_read_summary_missing_store_pins_every_field(tmp_path: Path) -> None:
    """The 'not is_aggregate and canonical missing' early return builds a
    ReadSummary literal with ~13 fields; pin every one so a mutant flipping
    any single field (target_path -> None, unfolded_kinds -> None,
    agreement -> False, ...) is caught.
    """
    vertex_path = tmp_path / "ghost.vertex"
    vertex_path.write_text(
        'name "ghost_name"\nstore ".loops/data/ghost.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    summary = read_summary(vertex_path)
    assert summary.target_type == "vertex"
    assert summary.target_path == str(vertex_path.resolve())
    assert summary.canonical_mode is not None
    assert summary.canonical_path is None or isinstance(summary.canonical_path, str)
    assert summary.declaration_status == "file-pre-genesis"
    assert summary.fact_total == 0
    assert summary.tick_total == 0
    assert summary.latest_ts is None
    assert summary.kinds == {}
    assert summary.unfolded_kinds == []
    assert summary.agreement is True
    assert summary.signed_count == 0
    assert summary.unsigned_count == 0


# =============================================================================
# read_summary: aggregate (combine) branch field-by-field pin
# =============================================================================


def test_read_summary_aggregate_pins_every_field(tmp_path: Path) -> None:
    """The is_aggregate branch builds a second ReadSummary literal from
    vertex_summary()'s raw dict; pin fact_total/tick_total/kinds AND the
    fixed fields (latest_ts, unfolded_kinds, agreement, signed/unsigned)
    that this branch hardcodes.
    """
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\nstore ".loops/data/child.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    emit_fact(child, "task", {"title": "t1"}, observer="alice")
    emit_fact(child, "task", {"title": "t2"}, observer="alice")

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        f'name "aggregate"\ncombine {{\n  vertex "{child}" as="a"\n}}\n',
        encoding="utf-8",
    )

    summary = read_summary(parent)
    assert summary.target_type == "vertex"
    assert summary.fact_total == 2
    assert summary.tick_total == 0
    assert summary.kinds["task"]["count"] == 2
    assert summary.latest_ts is None  # aggregate branch never computes this
    assert summary.unfolded_kinds == []
    assert summary.agreement is True
    assert summary.signed_count == 0
    assert summary.unsigned_count == 2  # aggregate branch: nothing signed, all unsigned


# =============================================================================
# read_summary: normal vertex-with-store branch field-by-field pin
# =============================================================================


def test_read_summary_normal_vertex_pins_every_field(sample_vertex: Path) -> None:
    """The main vertex-with-existing-store return builds a ReadSummary from
    ~13 fields (index_path, canonical_mode fallback text, declaration_status
    fallback text, unfolded_kinds computation, agreement passthrough); pin
    each one.
    """
    emit_fact(sample_vertex, "note", {"body": "hi"}, observer="alice")

    summary = read_summary(sample_vertex)
    assert summary.target_type == "vertex"
    assert summary.target_path == str(sample_vertex.resolve())
    assert summary.canonical_mode == "sqlite"
    assert summary.canonical_path is not None
    assert summary.index_path is not None
    assert summary.declaration_status == "file-pre-genesis"
    assert summary.fact_total == 1
    assert summary.unfolded_kinds == []  # 'note' IS declared
    assert summary.agreement is True


# =============================================================================
# read_summary: bare (.jsonl/.db) store branch field-by-field pin
# =============================================================================


def test_read_summary_bare_store_pins_every_field(tmp_path: Path) -> None:
    """The bare-store return has no declaration_status/unfolded_kinds
    concept (always None/[]) but must still carry the correct target_type,
    target_path, canonical fields, and computed totals.
    """
    from sdk import sync_target

    log = tmp_path / "bare.jsonl"
    log.write_text(
        '{"t":"fact","id":"01FACT00000000000000000001","kind":"task",'
        '"ts":1700000000.0,"observer":"alice","origin":"","payload":"{\\"k\\":\\"v\\"}"}\n',
        encoding="utf-8",
    )
    sync_target(log)

    summary = read_summary(log)
    assert summary.target_type == "jsonl_log"
    assert summary.target_path == str(log.resolve())
    assert summary.canonical_mode == "jsonl"
    assert summary.canonical_path == str(log.resolve())
    assert summary.declaration_status is None
    assert summary.fact_total == 1
    assert summary.kinds["task"]["count"] == 1
    assert summary.unfolded_kinds == []
    assert summary.agreement is True


# =============================================================================
# read_summary: include_internal default + internal-kind filtering
# =============================================================================


def test_read_summary_include_internal_default_excludes_decl_genesis(sample_vertex: Path) -> None:
    """include_internal defaults to False: the `_decl.genesis` row that the
    add_kind ceremony absorbs into the store must not show up in totals or
    kinds unless the caller explicitly opts in.
    """
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "todo", observer="admin")
    emit_fact(sample_vertex, "note", {"body": "hello"}, observer="alice")

    default_summary = read_summary(sample_vertex)
    assert default_summary.fact_total == 1
    assert "_decl.genesis" not in default_summary.kinds

    internal_summary = read_summary(sample_vertex, include_internal=True)
    assert internal_summary.fact_total == 2
    assert "_decl.genesis" in internal_summary.kinds
    assert internal_summary.kinds["_decl.genesis"]["count"] == 1


def test_read_summary_unfolded_kinds_excludes_decl_prefix_even_with_internal(
    sample_vertex: Path,
) -> None:
    """`_decl.*` kinds never land in unfolded_kinds, even when surfaced via
    include_internal=True (they are reserved, not undeclared-admitted).
    """
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "todo", observer="admin")
    emit_fact(sample_vertex, "note", {"body": "hello"}, observer="alice")
    summary = read_summary(sample_vertex, include_internal=True)
    assert "_decl.genesis" not in summary.unfolded_kinds


# =============================================================================
# read_summary / _compute_summary_stats: kind stats, latest_ts, signed counts
# =============================================================================


def test_compute_summary_stats_kind_counts_and_fields(sample_vertex: Path) -> None:
    """Each kind entry carries the exact count plus its own earliest/latest,
    not a value borrowed from another kind or the wrong dict key.
    """
    emit_fact(sample_vertex, "note", {"body": "a"}, observer="alice", ts=1700000000.0)
    emit_fact(sample_vertex, "note", {"body": "b"}, observer="alice", ts=1700000100.0)
    emit_fact(sample_vertex, "note", {"body": "c"}, observer="alice", ts=1700000200.0)

    summary = read_summary(sample_vertex)
    assert summary.kinds["note"]["count"] == 3
    assert summary.kinds["note"]["earliest"] is not None
    assert summary.kinds["note"]["latest"] is not None


def test_compute_summary_stats_latest_ts_is_max_across_kinds(tmp_path: Path) -> None:
    """summary.latest_ts is the MAX timestamp across all kinds, not the min
    and not just the last kind processed in dict-iteration order.
    """
    vertex_path = tmp_path / "two_kind.vertex"
    vertex_path.write_text(
        'name "two_kind"\n'
        'store ".loops/data/two_kind.db"\n'
        "loops {\n"
        "  alpha { fold { items \"collect\" 100 } }\n"
        "  beta { fold { items \"collect\" 100 } }\n"
        "}\n",
        encoding="utf-8",
    )
    # alpha is emitted LAST (dict order) but has the SMALLER timestamp,
    # beta is emitted FIRST but has the LARGER timestamp.
    emit_fact(vertex_path, "beta", {"v": 1}, observer="alice", ts=1700000999.0)
    emit_fact(vertex_path, "alpha", {"v": 1}, observer="alice", ts=1700000001.0)

    summary = read_summary(vertex_path)
    assert summary.latest_ts == 1700000999.0


def test_compute_summary_stats_signed_and_unsigned_counts_not_swapped(
    sample_vertex: Path,
) -> None:
    """signed_count and unsigned_count read distinct tuple positions from
    `StoreReader.signed_counts()`, which returns ``(signed, total)`` — not
    ``(signed, unsigned)`` (see its docstring). An asymmetric split (2
    signed, 1 unsigned, 3 total) catches an index swap that a 1-vs-1 split
    would miss.

    Regression: read.py used to label ``signed_counts[1]`` (the TOTAL fact
    count) as ``unsigned_count``; unsigned is total minus signed.
    """
    ensure_signing_key(sample_vertex, "alice")
    emit_fact(sample_vertex, "note", {"body": "one"}, observer="alice")
    emit_fact(sample_vertex, "note", {"body": "two"}, observer="alice")
    emit_fact(sample_vertex, "note", {"body": "unsigned"}, observer="bob")

    summary = read_summary(sample_vertex)
    assert summary.signed_count == 2
    assert summary.unsigned_count == 1


# =============================================================================
# read_facts: ordering, filters, include_internal, exact-limit boundary
# =============================================================================


def test_read_facts_invalid_order_raises(sample_vertex: Path) -> None:
    from sdk import SdkValueError

    with pytest.raises(SdkValueError):
        read_facts(sample_vertex, order="sideways")


def test_read_facts_exact_limit_is_not_truncated(sample_vertex: Path) -> None:
    """When limit exactly equals the number of matching facts, truncated
    must be False and next_cursor None — not "off by one" true.
    """
    emit_fact(sample_vertex, "note", {"body": "a"}, observer="alice")
    emit_fact(sample_vertex, "note", {"body": "b"}, observer="alice")

    page = read_facts(sample_vertex, limit=2, kind="note")
    assert len(page.items) == 2
    assert page.truncated is False
    assert page.next_cursor is None


def test_read_facts_include_internal_default_excludes_genesis(sample_vertex: Path) -> None:
    """read_facts, like read_summary, hides `_decl.genesis` by default and
    surfaces it only with include_internal=True.
    """
    ensure_signing_key(sample_vertex, "admin")
    add_kind(sample_vertex, "todo", observer="admin")
    emit_fact(sample_vertex, "note", {"body": "a"}, observer="alice")

    default_page = read_facts(sample_vertex, limit=50)
    assert all(it["kind"] != "_decl.genesis" for it in default_page.items)

    internal_page = read_facts(sample_vertex, limit=50, include_internal=True)
    assert any(it["kind"] == "_decl.genesis" for it in internal_page.items)


# =============================================================================
# read_state: kind filter, generation, declaration status, vertex name
# =============================================================================


def test_read_state_generation_defaults_to_empty_mapping_without_as_dict(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    """generation is either `.as_dict()` output (if available) or the raw
    getattr fallback — both branches must be reachable and non-crashing,
    and a populated vertex's generation must be a mapping, not None.
    """
    vertex_path, _ = populated_vertex
    state = read_state(vertex_path)
    assert isinstance(state, FoldStateResult)
    assert isinstance(state.generation, dict)


def test_read_state_declaration_status_present(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    vertex_path, _ = populated_vertex
    state = read_state(vertex_path)
    assert state.declaration_status is not None
    assert state.declaration_status != "unknown"


def test_read_state_missing_store_reports_vertex_name_and_unknown_status(
    tmp_path: Path,
) -> None:
    """On an absent canonical store, read_state still resolves vertex_name
    from the declaration (not the path stem), reports the declaration's own
    status string (not a hardcoded fallback), and returns empty
    sections/generation.
    """
    vertex_path = tmp_path / "ghost.vertex"
    vertex_path.write_text(
        'name "ghost_name"\nstore ".loops/data/ghost.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    state = read_state(vertex_path)
    assert state.vertex_name == "ghost_name"
    assert state.declaration_status == "file-pre-genesis"
    assert state.generation == {}
    assert state.sections == {}


# =============================================================================
# read_ticks: name filter must actually filter, chronological bounds
# =============================================================================


def test_read_ticks_name_filter_no_match_returns_empty(
    populated_vertex: tuple[Path, list[EmitReceipt]],
) -> None:
    """A tick-mark filter that matches nothing returns an empty list — this
    also exercises reader.ticks_between's (0.0, inf) chronological bounds
    and the `name=` passthrough without hitting the real-tick serialization
    path (see KNOWN BUG note below).
    """
    vertex_path, _ = populated_vertex
    assert read_ticks(vertex_path, name="not_a_real_tick_mark") == []
    assert isinstance(read_ticks(vertex_path), list)


def test_read_ticks_on_real_boundary_fire_serializes_ticks(tmp_path: Path) -> None:
    """Regression: read_ticks used `t.as_dict() ... else dict(t)`, but
    engine.tick.Tick exposes `to_dict()` and is not a Mapping, so every
    real boundary-fired tick raised TypeError. Ticks must serialize.
    """
    vertex_path = tmp_path / "bounded.vertex"
    vertex_path.write_text(
        'name "bounded"\n'
        'store ".loops/data/bounded.db"\n'
        "\n"
        "loops {\n"
        "  event {\n"
        '    fold { total "count" }\n'
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    receipt = emit_fact(vertex_path, "event", {"n": 1}, observer="tester")
    assert receipt.tick_mark == "event"

    ticks = read_ticks(vertex_path, name="event")
    assert len(ticks) == 1
    assert ticks[0]["name"] == "event"


# =============================================================================
# read_fact_by_id: aggregate branch, present vs missing
# =============================================================================


def test_read_fact_by_id_aggregate_combine(tmp_path: Path) -> None:
    """read_fact_by_id on a combine-aggregate vertex resolves facts that
    live in a member store, and returns None for an unknown id.
    """
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\nstore ".loops/data/child.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    r = emit_fact(child, "task", {"title": "hello"}, observer="alice")

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        f'name "aggregate"\ncombine {{\n  vertex "{child}" as="a"\n}}\n',
        encoding="utf-8",
    )

    fact = read_fact_by_id(parent, r.id)
    assert fact is not None
    assert fact["id"] == r.id

    assert read_fact_by_id(parent, "00000000000000000000000000") is None


# =============================================================================
# _serialize_fold_item / _serialize_fold_section priority ordering
# =============================================================================


def test_fold_serialization_dict_and_list_branches() -> None:
    """_serialize_fold_item recurses through Mapping and list/tuple branches
    (not just the object-attribute branches already covered elsewhere).
    """
    from sdk.read import _serialize_fold_item

    # Mapping branch: keys stringified, values recursively serialized.
    mapping_item = {"a": 1, "b": [1, 2, 3]}
    result = _serialize_fold_item(mapping_item)
    assert result == {"a": 1, "b": [1, 2, 3]}

    # list/tuple branch.
    list_item = [1, "two", 3.0]
    assert _serialize_fold_item(list_item) == [1, "two", 3.0]
    assert _serialize_fold_item((1, 2)) == [1, 2]

    # Scalar passthrough (no branch matches).
    assert _serialize_fold_item(42) == 42
    assert _serialize_fold_item(None) is None


def test_fold_serialization_section_mapping_and_fallback_branches() -> None:
    """_serialize_fold_section: Mapping branch and the bare-scalar fallback
    (`{"value": section}`) both produce correctly-keyed output.
    """
    from sdk.read import _serialize_fold_section

    mapping_section = {"kind": "m", "count": 2}
    result = _serialize_fold_section(mapping_section)
    assert result == {"kind": "m", "count": 2}

    scalar_section = 7
    fallback_result = _serialize_fold_section(scalar_section)
    assert fallback_result == {"value": 7}


# =============================================================================
# _ensure_reader recovery path via bare stores (emit_batch keeps loop tight)
# =============================================================================


def test_read_summary_bare_jsonl_store_after_multiple_emits(tmp_path: Path) -> None:
    """_ensure_reader recovers/opens a bare jsonl-canonical store correctly:
    fact_total must reflect ALL emitted facts, not an off-by-one subset.
    """
    from sdk import sync_target

    vertex_path = tmp_path / "batchy.vertex"
    vertex_path.write_text(
        'name "batchy"\nstore ".loops/data/batchy.jsonl"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    emit_batch(
        vertex_path,
        [("item", {"n": i}) for i in range(4)],
        observer="alice",
    )
    sync_target(vertex_path)
    summary = read_summary(vertex_path)
    assert summary.fact_total == 4
