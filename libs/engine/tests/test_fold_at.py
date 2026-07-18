"""fold-state-as-of — vertex_fold at a witness position (0.8.0 session 1, E2).

Proves the full-reconstruction fold-at: the prefix `rowid <= at.rowid` is
selected, ontology resolves from the SAME prefix (equal cursors), replay is
`(ts, id)` (never append order — a backdated arrival inserts early), and the
result is a machine-readable `WitnessFold` envelope (fold + position + mode +
honesty status, A11). Aggregates are refused — witness order is per-member.

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact
from atoms.fold_state import FoldState
from lang import parse_vertex_file
from lang.document import DECL_GENESIS, DECL_KIND_DEFINED, genesis_payload

from engine import vertex_fold
from engine.declaration import DECLARATION_STATUSES
from engine.sqlite_store import SqliteStore, gen_id
from engine.witness import (
    WitnessAggregateUnsupported,
    WitnessFold,
    resolve_witness_position,
)

_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }}
             search "message" }}
  thread {{ fold {{ items "by" "name" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    return vpath, store


def _fresh_store(store: Path) -> None:
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _absorb(vpath: Path, store: Path) -> str:
    ast = parse_vertex_file(vpath)
    docs = genesis_payload(ast)["documents"]
    s = SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    lineage = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)["lineage"]
    s.close()
    return lineage


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


def _section(fold_state, kind: str):
    return next(s for s in fold_state.sections if s.kind == kind)


# ---------------------------------------------------------------------------
# Envelope shape + backward compatibility
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_at_none_returns_bare_fold_state(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a", message="alpha")
        result = vertex_fold(vpath)
        assert isinstance(result, FoldState)  # unchanged head contract

    def test_at_returns_witness_fold_envelope(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a", message="alpha")
        pos = resolve_witness_position(store, "head")
        result = vertex_fold(vpath, at=pos)
        assert isinstance(result, WitnessFold)
        assert result.mode == "witness"
        assert result.position == pos
        assert result.status in DECLARATION_STATUSES
        assert isinstance(result.fold, FoldState)


# ---------------------------------------------------------------------------
# Full reconstruction — the prefix is exactly what the position had received
# ---------------------------------------------------------------------------


class TestPrefixReconstruction:
    def test_position_excludes_later_facts(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="x", message="alpha")
        pos = resolve_witness_position(store, "head")  # after x only
        _append(store, "decision", 101, topic="y", message="beta")  # later

        at_pos = vertex_fold(vpath, at=pos)
        at_head = vertex_fold(vpath, at=resolve_witness_position(store, "head"))

        topics_at_pos = {i.payload["topic"] for i in _section(at_pos.fold, "decision").items}
        topics_at_head = {i.payload["topic"] for i in _section(at_head.fold, "decision").items}
        assert topics_at_pos == {"x"}  # the later 'y' was not yet received
        assert topics_at_head == {"x", "y"}

    def test_backdated_arrival_replayed_by_ts_id_not_append_order(self, tmp_path):
        # A: topic x, ts=100, message alpha (rowid 1).
        # B: topic x, ts=50 (backdated), message beta, appended LATER (rowid 2).
        # At head both are in the prefix (n=2) but (ts,id) replay puts B first,
        # so A (higher ts) wins Latest — append order would have made B win.
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="x", message="alpha")
        pos_after_a = resolve_witness_position(store, "head")
        _append(store, "decision", 50, topic="x", message="beta")  # backdated

        early = _section(vertex_fold(vpath, at=pos_after_a).fold, "decision")
        head = _section(
            vertex_fold(vpath, at=resolve_witness_position(store, "head")).fold,
            "decision",
        )

        [item_early] = early.items
        [item_head] = head.items
        assert item_early.payload["message"] == "alpha" and item_early.n == 1
        # B is genuinely in the prefix at head (upsert count 2)...
        assert item_head.n == 2
        # ...but replay is (ts, id): A (ts 100) wins over the backdated B (ts 50).
        assert item_head.payload["message"] == "alpha"


# ---------------------------------------------------------------------------
# Equal cursors — ontology resolves from the same prefix
# ---------------------------------------------------------------------------


class TestEqualCursorsOntology:
    def test_ontology_folds_from_the_same_prefix(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)  # genesis rowid 1, decision folds by topic
        # Rekey overlay topic→name at rowid 2.
        _append(
            store, DECL_KIND_DEFINED, 1000.0, fid="rekey",
            lineage=lineage, subject="decision",
            payload={"order": 0, "search": ["message"],
                     "folds": [{"target": "items",
                                "op": {"op": "by", "key_field": "name"}}]},
        )
        _append(store, "decision", 2000.0, topic="d", name="dee", message="m")  # rowid 3

        conn = sqlite3.connect(str(store))
        gid = conn.execute(
            "SELECT id FROM facts WHERE kind = ?", (DECL_GENESIS,)
        ).fetchone()[0]
        conn.close()

        # Position AT genesis (before the rekey) → old ontology (topic).
        at_genesis = resolve_witness_position(store, gid)
        # Head (rekey in prefix) → new ontology (name).
        at_head = resolve_witness_position(store, "head")

        assert _section(vertex_fold(vpath, at=at_genesis).fold, "decision").key_field == "topic"
        assert _section(vertex_fold(vpath, at=at_head).fold, "decision").key_field == "name"


# ---------------------------------------------------------------------------
# Honesty status (N3)
# ---------------------------------------------------------------------------


class TestHonestyStatus:
    def test_pre_genesis_fold_reports_file_pre_genesis(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a", message="alpha")
        pos = resolve_witness_position(store, "head")
        assert vertex_fold(vpath, at=pos).status == "file-pre-genesis"

    def test_adopted_fold_reports_store(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        _append(store, "decision", 100, topic="a", message="alpha")
        pos = resolve_witness_position(store, "head")
        assert vertex_fold(vpath, at=pos).status == "store"


# ---------------------------------------------------------------------------
# Aggregate refusal (A1/A9)
# ---------------------------------------------------------------------------


def test_witness_fold_refuses_aggregate(tmp_path):
    member_v = tmp_path / "member.vertex"
    member_db = tmp_path / "member.db"
    member_v.write_text(_VERTEX_KDL.format(store=member_db))
    _fresh_store(member_db)
    _append(member_db, "decision", 100, topic="a", message="alpha")

    agg = tmp_path / "agg.vertex"
    agg.write_text(f'name "agg"\ncombine {{\n  vertex "{member_v}"\n}}\n')

    pos = resolve_witness_position(member_db, "head")
    with pytest.raises(WitnessAggregateUnsupported):
        vertex_fold(agg, at=pos)
