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
    ord_val = conn.execute("SELECT COALESCE(MAX(arrival_ordinal), 0) + 1 FROM facts").fetchone()[0]
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 0)",
        (fid, kind, ts, "kyle", "", json.dumps(payload), ord_val),
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
        assert report == {"late_arrivals": [], "declaration_changed": False, "baseline": "pos1"}

    def test_invalid_store_raises(self, tmp_path):
        """Kills mutant replacing invalid store message with None in diff_interval_report at witness.py:604.

        The store vanishes AFTER the positions resolved: the Law-4 guard
        passes (same resolved path), so the unusable-store branch is the one
        that answers. A position aimed at a DIFFERENT bad path now fails
        structurally first — see TestLaw4Guard.
        """
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        store.unlink()
        with pytest.raises(WitnessResolutionError, match="is not a usable store — cannot compute a diff interval report"):
            diff_interval_report(store, pos, pos)


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
        assert forward["late_arrivals"] == backward["late_arrivals"]
        assert forward["declaration_changed"] == backward["declaration_changed"]
        assert forward["baseline"] == "pos1"
        assert backward["baseline"] == "pos2"
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


class TestLaw4Guard:
    """Cross-store positions fail structurally (CX-BR-03, Law 4).

    diff_interval_report applies verify_position_for_store to BOTH
    positions before any rowid is compared — the same guard every ``at=``
    read selector uses. An unadopted or lineage-foreign position refuses;
    a same-lineage position from another store RE-RESOLVES to this store's
    rowid, which is the behavior upgrade: a cross-replica diff is answered
    correctly instead of silently indexing an unrelated prefix.
    """

    def test_unadopted_cross_store_position_refuses(self, tmp_path):
        from engine.witness import WitnessLineageMismatch

        sa = tmp_path / "a.db"
        _fresh_store(sa)
        _append(sa, "decision", 100, topic="a")
        pos_a = resolve_witness_position(sa, "head")

        sb = tmp_path / "b.db"
        _fresh_store(sb)
        _append(sb, "decision", 100, topic="b")
        pos_b = resolve_witness_position(sb, "head")

        with pytest.raises(WitnessLineageMismatch, match="UNADOPTED handle"):
            diff_interval_report(sb, pos_a, pos_b)
        # Symmetric: the second position is guarded too.
        with pytest.raises(WitnessLineageMismatch, match="UNADOPTED handle"):
            diff_interval_report(sa, pos_a, pos_b)

    def test_foreign_lineage_position_refuses(self, tmp_path):
        from engine.witness import WitnessLineageMismatch
        from lang import parse_vertex_file
        from lang.document import genesis_payload

        def _signer(observer: str, digest: str) -> str:
            return f"sig:{observer}:{digest[:8]}"

        def _adopt(store: Path) -> None:
            vpath = store.with_suffix(".vertex")
            vpath.write_text(
                f'name "t"\nstore "{store}"\nloops {{\n'
                '  decision { fold { items "by" "topic" } }\n}\n'
                'observers { kyle { key "AAAA" } }\n'
            )
            docs = genesis_payload(parse_vertex_file(vpath))["documents"]
            s = SqliteStore(
                path=store, serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )
            s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
            s.close()

        sa = tmp_path / "a.db"
        _adopt(sa)
        _append(sa, "decision", 100, topic="a")
        pos_a = resolve_witness_position(sa, "head")
        assert pos_a.lineage is not None

        sb = tmp_path / "b.db"
        _adopt(sb)  # a different genesis -> different lineage
        _append(sb, "decision", 100, topic="b")
        pos_b = resolve_witness_position(sb, "head")

        with pytest.raises(WitnessLineageMismatch, match="does not match this store's lineage"):
            diff_interval_report(sb, pos_a, pos_b)

    def test_same_lineage_copy_re_resolves_instead_of_refusing(self, tmp_path):
        """A byte-copied store shares the lineage; its positions re-resolve
        by fact id against the target, so the diff answers correctly."""
        import shutil

        from lang import parse_vertex_file
        from lang.document import genesis_payload

        def _signer(observer: str, digest: str) -> str:
            return f"sig:{observer}:{digest[:8]}"

        sa = tmp_path / "a.db"
        vpath = tmp_path / "a.vertex"
        vpath.write_text(
            f'name "t"\nstore "{sa}"\nloops {{\n'
            '  decision { fold { items "by" "topic" } }\n}\n'
            'observers { kyle { key "AAAA" } }\n'
        )
        docs = genesis_payload(parse_vertex_file(vpath))["documents"]
        s = SqliteStore(
            path=sa, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        )
        s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
        s.close()
        _append(sa, "decision", 100, topic="a")
        pos_early = resolve_witness_position(sa, "head")
        assert pos_early.lineage is not None

        sb = tmp_path / "b.db"
        shutil.copy(sa, sb)  # legal byte copy, same lineage
        _append(sb, "decision", 200, topic="b")
        pos_late = resolve_witness_position(sb, "head")

        report = diff_interval_report(sb, pos_early, pos_late)
        assert report["declaration_changed"] is False
        assert report["late_arrivals"] == []
