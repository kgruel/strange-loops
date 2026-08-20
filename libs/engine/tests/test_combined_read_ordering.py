"""_combined_read under a DECLARED ordering (Cut C, Q2).

'arrival' is single-store-only: a combine-of-one reads on the arrival axis by
default, an aggregate of several reads on the ``(ts, id)`` lens, and declaring
``Arrival()`` on an aggregate is refused.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Arrival, ByKey, OrderingError

from engine.vertex_reader import _combined_read, resolve_ordering

from .test_vertex_reader import _seed_facts, _setup_combine_env


# Backdated ts against append order: fact ids ascend with rowid, ts does NOT.
# Row 0 lands first but carries the LATEST ts, so arrival order and (ts, id)
# order disagree on every adjacent pair — the fixture discriminates.
_INTERLEAVED = [
    {"id": "F0", "kind": "decision", "ts": 4000.0, "payload": {"topic": "t", "seq": 0}},
    {"id": "F1", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t", "seq": 1}},
    {"id": "F2", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t", "seq": 2}},
    {"id": "F3", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t", "seq": 3}},
]

_ARRIVAL_IDS = ["F0", "F1", "F2", "F3"]
_TS_IDS = ["F1", "F3", "F2", "F0"]


def _single_member_vertex(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """A combine-of-ONE aggregate — the shape the old rowid sort served."""
    home = tmp_path / "loops_home"
    solo_dir = home / "solo"
    solo_dir.mkdir(parents=True)
    (solo_dir / "solo.vertex").write_text(
        'name "solo"\nstore "./store.db"\n'
        'loops {\n  decision { fold { items "collect" 10 } }\n}\n'
    )
    combine = tmp_path / "combined.vertex"
    combine.write_text(
        'name "combined"\ncombine {\n    vertex "solo"\n}\n'
        'loops {\n  decision { fold { items "collect" 10 } }\n}\n'
    )
    monkeypatch.setenv("LOOPS_HOME", str(home))
    return combine, solo_dir / "store.db"


def _fold_ids(vertex_path: Path, **kwargs) -> list[str]:
    """Replay ids in the order _combined_read handed them to the fold."""
    from engine.compiler import compile_vertex
    from engine.declaration import load_declaration

    ast = load_declaration(vertex_path)
    _, payloads = _combined_read(
        ast, vertex_path, compile_vertex(ast), return_payloads=True, **kwargs
    )
    return [p["_id"] for p in payloads["decision"]]


def _rowid_ids_by_direct_sqlite(db_path: Path) -> list[str]:
    """The OLD single-store semantics, read straight off sqlite.

    Independent of production code: the pin compares against this, not against
    anything the new path computes.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT id, rowid FROM facts").fetchall()
    finally:
        conn.close()
    rows.sort(key=lambda r: r[1])
    return [r[0] for r in rows]


class TestSingleStoreArrivalEquivalence:
    """GATE item 3: single-store Arrival() ≡ the old rowid sequence."""

    def test_the_fixture_discriminates_arrival_from_event_time(self, tmp_path, monkeypatch):
        """Guard on the pin below: ts order must NOT equal arrival order."""
        _, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _rowid_ids_by_direct_sqlite(db) == _ARRIVAL_IDS
        conn = sqlite3.connect(str(db))
        try:
            ts_order = [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY ts, id")]
        finally:
            conn.close()
        assert ts_order == _TS_IDS
        assert ts_order != _ARRIVAL_IDS

    def test_declared_arrival_reproduces_the_old_rowid_sequence(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        expected = _rowid_ids_by_direct_sqlite(db)
        assert _fold_ids(vpath, ordering=Arrival()) == expected

    def test_the_single_store_default_is_arrival(self, tmp_path, monkeypatch):
        """No declared ordering ≡ declared Arrival() ≡ the old sequence."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath) == _rowid_ids_by_direct_sqlite(db) == _ARRIVAL_IDS

    def test_a_single_store_may_declare_bykey_instead(self, tmp_path, monkeypatch):
        """Arrival is the default, not the only option, on one store."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath, ordering=ByKey("ts")) == _TS_IDS


class TestAggregateOrdering:
    """GATE item 4: aggregates are ByKey; Arrival() on one refuses loudly."""

    def test_the_aggregate_default_is_event_time(self, tmp_path, monkeypatch):
        vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)
        _seed_facts(alpha_db, [
            {"id": "A1", "kind": "decision", "ts": 4000.0, "payload": {"topic": "t"}},
            {"id": "A2", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t"}},
        ])
        _seed_facts(beta_db, [
            {"id": "B1", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t"}},
            {"id": "B2", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t"}},
        ])

        assert _fold_ids(vpath) == ["A2", "B2", "B1", "A1"]

    def test_declaring_arrival_on_an_aggregate_refuses(self, tmp_path, monkeypatch):
        vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)
        _seed_facts(alpha_db, [
            {"id": "A1", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t"}},
        ])
        _seed_facts(beta_db, [
            {"id": "B1", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t"}},
        ])

        with pytest.raises(OrderingError) as excinfo:
            _fold_ids(vpath, ordering=Arrival())

        message = str(excinfo.value)
        # Names the REASON...
        assert "dense per-log" in message
        assert "no cross-store" in message or "has no cross-store" in message
        # ...and the ALTERNATIVE.
        assert "ByKey" in message


class TestResolveOrdering:
    """The one place the Q2 defaults and the refusal are defined."""

    def test_defaults(self):
        assert resolve_ordering(None, single_store=True) == Arrival()
        assert resolve_ordering(None, single_store=False) == ByKey("ts")

    def test_declared_orderings_pass_through(self):
        assert resolve_ordering(Arrival(), single_store=True) == Arrival()
        assert resolve_ordering(ByKey("ts"), single_store=True) == ByKey("ts")
        assert resolve_ordering(ByKey("seq"), single_store=False) == ByKey("seq")

    def test_arrival_on_an_aggregate_refuses(self):
        with pytest.raises(OrderingError, match="dense per-log"):
            resolve_ordering(Arrival(), single_store=False)


class TestRowAccessors:
    """Column-backed keys read off the tuple; payload keys cost a parse."""

    def test_bykey_on_a_payload_field(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, [
            {"id": "P0", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t", "n": 3}},
            {"id": "P1", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t", "n": 1}},
            {"id": "P2", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t", "n": 2}},
        ])

        assert _fold_ids(vpath, ordering=ByKey("n")) == ["P1", "P2", "P0"]

    def test_bykey_on_id_reads_the_id_column(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath, ordering=ByKey("id")) == ["F0", "F1", "F2", "F3"]

    def test_a_fact_missing_the_declared_key_is_not_in_the_projection(
        self, tmp_path, monkeypatch
    ):
        """Exclusion-by-declaration reaches the FOLD INPUT, not just the page."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, [
            {"id": "K0", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t", "n": 2}},
            {"id": "K1", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t"}},
            {"id": "K2", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t", "n": 1}},
        ])

        assert _fold_ids(vpath, ordering=ByKey("n")) == ["K2", "K0"]


class TestUntilTsStillCaps:
    """The event-time cursor is orthogonal to the declared ordering."""

    def test_until_ts_caps_under_arrival(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath, ordering=Arrival(), until_ts=2500.0) == ["F1", "F3"]

    def test_payload_shape_is_untouched(self, tmp_path, monkeypatch):
        """The ordering rewrite did not disturb the _-prefixed row projection."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED[:1])

        from engine.compiler import compile_vertex
        from engine.declaration import load_declaration

        ast = load_declaration(vpath)
        _, payloads = _combined_read(
            ast, vpath, compile_vertex(ast), return_payloads=True
        )
        p = payloads["decision"][0]
        assert p["_id"] == "F0"
        assert p["_ts"] == 4000.0
        assert p["_observer"] == "test"
        assert p["_origin"] == ""
        assert p["seq"] == 0
        assert json.loads(json.dumps(p))  # plain JSON, no tuple leakage
