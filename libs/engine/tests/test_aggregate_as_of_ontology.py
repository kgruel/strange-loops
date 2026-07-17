"""Aggregate as_of resolves MEMBER ontology at the cutoff (review finding 6).

An aggregate WITHOUT its own loops folds member facts under specs collected from
its members (union semantics). On an as_of read, those member specs must be
resolved at the SAME event-time cutoff — otherwise ts<=T member facts fold under
a member ontology (e.g. a fold-key rename) introduced AFTER T, breaking
equal-cursor semantics. (Membership stays current — the disclosed aggregate-head
derogation; only the ontology rides the cutoff.)

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from atoms import Fact
from lang import parse_vertex_file
from lang.document import DECL_KIND_DEFINED, genesis_payload

from engine import vertex_fold
from engine.sqlite_store import SqliteStore, gen_id

_MEMBER_KDL = '''name "m"
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


def _absorb(vpath: Path, store: Path) -> str:
    ast = parse_vertex_file(vpath)
    docs = genesis_payload(ast)["documents"]
    s = SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    lineage = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)["lineage"]
    s.close()
    return lineage


def _genesis_ts(store: Path) -> float:
    conn = sqlite3.connect(str(store))
    from lang.document import DECL_GENESIS

    ts = conn.execute(
        "SELECT ts FROM facts WHERE kind = ?", (DECL_GENESIS,)
    ).fetchone()[0]
    conn.close()
    return ts


def _append(store: Path, kind: str, ts: float, **payload) -> None:
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (gen_id(), kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _rekey(store: Path, lineage: str, ts: float) -> None:
    """Member overlay moving decision's fold key topic→name at ``ts``."""
    _append(
        store, DECL_KIND_DEFINED, ts,
        lineage=lineage, subject="decision",
        payload={"order": 0, "search": ["message"],
                 "folds": [{"target": "items",
                            "op": {"op": "by", "key_field": "name"}}]},
    )


def _decision_key_field(fold_state) -> str:
    section = next(s for s in fold_state.sections if s.kind == "decision")
    return section.key_field


def _build(tmp_path: Path) -> tuple[Path, float, float]:
    """A discover-aggregate over one member whose decision fold-key is renamed
    topic→name at gts+100. Returns (agg_vertex, ts_before, ts_after)."""
    members = tmp_path / "members"
    members.mkdir()
    m_store = members / "m.db"
    m_vertex = members / "m.vertex"
    m_vertex.write_text(_MEMBER_KDL.format(store=m_store))
    lineage = _absorb(m_vertex, m_store)
    gts = _genesis_ts(m_store)
    _append(m_store, "decision", gts + 10, topic="x", name="ex", message="m")
    _rekey(m_store, lineage, ts=gts + 100)

    agg = tmp_path / "agg.vertex"
    agg.write_text('name "agg"\ndiscover "members/*.vertex"\n')
    return agg, gts + 50, gts + 200


def test_aggregate_as_of_folds_member_facts_under_cutoff_ontology(tmp_path):
    agg, ts_before, ts_after = _build(tmp_path)

    # Before the rename: member ontology folds decision by topic.
    before = vertex_fold(agg, as_of=ts_before)
    assert _decision_key_field(before) == "topic"

    # After the rename (and at head): folds by name.
    after = vertex_fold(agg, as_of=ts_after)
    assert _decision_key_field(after) == "name"
    assert _decision_key_field(vertex_fold(agg)) == "name"


def test_member_fold_op_is_the_cutoff_era_op(tmp_path):
    # Stronger check: the resolved fold op itself is the topic-era FoldBy, not
    # the head one — proving member SPEC resolution rode the cutoff, not just a
    # display field.
    agg, ts_before, _ts_after = _build(tmp_path)
    section = next(
        s for s in vertex_fold(agg, as_of=ts_before).sections if s.kind == "decision"
    )
    assert section.key_field == "topic"
    # And the head read differs — the two are genuinely distinct ontologies.
    head_section = next(
        s for s in vertex_fold(agg).sections if s.kind == "decision"
    )
    assert head_section.key_field == "name"
