"""S4 read grammar — flags → Surface transforms, predicate classification.

Each transform flag is asserted via the ``--json`` Surface encoding (the agent's
primary read path): the structured ``rows``/``window`` prove the transform ran
and that plain and json would carry the same rows. The predicate grammar
(``field=value``, ``observer=``) is exercised across the three dispatch shapes —
the ``read`` verb, an intermixed flag, and the vertex-shorthand predicate guard
— to prove ``parse_intermixed_args`` + ``_classify_tokens`` classify it
regardless of position.

Anchors: decision/design/surface-base-order-is-fold-order;
plan:surface-build1 (S4).
"""
from __future__ import annotations

import argparse
import json

import pytest

from engine.builder import fold_by, vertex
from loops.cli import app
from loops.cli.operation import SurfaceSpec
from loops.cli.views.fold import (
    _classify_tokens,
    _resolve_kind_key,
    _resolve_key_grammar,
)
from loops.main import cmd_emit, main


# --- Fixtures + helpers ----------------------------------------------------


@pytest.fixture
def grammar_vertex(tmp_path):
    """A two-kind by-fold vertex with a declared observers block (so the
    ``observer=`` filter test is self-contained, not dependent on the global
    observer registry)."""
    v = (
        vertex("grammar")
        .store("./g.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
    )
    vpath = tmp_path / "grammar.vertex"
    v.write(vpath)
    # Append an observers block — the builder doesn't model it, the parser does.
    with open(vpath, "a") as f:
        f.write("\nobservers {\n  kyle { }\n  alcove { }\n}\n")
    return tmp_path, vpath


def _emit(vpath, kind, *, observer="kyle", **payload):
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts, observer=observer, dry_run=False,
    )
    return cmd_emit(ns, vertex_path=vpath)


def _seed(vpath):
    assert _emit(vpath, "decision", topic="design/a", message="alpha", status="open") == 0
    assert _emit(vpath, "decision", topic="design/b", message="beta", status="resolved") == 0
    assert _emit(vpath, "decision", topic="arch/c", message="gamma", status="open") == 0
    assert _emit(vpath, "thread", name="t1", message="one", status="open", observer="alcove") == 0
    assert _emit(vpath, "thread", name="t2", message="two", status="resolved") == 0


def _json_read(capsys, *argv):
    """Run ``read <argv> --json`` and parse the Surface dict from stdout.

    Clears any prior captured output (seed receipts) first so only the read's
    JSON is parsed.
    """
    capsys.readouterr()
    rc = main(["read", *argv, "--json"])
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _kinds(surface):
    return [r["kind"] for r in surface["rows"]]


# --- Transform flags via the --json Surface --------------------------------


class TestTransformFlags:
    def test_baseline_full_surface(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath))
        assert rc == 0
        # 3 decisions + 2 threads, faithful fold order, nothing windowed.
        assert len(s["rows"]) == 5
        assert s["window"]["total"] == 5
        assert s["window"]["limited_by"] is None

    def test_limit_takes_salience_head(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "--limit", "2")
        assert rc == 0
        assert len(s["rows"]) == 2
        assert s["window"]["limited_by"] == "limit"
        # salience-desc order under --limit
        sal = [r["salience"] for r in s["rows"]]
        assert sal == sorted(sal, reverse=True)

    def test_last_takes_newest_by_ts(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "--last", "2")
        assert rc == 0
        assert len(s["rows"]) == 2
        assert s["window"]["limited_by"] == "last"
        ts = [r["ts"] for r in s["rows"]]
        assert ts == sorted(ts, reverse=True)

    def test_fields_projects_payload(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "--fields", "status")
        assert rc == 0
        assert s["window"]["fields"] == ["status"]
        for r in s["rows"]:
            assert set(r["payload"]).issubset({"status"})

    def test_count_total(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "--count")
        assert rc == 0
        assert len(s["rows"]) == 1
        assert s["rows"][0]["kind"] == "count"
        assert s["rows"][0]["payload"]["count"] == 5

    def test_count_by_kind(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "--count", "--by", "kind")
        assert rc == 0
        groups = {r["payload"]["kind"]: r["payload"]["count"] for r in s["rows"]}
        assert groups == {"decision": 3, "thread": 2}

    def test_count_then_budget_takes_top_groups_by_count(self, grammar_vertex, capsys):
        # --count --by kind --limit 1 → the SINGLE biggest kind by count
        # (decision=3 > thread=2), proving count runs before budget so the
        # count-row salience (=count) drives the limit.
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "--count", "--by", "kind", "--limit", "1")
        assert rc == 0
        assert len(s["rows"]) == 1
        assert s["rows"][0]["payload"] == {"kind": "decision", "count": 3}

    def test_full_forces_whole_granularity(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "--full")
        assert rc == 0
        assert {r["granularity"] for r in s["rows"]} == {"whole"}
        assert s["window"]["granularity"] == "whole"

    def test_comma_or_key_filters_union(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        # design/a (decision) OR t1 (thread) — comma-OR across kinds.
        rc, s = _json_read(capsys, str(vpath), "--key", "design/a,t1")
        assert rc == 0
        keys = sorted(r["key"] for r in s["rows"])
        assert keys == ["design/a", "t1"]

    def test_single_key_marks_complete_key_whole(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        # Exact single key → that row is whole (complete-key whole-detection),
        # and fetch filtered to it.
        rc, s = _json_read(capsys, str(vpath), "--kind", "decision", "--key", "design/a")
        assert rc == 0
        assert len(s["rows"]) == 1
        assert s["rows"][0]["key"] == "design/a"
        assert s["rows"][0]["granularity"] == "whole"


# --- Predicate grammar across the three dispatch shapes --------------------


class TestPredicateAcrossForms:
    def test_field_value_form_read_verb(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        rc, s = _json_read(capsys, str(vpath), "status=open")
        assert rc == 0
        assert {r["payload"].get("status") for r in s["rows"]} == {"open"}
        # design/a + arch/c (decisions) + t1 (thread) all carry status=open.
        assert len(s["rows"]) == 3

    def test_field_value_form_intermixed_with_flag(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        # predicate intermixed AFTER a value-taking flag — the parse_intermixed
        # win (the brittle nargs-pair shape would mis-bind this).
        rc, s = _json_read(capsys, str(vpath), "--kind", "decision", "status=open")
        assert rc == 0
        assert _kinds(s) == ["decision", "decision"]
        assert {r["payload"]["status"] for r in s["rows"]} == {"open"}

    def test_field_value_form_vertex_shorthand_guard(self, grammar_vertex):
        _, vpath = grammar_vertex
        _seed(vpath)
        # The vertex-shorthand predicate guard: `_vertex_first` must route a
        # leading `status=open` to the implicit read, not error as unknown op.
        rc = app._vertex_first("grammar", vpath, ["status=open", "--plain"])
        assert rc == 0

    def test_observer_filter_is_row_filter(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        # observer=alcove → only the one thread emitted by alcove.
        rc, s = _json_read(capsys, str(vpath), "observer=alcove")
        assert rc == 0
        assert len(s["rows"]) == 1
        assert s["rows"][0]["observer"] == "alcove"
        assert s["rows"][0]["key"] == "t1"

    def test_observer_filter_distinct_from_identity_peel(self, grammar_vertex, capsys):
        _, vpath = grammar_vertex
        _seed(vpath)
        # Two independent axes:
        #   --observer NAME (dashed) = identity peel, consumed in app.py — it
        #     SCOPES the fetch to NAME's facts.
        #   observer=NAME (bareword)  = a Surface ROW filter applied after fetch.
        # They never conflate: the bareword is NOT swallowed by the peel.
        #
        # (1) Same observer on both axes → the row filter passes through the
        # already-scoped fetch and keeps kyle's 4 rows.
        capsys.readouterr()
        rc = main(["read", str(vpath), "--observer", "kyle", "observer=kyle", "--json"])
        s = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(s["rows"]) == 4
        assert {r["observer"] for r in s["rows"]} == {"kyle"}

        # (2) Different values on each axis → empty intersection (the peel scoped
        # the fetch to kyle; the alcove row filter then matches none). An empty
        # result here IS the proof the two axes apply independently.
        capsys.readouterr()
        rc = main(["read", str(vpath), "--observer", "kyle", "observer=alcove", "--json"])
        s = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert s["rows"] == []


# --- Unit: token classification + key grammar ------------------------------


class TestClassifyTokens:
    def test_observer_predicate_routes_to_observer_slot(self):
        vname, entity, where, observer = _classify_tokens(["observer=alice"], True)
        assert observer == "alice"
        assert where == {}  # NOT a where predicate

    def test_field_value_routes_to_where(self):
        vname, entity, where, observer = _classify_tokens(["status=open"], True)
        assert where == {"status": ("open",)}
        assert observer is None

    def test_comma_or_in_where_value(self):
        _, _, where, _ = _classify_tokens(["status=open,resolved"], True)
        assert where == {"status": ("open", "resolved")}

    def test_positional_vertex_then_entity(self):
        vname, entity, where, observer = _classify_tokens(
            ["myvertex", "decision/foo"], False,
        )
        assert vname == "myvertex"
        assert entity == "decision/foo"

    def test_slash_token_is_entity_when_vertex_resolved(self):
        vname, entity, where, observer = _classify_tokens(["decision/foo"], True)
        assert vname is None
        assert entity == "decision/foo"

    def test_predicate_and_positional_intermix(self):
        vname, entity, where, observer = _classify_tokens(
            ["decision/foo", "status=open"], True,
        )
        assert entity == "decision/foo"
        assert where == {"status": ("open",)}


class TestKeyGrammar:
    def test_entity_split_sets_kind_and_key(self):
        kind, key = _resolve_kind_key("decision/design/a", None, None)
        assert kind == "decision"
        assert key == "design/a"

    def test_bare_entity_ignored(self):
        # A bare entity (no slash) does not become a kind — matches legacy.
        kind, key = _resolve_kind_key("decision", None, None)
        assert kind is None
        assert key is None

    def test_explicit_kind_wins_over_entity(self):
        kind, key = _resolve_kind_key("decision/foo", "thread", None)
        assert kind == "thread"
        assert key is None

    def test_single_key_is_fetch_and_queried(self):
        fetch_key, queried_key, key_or = _resolve_key_grammar("design/a")
        assert fetch_key == "design/a"
        assert queried_key == "design/a"
        assert key_or == ()

    def test_comma_key_is_key_or_only(self):
        fetch_key, queried_key, key_or = _resolve_key_grammar("a,b,c")
        assert fetch_key is None
        assert queried_key is None
        assert key_or == ("a", "b", "c")

    def test_none_key_all_empty(self):
        assert _resolve_key_grammar(None) == (None, None, ())


class TestPredicateGuard:
    def test_is_predicate_token(self):
        assert app._is_predicate_token("status=open")
        assert app._is_predicate_token("observer=alice")

    def test_non_predicate_tokens(self):
        assert not app._is_predicate_token("decision")
        assert not app._is_predicate_token("--kind")
        assert not app._is_predicate_token("./foo.vertex")
        assert not app._is_predicate_token("decision/foo")


# --- SurfaceSpec is carried, not leaked into render_context ----------------


def test_surface_spec_default_is_empty():
    """A bare SurfaceSpec is inert — no transform applies, no granularity flip."""
    spec = SurfaceSpec()
    assert spec.queried_key is None
    assert spec.full is False
    assert spec.key_or == ()
    assert spec.where == ()
    assert spec.do_count is False
