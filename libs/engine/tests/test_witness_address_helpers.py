"""CLI address-grammar helpers — seq:N / tick:ID / wall-clock (0.8.0 C1).

Proves the three small engine-seam resolvers the CLI address grammar needs
to map ``seq:N`` / ``tick:ID`` / ISO wall-clock addresses onto a fact id
before handing it to ``resolve_witness_position`` (which owns identity
resolution, the receipt-group guard, and everything else):

- ``resolve_seq`` — the inverse of ``WitnessPosition.seq`` (N -> fact id).
- ``resolve_tick_cursor`` — a tick's own id -> its ``fact_cursor``.
- ``resolve_tick_floor`` — the wall-clock tick-floor snap (A5).

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact

from engine.sqlite_store import SqliteStore, gen_id
from engine.witness import (
    NoWitnessAnchor,
    SeqOutOfRange,
    UnknownTickHandle,
    resolve_seq,
    resolve_tick_cursor,
    resolve_tick_floor,
    resolve_witness_position,
)


def _fresh_store(store: Path) -> None:
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _append(store: Path, kind: str, ts: float, *, fid: str | None = None, **payload) -> str:
    conn = sqlite3.connect(str(store))
    fid = fid or gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (fid, kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()
    return fid


def _append_tick(
    store: Path, name: str, ts: float, *, fact_cursor: str | None = None
) -> str:
    conn = sqlite3.connect(str(store))
    tid = gen_id()
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload, fact_cursor) "
        "VALUES (?, ?, ?, 0.0, '', '{}', ?)",
        (tid, name, ts, fact_cursor),
    )
    conn.commit()
    conn.close()
    return tid


class TestResolveSeq:
    def test_resolves_nth_row_in_rowid_order(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        first = _append(store, "decision", 100, topic="a")
        second = _append(store, "decision", 101, topic="b")
        assert resolve_seq(store, 1) == first
        assert resolve_seq(store, 2) == second

    def test_seq_feeds_resolve_witness_position(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        first = _append(store, "decision", 100, topic="a")
        _append(store, "decision", 101, topic="b")
        fid = resolve_seq(store, 1)
        pos = resolve_witness_position(store, fid)
        assert pos.fact_id == first and pos.seq == 1

    def test_zero_or_negative_out_of_range(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(SeqOutOfRange):
            resolve_seq(store, 0)
        with pytest.raises(SeqOutOfRange):
            resolve_seq(store, -1)

    def test_beyond_total_out_of_range(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(SeqOutOfRange, match="has 1 receipt"):
            resolve_seq(store, 5)


class TestResolveTickCursor:
    def test_resolves_fact_cursor_of_named_tick(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        tid = _append_tick(store, "project", 150.0, fact_cursor=f1)
        cursor, name, ts = resolve_tick_cursor(store, tid)
        assert cursor == f1 and name == "project" and ts == 150.0

    def test_unknown_tick_id_refuses(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(UnknownTickHandle):
            resolve_tick_cursor(store, "01NONEXISTENTTICKID00000000")

    def test_tick_with_no_cursor_has_no_anchor(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        tid = _append_tick(store, "project", 150.0, fact_cursor=None)
        with pytest.raises(NoWitnessAnchor):
            resolve_tick_cursor(store, tid)


class TestResolveTickFloor:
    def test_snaps_to_last_chained_tick_at_or_before_mark(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "project", 150.0, fact_cursor=f1)
        f2 = _append(store, "decision", 200, topic="b")
        _append_tick(store, "project", 250.0, fact_cursor=f2)

        # Mark between the two ticks — floor is the FIRST tick.
        cursor, name, ts = resolve_tick_floor(store, 175.0)
        assert cursor == f1 and ts == 150.0

        # Mark after both — floor is the SECOND (newest at-or-before).
        cursor2, _, ts2 = resolve_tick_floor(store, 300.0)
        assert cursor2 == f2 and ts2 == 250.0

    def test_no_tick_before_mark_refuses(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "project", 150.0, fact_cursor=f1)
        with pytest.raises(NoWitnessAnchor):
            resolve_tick_floor(store, 50.0)  # before the only tick

    def test_no_ticks_at_all_refuses(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(NoWitnessAnchor):
            resolve_tick_floor(store, 200.0)

    def test_unchained_tick_is_skipped(self, tmp_path):
        # A pre-chain tick (empty fact_cursor) does not satisfy the floor —
        # never a silent approximation.
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        _append_tick(store, "project", 150.0, fact_cursor=None)
        with pytest.raises(NoWitnessAnchor):
            resolve_tick_floor(store, 200.0)
