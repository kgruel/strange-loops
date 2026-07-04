"""CLI-level tests for ``read --why`` — the provenance drill flag.

Covers the exact-address gate (errors with guidance), the end-to-end
attribution through the full dispatch (asserted via --json), the collect-fold
degrade, and register parity of the why lens.

Anchors: decision/design/provenance-why-build1-scope.
"""
from __future__ import annotations

import argparse
import json

import pytest
from painted import Zoom

from engine.builder import fold_by, fold_collect, vertex
from loops.lenses.provenance import why_view
from loops.main import cmd_emit, main
from loops.provenance import replay_attribution

from .parity import assert_register_parity


@pytest.fixture
def why_vertex(tmp_path):
    v = (
        vertex("why")
        .store("./w.db")
        .loop("decision", fold_by("topic"))
        .loop("cite", fold_collect())
    )
    vpath = tmp_path / "why.vertex"
    v.write(vpath)
    with open(vpath, "a") as f:
        f.write("\nobservers {\n  alice { }\n  bob { }\n}\n")
    return vpath


def _emit(vpath, kind, *, observer="alice", **payload):
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts, observer=observer, dry_run=False,
    )
    return cmd_emit(ns, vertex_path=vpath)


def _seed(vpath):
    # design/a folded over three emits by two observers: status open→review→open,
    # message set once (persists), label set then cleared.
    assert _emit(vpath, "decision", topic="design/a", message="body",
                 status="open", label="draft") == 0
    assert _emit(vpath, "decision", topic="design/a", status="review",
                 observer="bob") == 0
    assert _emit(vpath, "decision", topic="design/a", status="open", label="") == 0
    # a second key + a collect kind for the degrade path
    assert _emit(vpath, "decision", topic="design/b", message="beta") == 0
    assert _emit(vpath, "cite", context="c1") == 0
    assert _emit(vpath, "cite", context="c2", observer="bob") == 0


def _why_json(capsys, vpath, *argv):
    capsys.readouterr()
    rc = main(["read", str(vpath), *argv, "--why", "--json"])
    out = capsys.readouterr().out
    return rc, json.loads(out)


# --- Exact-address gate ----------------------------------------------------


class TestAddressGate:
    def test_no_address_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--why"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "exact kind/key address" in err

    def test_bare_kind_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--kind", "decision", "--why"])
        assert rc == 2
        assert "exact kind/key address" in capsys.readouterr().err

    def test_prefix_key_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--kind", "decision",
                   "--key", "design/", "--why"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "EXACT fold key" in err

    def test_comma_or_key_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--kind", "decision",
                   "--key", "design/a,design/b", "--why"])
        assert rc == 2
        assert "exact kind/key address" in capsys.readouterr().err


# --- End-to-end attribution via --json -------------------------------------


class TestAttributionJson:
    def test_upsert_attribution_shape(self, why_vertex, capsys):
        _seed(why_vertex)
        rc, d = _why_json(capsys, why_vertex, "decision/design/a")
        assert rc == 0
        assert d["mode"] == "upsert"
        assert d["kind"] == "decision" and d["key"] == "design/a"
        assert d["total_facts"] == 3
        fields = {f["field"]: f for f in d["fields"]}
        # status: open→review→open — current from fact 3, history newest-first.
        assert fields["status"]["value"] == "open"
        assert fields["status"]["setter"]["index"] == 3
        assert [p["value"] for p in fields["status"]["priors"]] == ["review", "open"]
        # message persisted from fact 1 (never re-supplied under merge).
        assert fields["message"]["value"] == "body"
        assert fields["message"]["setter"]["index"] == 1
        # label cleared to "" by fact 3's sentinel.
        assert fields["label"]["value"] == ""
        assert fields["label"]["setter"]["index"] == 3

    def test_observers_carried(self, why_vertex, capsys):
        _seed(why_vertex)
        _, d = _why_json(capsys, why_vertex, "decision/design/a")
        assert set(d["observers"]) == {"alice", "bob"}
        fields = {f["field"]: f for f in d["fields"]}
        assert fields["status"]["priors"][0]["setter"]["observer"] == "bob"  # review

    def test_collect_degrade(self, why_vertex, capsys):
        _seed(why_vertex)
        rc, d = _why_json(capsys, why_vertex, "cite/any")
        assert rc == 0
        assert d["mode"] == "collect"
        assert d["fields"] == []
        assert d["total_facts"] == 2
        assert [f["context"] for f in d["facts"]] == ["c1", "c2"]

    def test_missing_key_is_empty(self, why_vertex, capsys):
        _seed(why_vertex)
        rc, d = _why_json(capsys, why_vertex, "decision/design/nope")
        assert rc == 0
        assert d["mode"] == "empty"
        assert d["total_facts"] == 0


# --- Register parity of the why lens ---------------------------------------


def _prov_fixture():
    facts = [
        {"_ts": 1736850000.0, "_observer": "alice", "topic": "design/a",
         "message": "body", "status": "open"},
        {"_ts": 1736853600.0, "_observer": "bob", "topic": "design/a",
         "status": "review"},
        {"_ts": 1736942400.0, "_observer": "alice", "topic": "design/a",
         "status": "open"},
    ]
    from atoms.fold import Upsert

    return replay_attribution(
        Upsert(target="s", key="topic"), facts,
        kind="decision", key="design/a", key_field="topic",
    )


def test_why_register_parity():
    prov = _prov_fixture()
    # load-bearing: address, counts, both observers, the current field values.
    assert_register_parity(
        why_view, prov,
        load_bearing=["design/a", "decision", "3 facts", "alice", "bob",
                      "review", "body"],
        zoom=Zoom.DETAILED,
    )
