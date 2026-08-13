"""query_facts — bounded, cursor-bearing generic fact query (libs-handoff S5).

The oracle this slice ships against:

- pagination-vs-full-scan equivalence on a store with MIXED id eras: paging
  through the whole store in pages of N yields exactly the full-scan sequence,
  no duplicates, no gaps, in BOTH orders. Ids are constructed so lexicographic
  id order is the REVERSE of append order (and ts is non-monotonic) — any code
  path that orders by id (A3 violation) or by ts flips the sequence and fails.
- snapshot consistency: a writer appending mid-pagination does not perturb a
  page walk running inside one ``StoreReader.snapshot()`` bracket, and a
  ``newest`` walk is cursor-immune to appends even without the bracket.

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from atoms import Fact

from engine.sqlite_store import SqliteStore
from engine.store_reader import FactPage, StoreReader
from engine.vertex_reader import vertex_query_facts
from engine.witness import (
    WitnessAggregateUnsupported,
    WitnessLineageMismatch,
    resolve_witness_position,
)


def _open_store(path: Path) -> SqliteStore:
    return SqliteStore(
        path=path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )


def _mixed_era_id(i: int) -> str:
    """An id whose lexicographic order REVERSES append order, mixing eras.

    Even appends get a uuid4-shaped id, odd appends a ULID-shaped one; the
    leading counter descends as i ascends so ``ORDER BY id`` is exactly the
    reverse of ``ORDER BY rowid``. Any id-as-position bug inverts the walk.
    """
    tag = 999 - i
    if i % 2 == 0:
        return f"{tag:03d}4a7b-{i:04d}-uuid-era0-abcdef012345"
    return f"{tag:03d}ULIDERA{i:04d}ZZZZZZZZZZ"


KINDS = ["decision", "thread", "log", "decision.sub"]
OBSERVERS = ["kyle", "kyle/loops-claude", "sol"]
N = 53


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """A store of N facts with adversarial ids, non-monotonic ts, interior
    ``_decl.*`` rows, and multiple kinds/observers."""
    path = tmp_path / "s5.db"
    store = _open_store(path)
    for i in range(N):
        kind = "_decl.kind_defined" if i % 11 == 5 else KINDS[i % len(KINDS)]
        # Every 7th fact is backdated — event time disagrees with append order.
        ts = 500.0 - i if i % 7 == 3 else 1000.0 + i
        fact = Fact.of(kind, OBSERVERS[i % len(OBSERVERS)], ts=ts, seq=i)
        store.append(fact, id_override=_mixed_era_id(i))
    store.close()
    return path


def _walk(reader: StoreReader, order: str, page_size: int, **filters) -> list[dict]:
    """Page through the whole store; assert cursor plumbing along the way."""
    items: list[dict] = []
    cursor = None
    while True:
        kw = dict(filters)
        if cursor is not None:
            kw["before" if order == "newest" else "after"] = cursor
        page = reader.query_facts(limit=page_size, order=order, **kw)
        assert isinstance(page, FactPage)
        assert page.order == order
        assert len(page.items) <= page_size
        items.extend(page.items)
        if not page.truncated:
            assert page.next is None
            return items
        assert page.next is not None
        # The cursor is the 0.8.0 WitnessPosition — addressed by fact id +
        # rowid, and the id is the page's last item (never compared/ordered).
        assert page.next.fact_id == page.items[-1]["id"]
        cursor = page.next


@pytest.mark.parametrize("order", ["newest", "oldest"])
@pytest.mark.parametrize("page_size", [1, 7, 10, 53, 100])
def test_pagination_equals_full_scan_mixed_id_eras(db, order, page_size):
    with StoreReader(db) as reader:
        full = reader.query_facts(limit=10_000, order=order)
        assert not full.truncated and full.next is None
        paged = _walk(reader, order, page_size)
    full_ids = [f["id"] for f in full.items]
    paged_ids = [f["id"] for f in paged]
    assert paged_ids == full_ids                      # no gaps, no reorders
    assert len(set(paged_ids)) == len(paged_ids)      # no duplicates


def test_full_scan_is_append_order_not_id_or_ts_order(db):
    """Ordering authority is the witness (append) axis — A3 pinned."""
    visible = [i for i in range(N) if i % 11 != 5]
    append_order_ids = [_mixed_era_id(i) for i in visible]
    with StoreReader(db) as reader:
        oldest = [f["id"] for f in reader.query_facts(limit=1000, order="oldest").items]
        newest = [f["id"] for f in reader.query_facts(limit=1000, order="newest").items]
    assert oldest == append_order_ids
    assert newest == list(reversed(append_order_ids))
    # The adversarial construction actually bites: id order != append order,
    # and ts order != append order.
    assert sorted(oldest) != oldest
    with StoreReader(db) as reader:
        ts_by_id = {f["id"]: f["ts"] for f in reader.query_facts(limit=1000, order="oldest").items}
    assert [i for i, _ in sorted(ts_by_id.items(), key=lambda kv: kv[1])] != oldest


@pytest.mark.parametrize("order", ["newest", "oldest"])
def test_snapshot_consistency_writer_appends_mid_pagination(db, order):
    """Inside one snapshot bracket, a concurrent append is invisible: the
    page stream equals the pre-write full scan, both orders."""
    with StoreReader(db) as reader:
        before_ids = [f["id"] for f in reader.query_facts(limit=1000, order=order).items]
    with StoreReader(db) as reader:
        with reader.snapshot():
            first = reader.query_facts(limit=7, order=order)
            # Mid-pagination write on a separate connection (WAL).
            w = _open_store(db)
            for j in range(5):
                w.append(Fact.of("decision", "kyle", ts=2000.0 + j, seq=1000 + j))
            w.close()
            rest = _walk_from(reader, order, 7, first)
    assert [f["id"] for f in first.items] + [f["id"] for f in rest] == before_ids


def _walk_from(reader: StoreReader, order: str, page_size: int, page: FactPage) -> list[dict]:
    items: list[dict] = []
    while page.truncated:
        kw = {"before" if order == "newest" else "after": page.next}
        page = reader.query_facts(limit=page_size, order=order, **kw)
        items.extend(page.items)
    return items


def test_newest_walk_is_cursor_immune_to_appends_without_bracket(db):
    """Even without a snapshot bracket, a newest walk started before a write
    never shows the new rows: they land at higher rowids than the cursor."""
    with StoreReader(db) as reader:
        before_ids = [f["id"] for f in reader.query_facts(limit=1000, order="newest").items]
        first = reader.query_facts(limit=7, order="newest")
        w = _open_store(db)
        w.append(Fact.of("decision", "kyle", ts=3000.0, seq=9999))
        w.close()
        rest = _walk_from(reader, "newest", 7, first)
    assert [f["id"] for f in first.items] + [f["id"] for f in rest] == before_ids


def test_kind_filter_includes_dotted_subtree(db):
    with StoreReader(db) as reader:
        page = reader.query_facts(limit=1000, kind="decision", order="oldest")
    kinds = {f["kind"] for f in page.items}
    assert kinds == {"decision", "decision.sub"}
    expected = [
        _mixed_era_id(i) for i in range(N)
        if i % 11 != 5 and KINDS[i % len(KINDS)] in ("decision", "decision.sub")
    ]
    assert [f["id"] for f in page.items] == expected


def test_observer_filter_namespacing_semantics(db):
    with StoreReader(db) as reader:
        bare = reader.query_facts(limit=1000, observer="loops-claude")
        assert {f["observer"] for f in bare.items} == {"kyle/loops-claude"}
        namespaced = reader.query_facts(limit=1000, observer="kyle/loops-claude")
        assert {f["observer"] for f in namespaced.items} == {"kyle/loops-claude"}
        kyle = reader.query_facts(limit=1000, observer="kyle")
        # Bare "kyle" matches the bare observer, NOT the kyle/ namespace prefix.
        assert {f["observer"] for f in kyle.items} == {"kyle"}


def test_internal_rows_excluded_by_default(db):
    with StoreReader(db) as reader:
        default = reader.query_facts(limit=1000)
        assert all(not f["kind"].startswith("_decl.") for f in default.items)
        internal = reader.query_facts(limit=1000, include_internal=True)
    assert len(internal.items) == N
    assert len(default.items) == N - sum(1 for i in range(N) if i % 11 == 5)


def test_internal_pagination_equivalence(db):
    """include_internal pages may end ON a _decl row — the read-progress
    cursor must not refuse (A2 guard is for fold cuts, not page marks)."""
    with StoreReader(db) as reader:
        full = [f["id"] for f in reader.query_facts(limit=1000, include_internal=True, order="oldest").items]
        paged = [f["id"] for f in _walk(reader, "oldest", 3, include_internal=True)]
    assert paged == full == [_mixed_era_id(i) for i in range(N)]


def test_exact_limit_boundary_not_truncated(db):
    with StoreReader(db) as reader:
        total = len(reader.query_facts(limit=1000).items)
        page = reader.query_facts(limit=total)
    assert not page.truncated and page.next is None and len(page.items) == total


def test_before_and_after_compose_into_a_window(db):
    with StoreReader(db) as reader:
        full = reader.query_facts(limit=1000, order="oldest").items
        lo = resolve_witness_position(db, full[10]["id"])
        hi = resolve_witness_position(db, full[20]["id"])
        window = reader.query_facts(limit=1000, order="oldest", after=lo, before=hi)
    assert [f["id"] for f in window.items] == [f["id"] for f in full[11:20]]


def test_foreign_unadopted_cursor_refused(db, tmp_path):
    other = tmp_path / "other.db"
    s = _open_store(other)
    s.append(Fact.of("decision", "kyle", ts=1.0, seq=0))
    s.close()
    pos = resolve_witness_position(other, "head")
    with StoreReader(db) as reader:
        with pytest.raises(WitnessLineageMismatch):
            reader.query_facts(before=pos)


def test_invalid_args_refused(db):
    with StoreReader(db) as reader:
        with pytest.raises(ValueError):
            reader.query_facts(order="sideways")
        with pytest.raises(ValueError):
            reader.query_facts(limit=0)


def test_vertex_query_facts_instance_and_aggregate(db, tmp_path):
    member_v = tmp_path / "m.vertex"
    member_v.write_text(
        f'name "m"\nstore "{db}"\n'
        'loops { decision { fold { items "by" "topic" } } }\n'
    )
    page = vertex_query_facts(member_v, limit=5)
    assert page.truncated and len(page.items) == 5

    agg = tmp_path / "agg.vertex"
    agg.write_text(f'name "agg"\ncombine {{\n  vertex "{member_v}"\n}}\n')
    with pytest.raises(WitnessAggregateUnsupported):
        vertex_query_facts(agg, limit=5)


def test_vertex_query_facts_missing_store_answers_empty_page(tmp_path):
    v = tmp_path / "ghost.vertex"
    v.write_text(
        f'name "ghost"\nstore "{tmp_path / "nope.db"}"\n'
        'loops { decision { fold { items "by" "topic" } } }\n'
    )
    page = vertex_query_facts(v)
    assert page.items == [] and page.next is None and not page.truncated
