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
    TickAnchor,
    UnknownTickHandle,
    UnknownWitnessHandle,
    WitnessResolutionError,
    expand_fact_prefix,
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

    def test_resolve_seq_invalid_store_raises(self, tmp_path):
        """Kills mutant replacing invalid store message with None in resolve_seq at witness.py:680."""
        with pytest.raises(WitnessResolutionError, match="is not a usable store — cannot resolve seq:1"):
            resolve_seq(tmp_path / "nope.db", 1)


class TestResolveTickCursor:
    def test_resolves_fact_cursor_of_named_tick(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        tid = _append_tick(store, "project", 150.0, fact_cursor=f1)
        cursor, name, ts = resolve_tick_cursor(store, tid)
        assert cursor == f1 and name == "project" and ts == 150.0

    def test_unknown_tick_id_refuses(self, tmp_path):
        """Kills mutant replacing UnknownTickHandle message with None at witness.py:744."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(UnknownTickHandle, match="no tick with id '01NONEXISTENTTICKID00000000' in this store"):
            resolve_tick_cursor(store, "01NONEXISTENTTICKID00000000")

    def test_tick_with_no_cursor_has_no_anchor(self, tmp_path):
        """Kills mutant replacing NoWitnessAnchor message with None on unchained tick at witness.py:747."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        tid = _append_tick(store, "project", 150.0, fact_cursor=None)
        with pytest.raises(NoWitnessAnchor, match="has no witness anchor — a pre-chain tick was never bound to a fact_cursor"):
            resolve_tick_cursor(store, tid)

    def test_resolve_tick_cursor_invalid_store_raises(self, tmp_path):
        """Kills mutant replacing invalid store message with None in resolve_tick_cursor at witness.py:720."""
        with pytest.raises(WitnessResolutionError, match="is not a usable store — cannot resolve tick:t1"):
            resolve_tick_cursor(tmp_path / "nope.db", "t1")

    def test_pre_chain_schema_tick_raises_no_witness_anchor(self, tmp_path):
        """Kills mutants in pre-chain schema branch without fact_cursor column in resolve_tick_cursor at witness.py:726-738."""
        store = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(store))
        conn.execute(
            "CREATE TABLE ticks (id TEXT PRIMARY KEY, name TEXT, ts REAL, since REAL, origin TEXT, payload TEXT)"
        )
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES ('t1', 'old_tick', 100.0, 0.0, '', '{}')"
        )
        conn.commit()
        conn.close()
        with pytest.raises(
            NoWitnessAnchor,
            match="tick:t1 \\(old_tick @ 100\\.0\\) predates the witness-chain era \\(no fact_cursor column\\)",
        ):
            resolve_tick_cursor(store, "t1")

    def test_pre_chain_schema_unknown_tick_raises_unknown_tick_handle(self, tmp_path):
        """Kills mutant replacing UnknownTickHandle message with None on pre-chain schema at witness.py:730."""
        store = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(store))
        conn.execute(
            "CREATE TABLE ticks (id TEXT PRIMARY KEY, name TEXT, ts REAL, since REAL, origin TEXT, payload TEXT)"
        )
        conn.commit()
        conn.close()
        with pytest.raises(UnknownTickHandle, match="no tick with id 't_missing' in this store"):
            resolve_tick_cursor(store, "t_missing")


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
        """Kills mutant replacing NoWitnessAnchor message with None in resolve_tick_floor at witness.py:798."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "project", 150.0, fact_cursor=f1)
        with pytest.raises(NoWitnessAnchor, match="no witness-time anchor — no sealed tick at or before this mark"):
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

    def test_dangling_cursor_refuses_with_as_of_teaching(self, tmp_path):
        # Review finding 7b: the only pre-mark tick carries a fact_cursor that
        # resolves to NO fact (a merged/dangling cursor). It must NOT be treated
        # as usable — the JOIN skips it, so the floor scan finds nothing and
        # raises the honest NoWitnessAnchor refusal (not a downstream
        # unknown-fact error).
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        _append_tick(store, "project", 150.0, fact_cursor="01DANGLINGCURSORNOFACT00000")
        with pytest.raises(NoWitnessAnchor):
            resolve_tick_floor(store, 200.0)

    def test_dangling_cursor_scan_continues_to_a_resolvable_tick(self, tmp_path):
        # A dangling-cursor tick is skipped, but an EARLIER tick with a
        # resolvable cursor is a valid floor — the scan continues past the hole.
        store = tmp_path / "t.db"
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "good", 120.0, fact_cursor=f1)  # resolvable
        _append_tick(store, "bad", 150.0, fact_cursor="01DANGLINGCURSOR0000000000")
        cursor, name, ts = resolve_tick_floor(store, 200.0)
        assert cursor == f1 and name == "good" and ts == 120.0

    def test_resolve_tick_floor_invalid_store_raises(self, tmp_path):
        """Kills mutant replacing invalid store message with None in resolve_tick_floor at witness.py:780."""
        with pytest.raises(WitnessResolutionError, match="is not a usable store — cannot resolve a wall-clock address"):
            resolve_tick_floor(tmp_path / "nope.db", 100.0)


class TestExpandFactPrefix:
    # The engine-owned fact:prefix resolver — the app must not touch StoreReader
    # (architecture ratchet); this is where the store access lives now.
    def test_exact_and_prefix(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        full = _append(store, "decision", 100, fid="01KABCDEF00000000000000001", topic="a")
        assert expand_fact_prefix(store, full) == full
        assert expand_fact_prefix(store, "01KABCDEF") == full

    def test_resolves_internal_decl_rows_too(self, tmp_path):
        # Witness identity is over ALL rows — a _decl.* id is addressable.
        store = tmp_path / "t.db"
        _fresh_store(store)
        did = _append(store, "_decl.genesis", 50, fid="01KDECL0000000000000000001")
        assert expand_fact_prefix(store, "01KDECL") == did

    def test_no_match_raises_unknown_handle(self, tmp_path):
        """Kills mutant replacing UnknownWitnessHandle message with None at witness.py:658."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(UnknownWitnessHandle, match="no fact matches 'ZZZNONEXISTENT' in this store"):
            expand_fact_prefix(store, "ZZZNONEXISTENT")

    def test_ambiguous_prefix_raises_value_error(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, fid="01KSHARED0000000000000000A1", topic="a")
        _append(store, "decision", 101, fid="01KSHARED0000000000000000B2", topic="b")
        with pytest.raises(ValueError):
            expand_fact_prefix(store, "01KSHARED")


class TestAnchorPreservation:
    def test_floor_tick_preserved_not_re_derived(self, tmp_path):
        # Review finding 7a: two ticks seal the SAME fact_cursor — an earlier one
        # (the wall-clock floor) and a later one PAST the mark. resolve_tick_floor
        # picks the floor; passing it as anchor= to resolve_witness_position
        # preserves it. Re-deriving from the cursor would instead name the later
        # tick (the finding-5 tie-break picks the last-appended sealing tick).
        store = tmp_path / "t.db"
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "floor", 150.0, fact_cursor=f1)
        _append_tick(store, "later", 250.0, fact_cursor=f1)  # after the mark

        cursor, name, ts = resolve_tick_floor(store, 175.0)  # mark between ticks
        assert name == "floor" and ts == 150.0

        # WITHOUT preservation, the anchor is re-derived and names the LATER tick
        # (last-appended sealing the same cursor) — the bug.
        re_derived = resolve_witness_position(store, cursor)
        assert re_derived.anchor is not None and re_derived.anchor.name == "later"

        # WITH preservation (the fix), the position reports the floor tick.
        preserved = resolve_witness_position(
            store, cursor, anchor=TickAnchor(name=name, ts=ts, fact_cursor=cursor)
        )
        assert preserved.anchor is not None
        assert preserved.anchor.name == "floor" and preserved.anchor.ts == 150.0
