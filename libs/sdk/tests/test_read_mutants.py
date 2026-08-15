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
    assert summary.canonical_mode == "sqlite"
    expected_canonical = vertex_path.parent / ".loops" / "data" / "ghost.db"
    assert summary.canonical_path == str(expected_canonical)
    assert summary.index_path == str(expected_canonical)
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


@pytest.fixture
def rich_store(tmp_path: Path) -> tuple[Path, Path, Path]:
    """One populated child vertex, reachable through all three read_summary
    branches: as a discover-aggregate parent, as the vertex itself, and as a
    bare sqlite store.

    Deliberately asymmetric so that no field can be confused with another:
    fact_total 3 != tick_total 2, signed 2 != unsigned 1, two kinds with
    counts 2 and 1, one `_decl.genesis` behind include_internal, and a real
    latest_ts. Every default in the `.get(key, default)` chains differs from
    the true value.

    Returns (parent, child, bare_db).
    """
    children = tmp_path / "children"
    children.mkdir()
    child = children / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store "child.db"\n'
        "loops {\n"
        "  task {\n"
        '    fold { items "collect" 100 }\n'
        "    boundary every=1\n"
        "  }\n"
        '  note { fold { items "collect" 100 } }\n'
        "}\n",
        encoding="utf-8",
    )
    ensure_signing_key(child, "admin")
    add_kind(child, "todo", observer="admin")
    ensure_signing_key(child, "alice")
    emit_fact(child, "task", {"t": "a"}, observer="alice", ts=0.5)
    emit_fact(child, "task", {"t": "b"}, observer="alice", ts=1700000100.0)
    emit_fact(child, "note", {"b": "n"}, observer="bob", ts=1700000200.0)

    parent = tmp_path / "disc.vertex"
    parent.write_text('name "disc"\ndiscover "children/*.vertex"\n', encoding="utf-8")

    return parent, child, children / "child.db"


def test_read_summary_discover_aggregate_pins_every_field(
    rich_store: tuple[Path, Path, Path],
) -> None:
    """Full field pin on the aggregate return, with a tick_total that is
    neither zero nor equal to fact_total. Nothing here may fall back to a
    `.get()` default or borrow another field's value.
    """
    parent, _, _ = rich_store

    summary = read_summary(parent)
    assert summary.target_type == "vertex"
    assert summary.target_path == str(parent.resolve())
    assert summary.canonical_mode == "aggregate"
    assert summary.canonical_path is None
    assert summary.index_path is None
    assert summary.declaration_status == "file-pre-genesis"
    assert summary.fact_total == 3
    assert summary.tick_total == 2
    assert summary.latest_ts is None  # the aggregate branch never computes this
    assert {k: v["count"] for k, v in summary.kinds.items()} == {"task": 2, "note": 1}
    assert summary.unfolded_kinds == []
    assert summary.agreement is True
    assert summary.signed_count == 0
    assert summary.unsigned_count == 3


def test_read_summary_discover_aggregate_kind_entries_carry_time_bounds(
    rich_store: tuple[Path, Path, Path],
) -> None:
    """Each aggregate kind entry is keyed count/earliest/latest, and its
    earliest/latest come from that kind's own stats.
    """
    parent, _, _ = rich_store
    task = read_summary(parent).kinds["task"]
    assert set(task) == {"count", "earliest", "latest"}
    assert task["earliest"] is not None
    assert task["latest"] is not None
    assert task["earliest"] != task["latest"]


def test_read_summary_aggregate_with_own_store_reports_its_paths(tmp_path: Path) -> None:
    """`discover` and `store` are not mutually exclusive (only `combine` and
    `store` are), so an aggregate CAN have canonical/index paths of its own.
    That is the only shape in which the aggregate branch's
    ``str(path) if path else None`` conditionals take their true arm.
    """
    children = tmp_path / "children"
    children.mkdir()
    child = children / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store "child.db"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    emit_fact(child, "task", {"t": "a"}, observer="alice")

    parent = tmp_path / "disc_owned.vertex"
    parent.write_text(
        'name "disc_owned"\n'
        'store "disc_owned.db"\n'
        'discover "children/*.vertex"\n'
        'loops { task { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )

    summary = read_summary(parent)
    assert summary.canonical_mode == "sqlite"
    assert summary.canonical_path == str(tmp_path / "disc_owned.db")
    assert summary.index_path == str(tmp_path / "disc_owned.db")
    assert summary.fact_total == 1


def test_read_summary_aggregate_include_internal_is_forwarded(
    rich_store: tuple[Path, Path, Path],
) -> None:
    """include_internal reaches the aggregate summary query: the child's
    `_decl.genesis` row is hidden by default and counted when asked for.
    """
    parent, _, _ = rich_store
    assert read_summary(parent).fact_total == 3
    internal = read_summary(parent, include_internal=True)
    assert internal.fact_total == 4
    assert "_decl.genesis" in internal.kinds


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


def test_read_summary_vertex_branch_pins_totals_and_paths(
    rich_store: tuple[Path, Path, Path],
) -> None:
    """The vertex-with-store return, pinned against a store whose
    fact_total, tick_total, signed and unsigned counts are all different
    numbers, so no field can stand in for another.
    """
    _, child, bare_db = rich_store

    summary = read_summary(child)
    assert summary.target_path == str(child.resolve())
    assert summary.canonical_mode == "sqlite"
    assert summary.canonical_path == str(bare_db)
    assert summary.index_path == str(bare_db)
    assert summary.declaration_status == "store"
    assert summary.fact_total == 3
    assert summary.tick_total == 2
    assert summary.latest_ts == 1700000200.0
    assert summary.signed_count == 2
    assert summary.unsigned_count == 1
    assert summary.agreement is True


def test_read_summary_bare_sqlite_store_pins_totals_and_counts(
    rich_store: tuple[Path, Path, Path],
) -> None:
    """The bare-store branch computes the same statistics as the vertex
    branch but reports declaration_status None and no unfolded kinds. Pinned
    against the same asymmetric store.
    """
    _, _, bare_db = rich_store

    summary = read_summary(bare_db)
    assert summary.target_type == "sqlite_store"
    assert summary.target_path == str(bare_db)
    assert summary.canonical_path == str(bare_db)
    assert summary.index_path == str(bare_db)
    assert summary.declaration_status is None
    assert summary.fact_total == 3
    assert summary.tick_total == 2
    assert summary.latest_ts == 1700000200.0
    assert {k: v["count"] for k, v in summary.kinds.items()} == {"task": 2, "note": 1}
    assert summary.unfolded_kinds == []
    assert summary.agreement is True
    assert summary.signed_count == 2
    assert summary.unsigned_count == 1


def test_read_summary_pre_signature_store_reports_zero_not_one(
    rich_store: tuple[Path, Path, Path],
) -> None:
    """`StoreReader.signed_counts()` returns None on a pre-delta-3 store
    (no `signature` column). Both signed_count and unsigned_count fall back
    to 0 in that case — not 1, and not each other's value. Reached through
    both the vertex branch and the bare-store branch.
    """
    import sqlite3

    _, child, bare_db = rich_store

    conn = sqlite3.connect(bare_db)
    try:
        conn.execute("ALTER TABLE facts DROP COLUMN signature")
        conn.commit()
    finally:
        conn.close()

    via_vertex = read_summary(child)
    assert via_vertex.signed_count == 0
    assert via_vertex.unsigned_count == 0
    assert via_vertex.fact_total == 3

    via_bare = read_summary(bare_db)
    assert via_bare.signed_count == 0
    assert via_bare.unsigned_count == 0
    assert via_bare.fact_total == 3


def test_read_summary_bare_store_include_internal_is_forwarded(
    rich_store: tuple[Path, Path, Path],
) -> None:
    """The bare-store branch forwards include_internal to the stats helper."""
    _, _, bare_db = rich_store
    assert read_summary(bare_db).fact_total == 3
    internal = read_summary(bare_db, include_internal=True)
    assert internal.fact_total == 4
    assert "_decl.genesis" in internal.kinds


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

    with pytest.raises(SdkValueError) as excinfo:
        read_facts(sample_vertex, order="sideways")
    message = str(excinfo.value)
    assert "sideways" in message
    assert "newest" in message
    assert "oldest" in message


def test_read_facts_default_limit_is_exactly_50(tmp_path: Path) -> None:
    """The default `limit` is 50, not 51 or any other neighbor: 51 emitted
    facts read with no explicit limit must be capped at 50 and reported
    truncated — a limit=51 mutant would return all 51, untruncated.
    """
    vertex_path = tmp_path / "limit50.vertex"
    vertex_path.write_text(
        'name "limit50"\nstore ".loops/data/limit50.db"\n'
        'loops { item { fold { items "collect" 200 } } }\n',
        encoding="utf-8",
    )
    for i in range(51):
        emit_fact(vertex_path, "item", {"n": i}, observer="alice", ts=1700000000.0 + i)

    page = read_facts(vertex_path)
    assert len(page.items) == 50
    assert page.truncated is True


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


def test_read_facts_pagination_next_cursor_walks_pages_in_order(tmp_path: Path) -> None:
    """5 facts, limit=2: page 1 is truncated with a concrete next_cursor
    equal to the LAST item's id; feeding it back as `before=` in newest
    order returns the next older slice, and the final page has
    truncated=False, next_cursor=None. Pins the exact cursor value (not
    just its non-None-ness) and the `>` vs `>=` truncation boundary.
    """
    vertex_path = tmp_path / "pager.vertex"
    vertex_path.write_text(
        'name "pager"\nstore ".loops/data/pager.db"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    ids = [
        emit_fact(vertex_path, "item", {"n": i}, observer="alice", ts=1700000000.0 + i).id
        for i in range(5)
    ]

    page1 = read_facts(vertex_path, limit=2)
    assert [it["id"] for it in page1.items] == [ids[4], ids[3]]
    assert page1.truncated is True
    assert page1.next_cursor == ids[3]

    page2 = read_facts(vertex_path, limit=2, before=page1.next_cursor)
    assert [it["id"] for it in page2.items] == [ids[2], ids[1]]
    assert page2.truncated is True
    assert page2.next_cursor == ids[1]

    page3 = read_facts(vertex_path, limit=2, before=page2.next_cursor)
    assert [it["id"] for it in page3.items] == [ids[0]]
    assert page3.truncated is False
    assert page3.next_cursor is None


def test_read_facts_oldest_order_returns_chronological_and_echoes_order(tmp_path: Path) -> None:
    """order="oldest" walks ascending, and the returned `order` field echoes
    the caller's choice rather than a hardcoded "newest".
    """
    vertex_path = tmp_path / "oldest.vertex"
    vertex_path.write_text(
        'name "oldest"\nstore ".loops/data/oldest.db"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    ids = [
        emit_fact(vertex_path, "item", {"n": i}, observer="alice", ts=1700000000.0 + i).id
        for i in range(3)
    ]
    page = read_facts(vertex_path, limit=50, order="oldest")
    assert [it["id"] for it in page.items] == ids
    assert page.order == "oldest"


def test_read_facts_observer_filter_excludes_other_observers(tmp_path: Path) -> None:
    vertex_path = tmp_path / "obs.vertex"
    vertex_path.write_text(
        'name "obs"\nstore ".loops/data/obs.db"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    emit_fact(vertex_path, "item", {"n": 1}, observer="alice")
    emit_fact(vertex_path, "item", {"n": 2}, observer="bob")

    page = read_facts(vertex_path, limit=50, observer="alice")
    assert len(page.items) == 1
    assert page.items[0]["observer"] == "alice"


def test_read_facts_missing_store_returns_empty_page_with_requested_order(
    tmp_path: Path,
) -> None:
    """The vertex-declared-but-store-missing early return still echoes the
    caller's `order` and reports an empty, non-truncated page — not a
    hardcoded/None order or truncated=True.
    """
    vertex_path = tmp_path / "ghost_facts.vertex"
    vertex_path.write_text(
        'name "ghost_facts"\nstore ".loops/data/ghost_facts.db"\n'
        'loops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    page = read_facts(vertex_path, order="oldest")
    assert page.items == []
    assert page.next_cursor is None
    assert page.prev_cursor is None
    assert page.truncated is False
    assert page.order == "oldest"


def test_read_facts_no_store_declared_reaches_and_or_split(tmp_path: Path) -> None:
    """A vertex with NO `store` line has info.canonical_path=None (not just
    "declared but missing"), which is the only public-surface path that
    makes the `canonical_path is None OR not .exists()` early-return guard
    distinguishable from an `and` mutant (an `and` mutant would call
    `.exists()` on None and crash, or — if short-circuited differently —
    fall through incorrectly).
    """
    vertex_path = tmp_path / "nostore_facts.vertex"
    vertex_path.write_text(
        'name "nostore_facts"\nloops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    page = read_facts(vertex_path)
    assert page.items == []
    assert page.truncated is False


def test_read_facts_aggregate_combine_reverses_for_newest_and_caps_at_limit(
    tmp_path: Path,
) -> None:
    """The aggregate branch fetches ALL matching facts chronologically then
    manually reverses for order="newest" and caps with `[:limit]` — pin the
    reversal, the cap, the kind/observer filter passthrough, and the
    truncated flag it derives from comparing lengths (not a hardcoded value).
    A fact at ts=0.5 distinguishes the hardcoded since_ts=0.0 lower bound
    from a since_ts=1.0 mutant, and an internal `_decl.genesis` fact
    distinguishes include_internal=True from a dropped/None-ed passthrough.
    """
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store ".loops/data/child.db"\n'
        "loops {\n"
        '  task { fold { items "collect" 100 } }\n'
        '  note { fold { items "collect" 100 } }\n'
        "}\n",
        encoding="utf-8",
    )
    ensure_signing_key(child, "admin")
    add_kind(child, "todo", observer="admin")
    ids = [emit_fact(child, "task", {"n": 0}, observer="alice", ts=0.5).id]
    ids += [
        emit_fact(child, "task", {"n": i}, observer="alice", ts=1700000000.0 + i).id
        for i in range(1, 3)
    ]
    emit_fact(child, "note", {"n": 0}, observer="bob", ts=1700000100.0)

    parent = tmp_path / "aggregate_facts.vertex"
    parent.write_text(
        f'name "aggregate_facts"\ncombine {{\n  vertex "{child}" as="a"\n}}\n',
        encoding="utf-8",
    )

    page = read_facts(parent, limit=2, kind="task")
    assert [it["id"] for it in page.items] == [ids[2], ids[1]]
    assert page.truncated is True
    assert page.next_cursor is None  # aggregate branch never sets cursors
    assert page.prev_cursor is None

    # Exact-limit boundary: len(all_facts) == len(capped) must NOT truncate.
    exact_page = read_facts(parent, limit=3, kind="task")
    assert len(exact_page.items) == 3
    assert exact_page.truncated is False

    oldest_page = read_facts(parent, limit=50, kind="task", order="oldest")
    assert [it["id"] for it in oldest_page.items] == ids
    assert oldest_page.order == "oldest"

    obs_page = read_facts(parent, limit=50, observer="bob")
    assert len(obs_page.items) == 1
    assert obs_page.items[0]["kind"] == "note"

    default_page = read_facts(parent, limit=50)
    assert all(it["kind"] != "_decl.genesis" for it in default_page.items)
    internal_page = read_facts(parent, limit=50, include_internal=True)
    assert any(it["kind"] == "_decl.genesis" for it in internal_page.items)


def test_read_facts_bare_store_pagination_and_cursor_resolution(tmp_path: Path) -> None:
    """A direct .db (bare, non-vertex) target exercises the tail branch's
    own canonical/index_path fallbacks and before_pos/after_pos cursor
    resolution — distinct code from the vertex-with-store branch above.
    Also pins the FactPageResult construction's next_cursor/prev_cursor/
    truncated/order fields for that branch.
    """
    from sdk import sync_target

    vertex_path = tmp_path / "bare_src.vertex"
    vertex_path.write_text(
        'name "bare_src"\nstore ".loops/data/bare_src.db"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    ids = [
        emit_fact(vertex_path, "item", {"n": i}, observer="alice", ts=1700000000.0 + i).id
        for i in range(4)
    ]
    db_path = vertex_path.parent / ".loops" / "data" / "bare_src.db"
    sync_target(db_path)

    page1 = read_facts(db_path, limit=2)
    assert [it["id"] for it in page1.items] == [ids[3], ids[2]]
    assert page1.truncated is True
    assert page1.next_cursor == ids[2]
    assert page1.prev_cursor is None
    assert page1.order == "newest"

    page2 = read_facts(db_path, limit=2, before=page1.next_cursor)
    assert [it["id"] for it in page2.items] == [ids[1], ids[0]]
    assert page2.truncated is False
    assert page2.next_cursor is None

    oldest = read_facts(db_path, limit=2, order="oldest", after=ids[0])
    assert [it["id"] for it in oldest.items] == [ids[1], ids[2]]
    assert oldest.order == "oldest"


def test_read_facts_bare_store_kind_observer_include_internal_passthrough(
    tmp_path: Path,
) -> None:
    """The bare-store branch's reader.query_facts call forwards kind,
    observer, and include_internal — dropping/None-ing any one of them
    would surface facts that should have been filtered out.
    """
    from sdk import sync_target

    vertex_path = tmp_path / "bare_filter.vertex"
    vertex_path.write_text(
        'name "bare_filter"\n'
        'store ".loops/data/bare_filter.db"\n'
        "loops {\n"
        '  task { fold { items "collect" 100 } }\n'
        '  note { fold { items "collect" 100 } }\n'
        "}\n",
        encoding="utf-8",
    )
    ensure_signing_key(vertex_path, "admin")
    add_kind(vertex_path, "todo", observer="admin")
    emit_fact(vertex_path, "task", {"n": 1}, observer="alice")
    emit_fact(vertex_path, "task", {"n": 2}, observer="bob")
    emit_fact(vertex_path, "note", {"n": 3}, observer="alice")
    db_path = vertex_path.parent / ".loops" / "data" / "bare_filter.db"
    sync_target(db_path)

    kind_page = read_facts(db_path, limit=50, kind="task")
    assert all(it["kind"] == "task" for it in kind_page.items)
    assert len(kind_page.items) == 2

    observer_page = read_facts(db_path, limit=50, observer="alice")
    assert all(it["observer"] == "alice" for it in observer_page.items)
    assert len(observer_page.items) == 2

    default_page = read_facts(db_path, limit=50)
    assert all(it["kind"] != "_decl.genesis" for it in default_page.items)
    internal_page = read_facts(db_path, limit=50, include_internal=True)
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
    assert state.target_path == str(vertex_path.resolve())
    assert state.generation == {}
    assert state.sections == {}


@pytest.fixture
def two_kind_vertex(tmp_path: Path) -> Path:
    """A vertex with two collect-folded kinds, written in a fixed order.

    The declaration order matters: `alpha` is folded before `beta`, so a
    ``kind="beta"`` filter must SKIP alpha rather than stop at it.
    """
    vertex_path = tmp_path / "two_kind_state.vertex"
    vertex_path.write_text(
        'name "two_kind_state"\n'
        'store ".loops/data/two_kind_state.db"\n'
        "loops {\n"
        '  alpha { fold { items "collect" 100 } }\n'
        '  beta { fold { items "collect" 100 } }\n'
        "}\n",
        encoding="utf-8",
    )
    emit_fact(vertex_path, "alpha", {"v": 1}, observer="alice")
    emit_fact(vertex_path, "beta", {"v": 2}, observer="bob")
    return vertex_path


def test_read_state_kind_filter_skips_non_matching_sections(two_kind_vertex: Path) -> None:
    """The kind filter must `continue` past non-matching sections, not
    `break` out of the loop: filtering for the SECOND declared kind still
    has to return that section, and must exclude the first.
    """
    state = read_state(two_kind_vertex, kind="beta")
    assert set(state.sections) == {"beta"}

    state_alpha = read_state(two_kind_vertex, kind="alpha")
    assert set(state_alpha.sections) == {"alpha"}

    unfiltered = read_state(two_kind_vertex)
    assert set(unfiltered.sections) == {"alpha", "beta"}


def test_read_state_observer_scopes_fold_state(two_kind_vertex: Path) -> None:
    """The `observer` argument is forwarded to the fold replay, producing an
    observer-scoped view — dropping it (or hardcoding None) would return
    every observer's contribution.
    """
    alice = read_state(two_kind_vertex, observer="alice")
    assert set(alice.sections) == {"alpha", "beta"}
    assert alice.sections["alpha"]["items"] != []
    assert alice.sections["beta"]["items"] == []

    bob = read_state(two_kind_vertex, observer="bob")
    assert bob.sections["alpha"]["items"] == []
    assert bob.sections["beta"]["items"] != []


def test_read_state_populated_vertex_pins_scalar_fields(two_kind_vertex: Path) -> None:
    """The main (store-present) return pins vertex_name from the declaration,
    target_path as the resolved .vertex path, and the declaration's own
    status string.
    """
    state = read_state(two_kind_vertex)
    assert isinstance(state, FoldStateResult)
    assert state.vertex_name == "two_kind_state"
    assert state.target_path == str(two_kind_vertex.resolve())
    assert state.declaration_status == "file-pre-genesis"
    assert state.generation == {}


def test_read_state_non_vertex_target_error_names_the_target_type(tmp_path: Path) -> None:
    """TargetUnsupported must say what was required and what was received —
    an empty/None message is useless to a caller.
    """
    from sdk import TargetUnsupported

    log = tmp_path / "bare.jsonl"
    log.write_text("", encoding="utf-8")

    with pytest.raises(TargetUnsupported) as excinfo:
        read_state(log)
    message = str(excinfo.value)
    assert "read_state requires a .vertex target" in message
    assert "jsonl_log" in message


# =============================================================================
# Shared aggregate fixtures
#
# Every one of read_summary / read_facts / read_ticks / read_fact_by_id
# computes `is_aggregate` from BOTH `decl_ast.combine` and
# `decl_ast.discover`. A combine-only fixture leaves the discover arm of
# that disjunction unexercised, so mutating it (`discover is not None` ->
# `discover is None`) is invisible. A discover-aggregate has no canonical
# store of its own, which makes the aggregate/non-aggregate split
# observable: the non-aggregate path returns the empty result.
# =============================================================================


@pytest.fixture
def discover_aggregate(tmp_path: Path) -> tuple[Path, list[EmitReceipt]]:
    """A `discover`-glob aggregate over one child vertex with fired ticks.

    The child fires a boundary tick per fact under two distinct tick marks
    ("task" and "note"), and its first fact is emitted at ts=0.5 so that the
    hardcoded 0.0 lower bound of the tick window is distinguishable from 1.0.
    """
    children = tmp_path / "children"
    children.mkdir()
    child = children / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store "child.db"\n'
        "loops {\n"
        "  task {\n"
        '    fold { items "collect" 100 }\n'
        "    boundary every=1\n"
        "  }\n"
        "  note {\n"
        '    fold { items "collect" 100 }\n'
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    receipts = [
        emit_fact(child, "task", {"title": "early"}, observer="alice", ts=0.5),
        emit_fact(child, "task", {"title": "later"}, observer="alice", ts=1700000100.0),
        emit_fact(child, "note", {"body": "n"}, observer="bob", ts=1700000200.0),
    ]

    parent = tmp_path / "disc.vertex"
    parent.write_text(
        'name "disc"\ndiscover "children/*.vertex"\n',
        encoding="utf-8",
    )
    return parent, receipts


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


@pytest.fixture
def two_mark_vertex(tmp_path: Path) -> Path:
    """A store-backed vertex firing ticks under two distinct marks, the
    first of them at ts=0.5 (below the hardcoded 1.0 mutant bound).
    """
    vertex_path = tmp_path / "two_mark.vertex"
    vertex_path.write_text(
        'name "two_mark"\n'
        'store ".loops/data/two_mark.db"\n'
        "loops {\n"
        "  alpha {\n"
        '    fold { total "count" }\n'
        "    boundary every=1\n"
        "  }\n"
        "  beta {\n"
        '    fold { total "count" }\n'
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    emit_fact(vertex_path, "alpha", {"n": 1}, observer="tester", ts=0.5)
    emit_fact(vertex_path, "beta", {"n": 1}, observer="tester", ts=1700000000.0)
    return vertex_path


def test_read_ticks_name_filter_selects_one_of_two_marks(two_mark_vertex: Path) -> None:
    """With two real tick marks present, the `name` argument must select
    exactly one — a dropped or None-ed `name=` passthrough returns both.
    """
    assert {t["name"] for t in read_ticks(two_mark_vertex)} == {"alpha", "beta"}
    assert [t["name"] for t in read_ticks(two_mark_vertex, name="alpha")] == ["alpha"]
    assert [t["name"] for t in read_ticks(two_mark_vertex, name="beta")] == ["beta"]


def test_read_ticks_window_starts_at_zero_not_one(two_mark_vertex: Path) -> None:
    """The tick window's lower bound is 0.0, so a tick sealed at ts=0.5 is
    inside it. A bound of 1.0 would silently drop that tick.
    """
    assert 0.5 in {t["ts"] for t in read_ticks(two_mark_vertex)}


def test_read_ticks_discover_aggregate_reads_member_ticks(
    discover_aggregate: tuple[Path, list[EmitReceipt]],
) -> None:
    """A discover-glob aggregate has no canonical store of its own, so its
    ticks can only come from the aggregate branch: they must be present,
    serialized as dicts, filterable by name, and include the ts=0.5 seal.
    """
    parent, _ = discover_aggregate

    ticks = read_ticks(parent)
    assert len(ticks) == 3
    assert all(isinstance(t, dict) for t in ticks)
    assert {t["name"] for t in ticks} == {"task", "note"}
    assert 0.5 in {t["ts"] for t in ticks}

    assert [t["name"] for t in read_ticks(parent, name="note")] == ["note"]
    assert read_ticks(parent, name="no_such_mark") == []


def test_read_ticks_combine_aggregate_reads_member_ticks(tmp_path: Path) -> None:
    """The other arm of the aggregate disjunction: a `combine` vertex also
    has no canonical store, so its member ticks are reachable only when
    `combine is not None` is what selects the aggregate branch.
    """
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store ".loops/data/child.db"\n'
        "loops {\n"
        "  event {\n"
        '    fold { total "count" }\n'
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    emit_fact(child, "event", {"n": 1}, observer="alice")

    parent = tmp_path / "combined.vertex"
    parent.write_text(
        f'name "combined"\ncombine {{\n  vertex "{child}" as="a"\n}}\n',
        encoding="utf-8",
    )

    ticks = read_ticks(parent)
    assert [t["name"] for t in ticks] == ["event"]


def test_read_ticks_jsonl_vertex_reads_through_derived_index(tmp_path: Path) -> None:
    """On a jsonl-canonical vertex the index is a separate .db; opening a
    StoreReader on the .jsonl itself is not a database. This is the only
    shape in which the `index_path or canonical` fallback is observable.
    """
    vertex_path = tmp_path / "tickjson.vertex"
    vertex_path.write_text(
        'name "tickjson"\n'
        'store ".loops/data/tickjson.jsonl"\n'
        "loops {\n"
        "  event {\n"
        '    fold { total "count" }\n'
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    emit_fact(vertex_path, "event", {"n": 1}, observer="alice")
    assert [t["name"] for t in read_ticks(vertex_path)] == ["event"]


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


def test_read_fact_by_id_discover_aggregate(
    discover_aggregate: tuple[Path, list[EmitReceipt]],
) -> None:
    """A discover-glob aggregate resolves member facts through the aggregate
    branch. Its own canonical store does not exist, so treating it as
    non-aggregate returns None instead.
    """
    parent, receipts = discover_aggregate
    fact = read_fact_by_id(parent, receipts[0].id)
    assert fact is not None
    assert fact["id"] == receipts[0].id
    assert fact["kind"] == "task"
    assert read_fact_by_id(parent, "00000000000000000000000000") is None


def test_read_fact_by_id_jsonl_vertex_recovers_index_from_canonical(
    jsonl_vertex: Path,
) -> None:
    """On a jsonl-canonical vertex the two fallbacks are distinguishable:
    ``canonical`` must be the .jsonl (preflight rebuilds the index from it)
    and ``index_path`` must be the derived .db (StoreReader cannot open a
    .jsonl). Deleting the index forces the recovery path, so an `and`-for-`or`
    mutation on either fallback line cannot silently pass.
    """
    from sdk import resolve_target

    receipt = emit_fact(jsonl_vertex, "entry", {"body": "x"}, observer="alice")
    info = resolve_target(jsonl_vertex)
    assert info.index_path is not None
    info.index_path.unlink()

    fact = read_fact_by_id(jsonl_vertex, receipt.id)
    assert fact is not None
    assert fact["id"] == receipt.id
    assert fact["kind"] == "entry"


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


# =============================================================================
# read_summary: no-store-declared reaches the canonical_mode "unknown" fallback
# =============================================================================


def test_read_summary_no_store_declared_reaches_unknown_fallback(tmp_path: Path) -> None:
    """A vertex with NO `store` line has info.canonical_mode=None, which is
    the only public-surface path that actually reaches the
    `info.canonical_mode or "unknown"` fallback (a declared-but-missing store
    still resolves a concrete canonical_mode like "sqlite"). This kills the
    `or`->`and` and string-constant mutants on that fallback.
    """
    vertex_path = tmp_path / "nostore.vertex"
    vertex_path.write_text(
        'name "nostore_name"\nloops { item { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    summary = read_summary(vertex_path)
    assert summary.canonical_mode == "unknown"
    assert summary.canonical_path is None
    assert summary.declaration_status == "file-pre-genesis"
    assert summary.fact_total == 0


# =============================================================================
# read_summary: aggregate (combine) branch, rich fixture (tick + multi-kind)
# =============================================================================


def test_read_summary_aggregate_rich_fixture_pins_every_field(tmp_path: Path) -> None:
    """Replaces the thin aggregate fixture: adds a second kind (distinct
    earliest/latest per kind) and a boundary-fired tick so tick_total is
    nonzero and distinguishable from fact_total/kind counts, and asserts
    every field the aggregate ReadSummary literal sets (target_path,
    canonical_mode="aggregate", canonical_path/index_path always None here
    because the aggregate head declares no store of its own).
    """
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store ".loops/data/child.db"\n'
        "loops {\n"
        "  task {\n"
        '    fold { items "collect" 100 }\n'
        "    boundary every=1\n"
        "  }\n"
        "  note {\n"
        '    fold { items "collect" 100 }\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    emit_fact(child, "task", {"title": "t1"}, observer="alice", ts=1700000000.0)
    emit_fact(child, "note", {"body": "n1"}, observer="alice", ts=1700000100.0)

    parent = tmp_path / "aggregate.vertex"
    parent.write_text(
        f'name "aggregate"\ncombine {{\n  vertex "{child}" as="a"\n}}\n',
        encoding="utf-8",
    )

    summary = read_summary(parent)
    assert summary.target_type == "vertex"
    assert summary.target_path == str(parent.resolve())
    assert summary.canonical_mode == "aggregate"
    assert summary.canonical_path is None
    assert summary.index_path is None
    assert summary.declaration_status == "file-pre-genesis"
    assert summary.fact_total == 2
    assert summary.tick_total == 1
    assert summary.kinds["task"]["count"] == 1
    assert summary.kinds["note"]["count"] == 1
    assert summary.latest_ts is None
    assert summary.unfolded_kinds == []
    assert summary.agreement is True
    assert summary.signed_count == 0
    assert summary.unsigned_count == 2


def test_read_facts_cursor_pagination_on_jsonl_canonical_vertex(tmp_path: Path) -> None:
    """Regression: witness cursors resolved against the jsonl canonical log,
    which resolve_witness_position opens as sqlite — DatabaseError on every
    cursor-paginated read of a jsonl-canonical target. Cursors must resolve
    against the index.
    """
    vertex_path = tmp_path / "j.vertex"
    vertex_path.write_text(
        'name "j"\nstore "j.jsonl"\nloops { note { fold { items "collect" 10 } } }\n',
        encoding="utf-8",
    )
    for i in range(3):
        emit_fact(vertex_path, "note", {"n": i}, observer="t", ts=1700000000.0 + i)

    page = read_facts(vertex_path, limit=2)
    assert len(page.items) == 2
    assert page.next_cursor is not None

    page2 = read_facts(vertex_path, limit=2, after=page.next_cursor)
    assert len(page2.items) >= 1
