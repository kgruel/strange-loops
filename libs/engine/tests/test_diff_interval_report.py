"""diff_interval_report — --diff honesty info (0.8.0 capstone M8/A13).

Proves the two things a bare structural (kind, key) diff cannot see between
two witness positions: a late arrival (a fact received in the interval whose
ts predates what the earlier position already replayed) and a declaration
change within the interval.

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
    GENESIS_SENTINEL,
    WitnessResolutionError,
    diff_interval_report,
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


class TestNoInterval:
    def test_same_position_reports_nothing(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        report = diff_interval_report(store, pos, pos)
        assert report == {"late_arrivals": [], "declaration_changed": False}

    def test_invalid_store_raises(self, tmp_path):
        """Kills mutant replacing invalid store message with None in diff_interval_report at witness.py:604."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        with pytest.raises(WitnessResolutionError, match="is not a usable store — cannot compute a diff interval report"):
            diff_interval_report(tmp_path / "nope.db", pos, pos)


class TestLateArrivals:
    def test_diff_from_empty_prefix_returns_empty_list_for_late_arrivals(self, tmp_path):
        """Kills mutant replacing late_arrivals: list[dict] = [] with None at witness.py:617."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        pos1 = resolve_witness_position(store, GENESIS_SENTINEL)
        _append(store, "decision", 100, topic="a")
        pos2 = resolve_witness_position(store, "head")
        report = diff_interval_report(store, pos1, pos2)
        assert report["late_arrivals"] == []
        assert isinstance(report["late_arrivals"], list)

    def test_backdated_arrival_in_interval_is_reported(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")  # rowid 1, ts=100
        pos1 = resolve_witness_position(store, "head")
        late_id = _append(store, "decision", 50, topic="b")  # rowid 2, ts=50 (backdated)
        pos2 = resolve_witness_position(store, "head")

        report = diff_interval_report(store, pos1, pos2)
        assert len(report["late_arrivals"]) == 1
        entry = report["late_arrivals"][0]
        assert entry["id"] == late_id and entry["kind"] == "decision" and entry["ts"] == 50

    def test_forward_dated_arrival_is_not_a_late_arrival(self, tmp_path):
        # An arrival with a LATER ts than what pos1 already saw is not "late"
        # — it's a normal forward-moving receipt.
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos1 = resolve_witness_position(store, "head")
        _append(store, "decision", 200, topic="b")
        pos2 = resolve_witness_position(store, "head")

        report = diff_interval_report(store, pos1, pos2)
        assert report["late_arrivals"] == []

    def test_symmetric_by_rowid_b_before_a(self, tmp_path):
        # --diff B..A (later position named first) reports identically.
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos1 = resolve_witness_position(store, "head")
        late_id = _append(store, "decision", 50, topic="b")
        pos2 = resolve_witness_position(store, "head")

        forward = diff_interval_report(store, pos1, pos2)
        backward = diff_interval_report(store, pos2, pos1)
        assert forward == backward
        assert forward["late_arrivals"][0]["id"] == late_id

    def test_decl_rows_excluded_from_late_arrivals(self, tmp_path):
        from lang.document import DECL_KIND_DEFINED

        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos1 = resolve_witness_position(store, "head")
        _append(
            store, DECL_KIND_DEFINED, 50, lineage="x", subject="decision",
            payload={"folds": [], "order": 0},
        )
        pos2 = resolve_witness_position(store, "head")

        report = diff_interval_report(store, pos1, pos2)
        assert report["late_arrivals"] == []  # _decl.* rows never counted


class TestDeclarationChanged:
    def test_decl_row_in_interval_flags_true(self, tmp_path):
        from lang.document import DECL_KIND_DEFINED

        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos1 = resolve_witness_position(store, "head")
        _append(
            store, DECL_KIND_DEFINED, 200, lineage="x", subject="decision",
            payload={"folds": [], "order": 0},
        )
        pos2 = resolve_witness_position(store, "head")

        report = diff_interval_report(store, pos1, pos2)
        assert report["declaration_changed"] is True

    def test_no_decl_row_in_interval_flags_false(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos1 = resolve_witness_position(store, "head")
        _append(store, "decision", 200, topic="b")
        pos2 = resolve_witness_position(store, "head")

        report = diff_interval_report(store, pos1, pos2)
        assert report["declaration_changed"] is False
