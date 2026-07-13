"""Ontology-as-of — the read path rewinds under a historical cursor (SPEC §9.3 S5).

The exit criterion is HONEST REWIND: a read at a cursor before a declaration edit
resolves under the OLD ontology; a head read under the new. The resolver's ``as_of``
cutoff is proven in ``test_declaration_resolver.py``; this file proves the READ
SURFACES thread it correctly and with the equal-cursors default (§9.3):

- ``vertex_facts`` / ``vertex_ticks`` / ``vertex_search`` grow an ``as_of`` param;
  ``as_of=None`` (head) is byte-identical to the pre-S5 behavior, and — because
  nothing has a future ``ts`` — identical to ``as_of=now``. That equivalence is
  why threading equal-cursors is a no-op against current behavior.
- ``vertex_tick_fold`` interprets its stored snapshot under ``as_of = tick.ts``
  (never re-folds) — a tick that fired before a fold-key rename types under the
  OLD key (Q5).

The load-bearing rewind case is a fold-key CHANGE: an S4-shaped
``_decl.kind-defined`` overlay that moves ``decision``'s fold key from ``topic``
to ``name``. Before the edit the key is ``topic``; at head it is ``name``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from atoms import Fact
from engine import vertex_facts, vertex_search, vertex_tick_fold, vertex_ticks
from engine.declaration import load_declaration
from engine.sqlite_store import SqliteStore
from engine.tick import Tick
from lang import parse_vertex_file
from lang.ast import FoldBy
from lang.document import DECL_GENESIS, DECL_KIND_DEFINED, genesis_payload

# ---------------------------------------------------------------------------
# Scaffolding (mirrors test_declaration_resolver — decision folds by topic)
# ---------------------------------------------------------------------------

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


def _absorb(vpath: Path, store: Path) -> str:
    ast = parse_vertex_file(vpath)
    docs = genesis_payload(ast)["documents"]
    s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    receipt = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return receipt["lineage"]


def _genesis_ts(store: Path) -> float:
    conn = sqlite3.connect(str(store))
    ts = conn.execute("SELECT ts FROM facts WHERE kind = ?", (DECL_GENESIS,)).fetchone()[0]
    conn.close()
    return ts


def _emit(store: Path, kind: str, ts: float, **payload) -> None:
    """Append a plain fact at a controlled ``ts`` (bypasses live-now stamping)."""
    conn = sqlite3.connect(str(store))
    from engine.sqlite_store import gen_id

    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (gen_id(), kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _rekey_decision(store: Path, lineage: str, ts: float) -> None:
    """S4-shaped overlay: move ``decision``'s fold key from ``topic`` to ``name``."""
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        ("rekey-decision", DECL_KIND_DEFINED, ts, "kyle", "", json.dumps({
            "lineage": lineage,
            "subject": "decision",
            "payload": {"order": 0, "search": ["message"], "folds": [
                {"target": "items", "op": {"op": "by", "key_field": "name"}}
            ]},
        })),
    )
    conn.commit()
    conn.close()


def _decision_key_field(ast) -> str:
    op = ast.loops["decision"].folds[0].op
    assert isinstance(op, FoldBy)
    return op.key_field


# ---------------------------------------------------------------------------
# Rewind honesty — the exit criterion, at the resolver seam
# ---------------------------------------------------------------------------


class TestFoldKeyRewind:
    def test_resolver_fold_key_rewinds_across_the_edit(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        gts = _genesis_ts(store)
        _rekey_decision(store, lineage, ts=gts + 100)

        # Before the edit → OLD key (topic). After → NEW key (name). Head → NEW.
        assert _decision_key_field(load_declaration(vpath, as_of=gts + 50)) == "topic"
        assert _decision_key_field(load_declaration(vpath, as_of=gts + 200)) == "name"
        assert _decision_key_field(load_declaration(vpath)) == "name"

    def test_cursor_between_two_edits_picks_the_earlier(self, tmp_path):
        # Two edits of the SAME subject: topic→name (t1), name→title (t2). A cursor
        # in [t1, t2) sees the FIRST edit only. Directly the "picks the earlier"
        # requirement, on the read seam.
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        gts = _genesis_ts(store)
        _rekey_decision(store, lineage, ts=gts + 100)  # → name
        conn = sqlite3.connect(str(store))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            ("rekey-2", DECL_KIND_DEFINED, gts + 200, "kyle", "", json.dumps({
                "lineage": lineage, "subject": "decision",
                "payload": {"order": 0, "folds": [
                    {"target": "items", "op": {"op": "by", "key_field": "title"}}]},
            })),
        )
        conn.commit()
        conn.close()

        assert _decision_key_field(load_declaration(vpath, as_of=gts + 50)) == "topic"
        assert _decision_key_field(load_declaration(vpath, as_of=gts + 150)) == "name"
        assert _decision_key_field(load_declaration(vpath, as_of=gts + 250)) == "title"

    def test_same_ts_edit_is_in_force_at_its_own_ts(self, tmp_path):
        # Codex #1 / the walkthrough transient. At an EXACT shared float ts the
        # cutoff is inclusive (`_ts <= as_of`), so a declaration edit is in force
        # AT its own ts — a fact sharing that ts (equal-cursors as_of=ts) folds
        # under the NEW ontology. The tie-break is pure ts (not rowid/append
        # order), so it is deterministic across runs. One epsilon earlier → OLD.
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        gts = _genesis_ts(store)
        edit_ts = gts + 100
        _rekey_decision(store, lineage, ts=edit_ts)
        for _ in range(5):  # determinism: same answer every evaluation
            assert _decision_key_field(load_declaration(vpath, as_of=edit_ts)) == "name"
        assert _decision_key_field(load_declaration(vpath, as_of=edit_ts - 0.001)) == "topic"

    def test_genesis_never_excluded_below_its_own_ts(self, tmp_path):
        # A cursor earlier than genesis falls back to the file era — the genesis
        # documents are the floor, never Latest-resolved away.
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        gts = _genesis_ts(store)
        pre = load_declaration(vpath, as_of=gts - 100)
        assert set(pre.loops) == {"decision", "thread"}


# ---------------------------------------------------------------------------
# Equal-cursors default — as_of=None (head) ≡ as_of=now, on every read surface
# ---------------------------------------------------------------------------


class TestHeadEquivalence:
    def test_vertex_facts_head_equals_now(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        gts = _genesis_ts(store)
        _emit(store, "decision", gts + 1, topic="a", message="alpha")
        _emit(store, "decision", gts + 2, topic="b", message="beta")
        now = gts + 1000

        head = vertex_facts(vpath, 0.0, now, as_of=None)
        at_now = vertex_facts(vpath, 0.0, now, as_of=now)
        assert [f["id"] for f in head] == [f["id"] for f in at_now]
        assert len(head) == 2  # user facts only; genesis excluded (§9.4)

    def test_vertex_facts_reserved_exclusion_holds_under_as_of(self, tmp_path):
        # The _decl.* ambient exclusion is resolved at the as_of ontology too.
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        gts = _genesis_ts(store)
        _emit(store, "decision", gts + 1, topic="a", message="alpha")
        facts = vertex_facts(vpath, 0.0, gts + 1000, as_of=gts + 1000)
        assert all(not f["kind"].startswith("_decl.") for f in facts)

    def test_vertex_search_head_equals_now(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        gts = _genesis_ts(store)
        _emit(store, "decision", gts + 1, topic="a", message="alpha uniquetoken")
        now = gts + 1000
        head = vertex_search(vpath, "uniquetoken", as_of=None)
        at_now = vertex_search(vpath, "uniquetoken", until=now, as_of=now)
        assert [f["id"] for f in head] == [f["id"] for f in at_now]
        assert len(head) == 1

    def test_vertex_ticks_head_equals_now(self, tmp_path):
        # No ticks stored → both return empty; the point is the as_of param does
        # not perturb the tick-window path.
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        gts = _genesis_ts(store)
        assert vertex_ticks(vpath, 0.0, gts + 1000, as_of=None) == \
            vertex_ticks(vpath, 0.0, gts + 1000, as_of=gts + 1000)


# ---------------------------------------------------------------------------
# vertex_tick_fold — interpret the snapshot under as_of=tick.ts (Q5)
# ---------------------------------------------------------------------------


class TestTickFoldInterpretation:
    def _tick_at(self, ts: float) -> Tick:
        return Tick(
            name="t",
            ts=datetime.fromtimestamp(ts, tz=UTC),
            payload={"decision": {"items": {"a": {"topic": "a", "name": "a", "message": "x"}}}},
        )

    def test_pre_edit_tick_types_under_old_key(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        gts = _genesis_ts(store)
        _rekey_decision(store, lineage, ts=gts + 100)

        pre = vertex_tick_fold(vpath, self._tick_at(gts + 50))
        post = vertex_tick_fold(vpath, self._tick_at(gts + 200))

        pre_decision = next(s for s in pre.sections if s.kind == "decision")
        post_decision = next(s for s in post.sections if s.kind == "decision")
        assert pre_decision.key_field == "topic"   # old ontology (as_of=tick.ts)
        assert post_decision.key_field == "name"    # new ontology
