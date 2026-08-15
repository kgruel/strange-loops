"""Property-based invariant tests for SDK operations using Hypothesis."""

from __future__ import annotations

import pytest
from atoms.testing.strategies import payloads
from hypothesis import given, settings
from hypothesis import strategies as st

from sdk import (
    emit_fact,
    read_fact_by_id,
    read_facts,
    read_summary,
)


@settings(max_examples=30, deadline=5000)
@given(
    fact_items=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=20, alphabet=st.characters(categories=["Ll", "Nd"])),
            payloads(),
        ),
        min_size=1,
        max_size=20,
    )
)
def test_property_emission_and_pagination_invariants(
    tmp_path_factory: pytest.TempPathFactory,
    fact_items: list[tuple[str, dict]],
) -> None:
    """Property: Paginating facts partitions the store completely without duplicates or loss."""
    tmp_path = tmp_path_factory.mktemp("prop_sdk")
    vertex_path = tmp_path / "prop.vertex"
    vertex_path.write_text(
        'name "prop"\nstore ".loops/data/prop.db"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )

    # Emit all generated facts (admit_undeclared=True allows arbitrary generated kind names)
    emitted_ids = []
    for kind, payload in fact_items:
        receipt = emit_fact(
            vertex_path,
            kind,
            payload,
            observer="tester",
            admit_undeclared=True,
        )
        emitted_ids.append(receipt.id)

    total_emitted = len(fact_items)

    # 1. Summary Conservation Property
    summary = read_summary(vertex_path)
    assert summary.fact_total == total_emitted
    assert sum(k["count"] for k in summary.kinds.values()) == total_emitted

    # 2. Lookup Fixpoint Property
    for fid in emitted_ids:
        fact = read_fact_by_id(vertex_path, fid)
        assert fact is not None
        assert fact["id"] == fid

    # 3. Newest Pagination Completeness & Partition Property (pages of size 3)
    page_size = 3
    collected_newest_ids: list[str] = []
    cursor = None

    while True:
        page = read_facts(vertex_path, limit=page_size, before=cursor, order="newest")
        collected_newest_ids.extend(it["id"] for it in page.items)
        if not page.truncated or page.next_cursor is None:
            break
        cursor = page.next_cursor

    # Ensure no duplicates and exact count matches total emitted
    assert len(collected_newest_ids) == total_emitted
    assert len(set(collected_newest_ids)) == total_emitted
    assert set(collected_newest_ids) == set(emitted_ids)

    # 4. Oldest Pagination Completeness & Reversal Property
    collected_oldest_ids: list[str] = []
    cursor = None

    while True:
        page = read_facts(vertex_path, limit=page_size, after=cursor, order="oldest")
        collected_oldest_ids.extend(it["id"] for it in page.items)
        if not page.truncated or page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert len(collected_oldest_ids) == total_emitted
    assert set(collected_oldest_ids) == set(emitted_ids)
    assert collected_oldest_ids == list(reversed(collected_newest_ids))
