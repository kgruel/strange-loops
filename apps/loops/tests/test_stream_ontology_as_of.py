"""fetch_stream rewinds its ontology under --as-of (SPEC §9.3 S5, equal-cursors).

The app-layer half of honest rewind. ``fetch_stream``'s per-kind ``fold_meta``
(the key field each row's key is extracted through) resolves through the
store-backed seam at the ontology-as-of cursor, so a rewound read renders under
the OLD fold key while head renders under the new. And the equal-cursors default
holds: ``as_of=None`` (head) is identical to an anchor at ``now`` — nothing has a
future ``ts``, so threading the cursor is a no-op against current behavior.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from atoms import Fact
from engine.sqlite_store import SqliteStore, gen_id
from lang import parse_vertex_file
from lang.document import DECL_KIND_DEFINED, genesis_payload
from loops.commands.fetch import fetch_stream, fetch_tick_facts


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }}
             search "message" }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _scaffold_absorb(tmp_path: Path) -> tuple[Path, Path, str]:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_KDL.format(store=store))
    docs = genesis_payload(parse_vertex_file(vpath))["documents"]
    s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    lineage = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)["lineage"]
    s.close()
    return vpath, store, lineage


def _genesis_ts(store: Path) -> float:
    conn = sqlite3.connect(str(store))
    from lang.document import DECL_GENESIS

    ts = conn.execute("SELECT ts FROM facts WHERE kind = ?", (DECL_GENESIS,)).fetchone()[0]
    conn.close()
    return ts


def _row(store: Path, kind: str, ts: float, row_id: str, payload: dict) -> None:
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (row_id, kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _rekey_decision(store: Path, lineage: str, ts: float) -> None:
    _row(store, DECL_KIND_DEFINED, ts, "rekey-decision", {
        "lineage": lineage, "subject": "decision",
        "payload": {"order": 0, "search": ["message"], "folds": [
            {"target": "items", "op": {"op": "by", "key_field": "name"}}]},
    })


def _backdate_genesis(store: Path, ts: float) -> None:
    """Move the genesis earlier so a whole pre-edit timeline fits before ``now``.

    ``absorb_genesis`` stamps the genesis at wall-clock now; a stored tick is
    only reachable through ``_load_ticks_newest``'s ``(now-30d, now]`` window, so
    the genesis → facts → tick → edit sequence must all sit in the past.
    Resolution keys off the genesis *ts* and *payload* only (pins are
    attestation), so backdating the ts is faithful.
    """
    conn = sqlite3.connect(str(store))
    conn.execute("UPDATE facts SET ts = ? WHERE kind = ?", (ts, "_decl.genesis"))
    conn.commit()
    conn.close()


def _append_tick(store: Path, *, name: str, since: float, ts: float, payload: dict) -> None:
    """Hand-append a stored tick (unsigned, unchained → envelope chained=False)."""
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (gen_id(), name, ts, since, "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def test_fold_meta_rewinds_across_the_edit(tmp_path):
    vpath, store, lineage = _scaffold_absorb(tmp_path)
    gts = _genesis_ts(store)
    _rekey_decision(store, lineage, ts=gts + 100)

    # Rewound before the edit → OLD fold key; head → NEW. fold_meta comes from
    # load_declaration(as_of=cursor), independent of which facts land in-window.
    rewound = fetch_stream(vpath, as_of=str(gts + 50))
    head = fetch_stream(vpath)
    assert rewound["fold_meta"]["decision"]["key_field"] == "topic"
    assert head["fold_meta"]["decision"]["key_field"] == "name"


def test_as_of_head_equivalence(tmp_path):
    # Equal-cursors no-op: as_of=None (head) ≡ an explicit anchor at now. A past
    # fact lands in both windows; the results match byte-for-byte.
    vpath, store, _lineage = _scaffold_absorb(tmp_path)
    gts = _genesis_ts(store)
    _row(store, "decision", gts - 10, gen_id(), {"topic": "a", "message": "alpha"})

    head = fetch_stream(vpath)
    at_now = fetch_stream(vpath, as_of=str(gts + 5))
    assert [f["id"] for f in head["facts"]] == [f["id"] for f in at_now["facts"]]
    assert head["fold_meta"] == at_now["fold_meta"]


def test_same_ts_fact_folds_under_new_ontology(tmp_path):
    # Codex #1: a fact and a declaration edit sharing an EXACT float ts. The
    # equal-cursors read at that ts includes the fact (facts_between `ts <=
    # until`) AND the edit (resolver `_ts <= as_of`), so the fact renders under
    # the NEW fold key — the edit is in force at its own ts. Deterministic across
    # runs (pure ts tie-break, not append/rowid order); the walkthrough transient
    # was this boundary read under a jittered anchor.
    vpath, store, lineage = _scaffold_absorb(tmp_path)
    gts = _genesis_ts(store)
    edit_ts = gts + 100
    _row(store, "decision", edit_ts, gen_id(), {"topic": "a", "name": "n-a", "message": "m"})
    _rekey_decision(store, lineage, ts=edit_ts)  # SAME ts as the fact
    for _ in range(5):
        out = fetch_stream(vpath, as_of=str(edit_ts))
        assert out["fold_meta"]["decision"]["key_field"] == "name"  # new ontology
        assert len(out["facts"]) == 1  # the same-ts fact is in-window (_decl excluded)


def test_key_drilldown_uses_as_of_fold_key(tmp_path):
    # kind/key drill-down extracts the key through the AS-OF fold key. Pre-edit,
    # decision folds by topic → a topic-prefix drill matches.
    vpath, store, lineage = _scaffold_absorb(tmp_path)
    gts = _genesis_ts(store)
    _row(store, "decision", gts - 10, gen_id(), {"topic": "design/x", "name": "n1", "message": "m"})
    _rekey_decision(store, lineage, ts=gts + 100)

    rewound = fetch_stream(vpath, kind="decision/design/", as_of=str(gts + 50))
    assert len(rewound["facts"]) == 1  # matched on the old (topic) key


def test_tick_drill_renders_under_pre_edit_ontology(tmp_path):
    """Drilling a pre-edit tick renders its facts under the OLD ontology (Codex #2).

    The regression this pins: ``fetch_tick_facts`` passes ``as_of=tick.ts`` to
    both ``vertex_facts`` and ``_get_fold_meta``. If either drops the cursor, the
    drill falls back to head and ``fold_meta`` reports the NEW fold key — this
    test then FAILS. The whole timeline is backdated into the past so the tick is
    reachable through the ``(now-30d, now]`` listing window.

    Timeline: genesis(T0) → fact(T0+10) → tick[since T0+5, ts T0+50] →
    fold-key edit topic→name(T0+1000). Drilling the tick (as_of=T0+50) excludes
    the later edit → OLD key ``topic``; head resolves the edit → NEW key ``name``.
    """
    vpath, store, lineage = _scaffold_absorb(tmp_path)
    t0 = _genesis_ts(store) - 5000.0
    _backdate_genesis(store, t0)
    _row(store, "decision", t0 + 10, gen_id(), {"topic": "a", "name": "n-a", "message": "m"})
    _append_tick(
        store, name="decision", since=t0 + 5, ts=t0 + 50,
        payload={"decision": {"items": {"a": {"topic": "a", "name": "n-a"}}}},
    )
    _rekey_decision(store, lineage, ts=t0 + 1000)  # edit AFTER the tick

    drill = fetch_tick_facts(vpath, 0)
    # OLD ontology at the tick boundary — the load-bearing assertion.
    assert drill["fold_meta"]["decision"]["key_field"] == "topic"
    assert len(drill["facts"]) == 1  # the pre-edit fact was drilled in-window

    # Sanity: the store genuinely changed — a head read resolves the NEW key.
    assert fetch_stream(vpath)["fold_meta"]["decision"]["key_field"] == "name"
