"""Tests for transport (slice and merge) on permuted-axis source stores.

W3-R3-1 ratchet: verifies that slice_store and merge_store iterate and replicate
rows following the source's arrival coordinate order, not physical SQLite rowid order.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from atoms import Fact
from engine.arrival import ArrivalLog
from engine.sqlite_store import (
    FACT_INSERT_SQL,
    TICK_INSERT_SQL,
    SqliteStore,
    _tick_row_hash,
)
from store.merge import merge_store
from store.slice import slice_store
from tests.conftest import STUB_KEY, stub_sign


def _build_permuted_source(path: Path) -> tuple[list[str], list[str]]:
    """Build a SQLite source store where physical rowid order != arrival coordinate order.

    Facts:
      - f-2: arrival (2, 0), inserted 1st -> rowid 1
      - f-0: arrival (0, 0), inserted 2nd -> rowid 2
      - f-3: arrival (3, 0), inserted 3rd -> rowid 3
      - f-1: arrival (1, 0), inserted 4th -> rowid 4

    Ticks:
      - t-2: arrival (5, 0), inserted 1st -> rowid 1
      - t-1: arrival (4, 0), inserted 2nd -> rowid 2

    Returns (fact_ids_in_arrival_order, tick_ids_in_arrival_order).
    """
    conn = sqlite3.connect(str(path), autocommit=True)
    store = SqliteStore(
        path=path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )

    facts = [
        ("f-0", "note", 100.0, "kyle", "", '{"v": 0}', None, 0, 0),
        ("f-1", "note", 101.0, "kyle", "", '{"v": 1}', None, 1, 0),
        ("f-2", "note", 102.0, "kyle", "", '{"v": 2}', None, 2, 0),
        ("f-3", "note", 103.0, "kyle", "", '{"v": 3}', None, 3, 0),
    ]
    # Insert facts in scrambled order: f-2, f-0, f-3, f-1
    scrambled_facts = [facts[2], facts[0], facts[3], facts[1]]
    for row in scrambled_facts:
        conn.execute(FACT_INSERT_SQL, row)

    # Precompute hashes on arrival axis
    t1_hash = store._window_hash("", "f-1")
    t1_row_hash = _tick_row_hash(
        ("t-1", "seal", 101.5, None, "test", '{"n": 1}', None, "", "f-1", t1_hash, None)
    )

    t2_hash = store._window_hash("f-1", "f-3")
    t2_row_hash = _tick_row_hash(
        ("t-2", "seal", 103.5, None, "test", '{"n": 2}', t1_row_hash, "f-1", "f-3", t2_hash, None)
    )

    # Insert tick 2 before tick 1
    conn.execute(
        TICK_INSERT_SQL,
        ("t-2", "seal", 103.5, None, "test", '{"n": 2}', t1_row_hash, "f-1", "f-3", t2_hash, None, 5, 0),
    )
    conn.execute(
        TICK_INSERT_SQL,
        ("t-1", "seal", 101.5, None, "test", '{"n": 1}', None, "", "f-1", t1_hash, None, 4, 0),
    )

    # Verify source rowids vs arrival order
    src_fact_rowids = [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY rowid").fetchall()]
    assert src_fact_rowids == ["f-2", "f-0", "f-3", "f-1"]

    src_tick_rowids = [r[0] for r in conn.execute("SELECT id FROM ticks ORDER BY rowid").fetchall()]
    assert src_tick_rowids == ["t-2", "t-1"]

    src_fact_arrival = [
        r[0] for r in conn.execute("SELECT id FROM facts ORDER BY arrival_ordinal, arrival_seq").fetchall()
    ]
    assert src_fact_arrival == ["f-0", "f-1", "f-2", "f-3"]

    src_tick_arrival = [
        r[0] for r in conn.execute("SELECT id FROM ticks ORDER BY arrival_ordinal, arrival_seq").fetchall()
    ]
    assert src_tick_arrival == ["t-1", "t-2"]

    conn.close()
    store.close()
    return src_fact_arrival, src_tick_arrival


def test_permuted_source_transport_follows_arrival_order(tmp_path: Path) -> None:
    """slice_store AND merge_store replicate rows in source ARRIVAL order, not rowid order."""
    src_db = tmp_path / "permuted_source.db"
    expected_facts, expected_ticks = _build_permuted_source(src_db)

    # 1. Test slice_store into fresh target
    slice_target = tmp_path / "sliced_target.db"
    slice_res = slice_store(source=src_db, target=slice_target)
    assert slice_res.facts == len(expected_facts)
    assert slice_res.ticks == len(expected_ticks)

    conn_slice = sqlite3.connect(str(slice_target))
    sliced_facts = [
        r[0] for r in conn_slice.execute("SELECT id FROM facts ORDER BY arrival_ordinal, arrival_seq").fetchall()
    ]
    sliced_ticks = [
        r[0] for r in conn_slice.execute("SELECT id FROM ticks ORDER BY arrival_ordinal, arrival_seq").fetchall()
    ]
    conn_slice.close()

    assert sliced_facts == expected_facts, (
        f"Sliced facts do not follow source arrival order: got {sliced_facts}, expected {expected_facts}"
    )
    assert sliced_ticks == expected_ticks, (
        f"Sliced ticks do not follow source arrival order: got {sliced_ticks}, expected {expected_ticks}"
    )

    # 2. Test merge_store into fresh arrival target
    log = ArrivalLog.mint(
        tmp_path / "merged_target.arrival",
        observer="kyle",
        signer=stub_sign,
        key=STUB_KEY,
    )
    merge_target_db = tmp_path / "merged_target.db"
    merge_res = merge_store(target=merge_target_db, source=src_db)
    assert merge_res.facts_added == len(expected_facts)
    assert merge_res.ticks_added == len(expected_ticks)

    conn_merge = sqlite3.connect(str(merge_target_db))
    merged_facts = [
        r[0] for r in conn_merge.execute("SELECT id FROM facts ORDER BY arrival_ordinal, arrival_seq").fetchall()
    ]
    merged_ticks = [
        r[0] for r in conn_merge.execute("SELECT id FROM ticks ORDER BY arrival_ordinal, arrival_seq").fetchall()
    ]
    conn_merge.close()

    assert merged_facts == expected_facts, (
        f"Merged facts do not follow source arrival order: got {merged_facts}, expected {expected_facts}"
    )
    assert merged_ticks == expected_ticks, (
        f"Merged ticks do not follow source arrival order: got {merged_ticks}, expected {expected_ticks}"
    )
