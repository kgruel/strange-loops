"""fold-state-``as_of`` — vertex_fold's event-time projection (0.8.0 C1 rider).

Proves the sibling of ``at=`` (test_fold_at.py): ``as_of`` selects facts by
``ts <= as_of`` (not a witness prefix) and resolves ontology via the existing
``load_declaration`` ``as_of`` seam — equal ts cursors both axes. Unlike
``at=``, this is allowed on combine/discover aggregates (uniform event-time
is well-posed: current membership, each member's facts cut by the same
cutoff — A9's rider).

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
from lang.document import genesis_payload

from engine import vertex_fold
from engine.sqlite_store import SqliteStore, gen_id
from engine.witness import WitnessFold, resolve_witness_position

_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }}
             search "message" }}
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


class TestAsOfSelectsByTimestamp:
    def test_excludes_facts_after_the_cutoff(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="x", message="alpha")
        _append(store, "decision", 200, topic="y", message="beta")

        at_150 = vertex_fold(vpath, as_of=150.0)
        at_head = vertex_fold(vpath)

        assert isinstance(at_150, FoldState)  # bare state, no envelope
        topics_150 = {i.payload["topic"] for i in _section(at_150, "decision").items}
        topics_head = {i.payload["topic"] for i in _section(at_head, "decision").items}
        assert topics_150 == {"x"}
        assert topics_head == {"x", "y"}

    def test_inclusive_cutoff(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="x", message="alpha")
        state = vertex_fold(vpath, as_of=100.0)
        assert {i.payload["topic"] for i in _section(state, "decision").items} == {"x"}


class TestAsOfOntologyEqualCursors:
    def test_ontology_resolves_at_the_same_cutoff(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)  # genesis (real wall-clock ts), decision by topic
        genesis_ts = _read_genesis_ts(store)
        from lang.document import DECL_KIND_DEFINED

        rekey_ts = genesis_ts + 1000.0
        _append(
            store, DECL_KIND_DEFINED, rekey_ts, fid="rekey",
            lineage=_read_lineage(store), subject="decision",
            payload={"order": 0, "search": ["message"],
                     "folds": [{"target": "items",
                                "op": {"op": "by", "key_field": "name"}}]},
        )
        _append(store, "decision", rekey_ts + 1000.0, topic="d", name="dee", message="m")

        before_rekey = vertex_fold(vpath, as_of=genesis_ts + 500.0)
        after_rekey = vertex_fold(vpath, as_of=rekey_ts + 500.0)
        assert _section(before_rekey, "decision").key_field == "topic"
        assert _section(after_rekey, "decision").key_field == "name"


def _read_lineage(store: Path) -> str:
    from lang.document import DECL_GENESIS

    conn = sqlite3.connect(str(store))
    gid = conn.execute(
        "SELECT id FROM facts WHERE kind = ?", (DECL_GENESIS,)
    ).fetchone()[0]
    conn.close()
    return gid


def _read_genesis_ts(store: Path) -> float:
    from lang.document import DECL_GENESIS

    conn = sqlite3.connect(str(store))
    ts = conn.execute(
        "SELECT ts FROM facts WHERE kind = ?", (DECL_GENESIS,)
    ).fetchone()[0]
    conn.close()
    return ts


class TestMutualExclusion:
    def test_as_of_and_at_together_raises(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a", message="m")
        pos = resolve_witness_position(store, "head")
        with pytest.raises(ValueError):
            vertex_fold(vpath, as_of=100.0, at=pos)


class TestAggregateAllowed:
    def test_as_of_allowed_on_aggregate_current_membership(self, tmp_path):
        member_v = tmp_path / "member.vertex"
        member_db = tmp_path / "member.db"
        member_v.write_text(_VERTEX_KDL.format(store=member_db))
        _fresh_store(member_db)
        _append(member_db, "decision", 100, topic="x", message="alpha")
        _append(member_db, "decision", 200, topic="y", message="beta")

        agg = tmp_path / "agg.vertex"
        agg.write_text(f'name "agg"\ncombine {{\n  vertex "{member_v}"\n}}\n')

        state = vertex_fold(agg, as_of=150.0)
        assert isinstance(state, FoldState)
        topics = {i.payload["topic"] for i in _section(state, "decision").items}
        assert topics == {"x"}  # 'y' (ts=200) is cut by the as_of=150 window
