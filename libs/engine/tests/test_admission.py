"""Declared admission policy at the engine boundary (libs-handoff S3).

Two coupled contracts:

* Observer-grant resolution (LIBS_CHANGES P1): ``grant_for_observer`` +
  ``VertexProgram.receive_as`` / ``VertexHandle.receive_as`` resolve the
  declaration's ``observers { grant { potential } }`` automatically. Five
  cases — no observers block, unknown observer, declared without grant,
  declared with potential, aggregate — each proven both ways: the enforced
  path rejects/admits per declaration, and the explicit bypass (the raw
  ``receive`` entry) admits.
* Strict enforcement (decision:design/strict-enforcement-at-engine-receive):
  ``strict true`` makes ``Vertex.receive_receipt`` refuse undeclared kinds
  with typed ``UndeclaredKind`` BEFORE storage; bypass only via the explicit
  ``admit_undeclared=True``. Non-strict behavior is preserved verbatim —
  undeclared facts store, read raw, and fold once the kind is declared.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact

from engine.admission import (
    AdmissionError,
    AggregateAdmissionUnsupported,
    UndeclaredKind,
    UnknownObserver,
    grant_for_observer,
)
from engine.peer import Grant
from engine.program import load_vertex_program
from lang import parse_vertex


def _fact(kind: str, observer: str = "kyle", **payload) -> Fact:
    return Fact.of(kind, observer, **payload)


def _write_vertex(tmp_path: Path, body: str, name: str = "t") -> Path:
    vpath = tmp_path / f"{name}.vertex"
    store = tmp_path / f"{name}.db"
    vpath.write_text(body.format(store=store))
    return vpath


def _stored_kinds(store: Path) -> list[str]:
    conn = sqlite3.connect(str(store))
    try:
        return [r[0] for r in conn.execute("SELECT kind FROM facts ORDER BY rowid")]
    finally:
        conn.close()


_DECISION_LOOP = 'loops {{\n  decision {{ fold {{ items "by" "topic" }} }}\n}}\n'


# ---------------------------------------------------------------------------
# grant_for_observer — the five contract cases, unit level
# ---------------------------------------------------------------------------


class TestGrantForObserver:
    def test_no_observers_block_is_unrestricted(self):
        ast = parse_vertex('name "t"\nloops { decision { fold { items "by" "topic" } } }')
        assert grant_for_observer(ast, "anyone") is None

    def test_unknown_observer_raises_typed(self):
        ast = parse_vertex(
            'name "t"\nobservers { kyle { } }\n'
            'loops { decision { fold { items "by" "topic" } } }'
        )
        with pytest.raises(UnknownObserver) as ei:
            grant_for_observer(ast, "mallory")
        assert ei.value.observer == "mallory"
        assert isinstance(ei.value, AdmissionError)

    def test_declared_observer_without_grant_is_unrestricted(self):
        ast = parse_vertex(
            'name "t"\nobservers { kyle { } }\n'
            'loops { decision { fold { items "by" "topic" } } }'
        )
        assert grant_for_observer(ast, "kyle") is None

    def test_declared_observer_with_potential_yields_grant(self):
        ast = parse_vertex(
            'name "t"\nobservers { bot { grant { potential "log" "change" } } }\n'
            'loops { log { fold { items "collect" 5 } } }'
        )
        g = grant_for_observer(ast, "bot")
        assert isinstance(g, Grant)
        assert g.potential == frozenset({"log", "change"})
        assert g.horizon is None

    def test_aggregate_vertex_refused(self, tmp_path):
        ast = parse_vertex('name "agg"\ndiscover "*.vertex"')
        with pytest.raises(AggregateAdmissionUnsupported):
            grant_for_observer(ast, "kyle")


# ---------------------------------------------------------------------------
# VertexProgram.receive_as — enforced path vs explicit bypass, per case
# ---------------------------------------------------------------------------


class TestProgramReceiveAs:
    def test_no_observers_block_admits(self, tmp_path):
        vpath = _write_vertex(tmp_path, 'name "t"\nstore "{store}"\n' + _DECISION_LOOP)
        with load_vertex_program(vpath) as p:
            r = p.receive_as(_fact("decision", topic="x"))
            assert r.stored and r.fact_id

    def test_unknown_observer_enforced_rejects_bypass_admits(self, tmp_path):
        vpath = _write_vertex(
            tmp_path,
            'name "t"\nstore "{store}"\nobservers {{ kyle {{ }} }}\n' + _DECISION_LOOP,
        )
        fact = _fact("decision", observer="mallory", topic="x")
        with load_vertex_program(vpath) as p:
            with pytest.raises(UnknownObserver):
                p.receive_as(fact)
            assert _stored_kinds(tmp_path / "t.db") == []
            # Explicit bypass: the raw receive entry point (caller grant).
            r = p.receive(fact)
            assert r.stored
        assert _stored_kinds(tmp_path / "t.db") == ["decision"]

    def test_declared_observer_without_grant_admits_any_declared_kind(self, tmp_path):
        vpath = _write_vertex(
            tmp_path,
            'name "t"\nstore "{store}"\nobservers {{ kyle {{ }} }}\n' + _DECISION_LOOP,
        )
        with load_vertex_program(vpath) as p:
            assert p.receive_as(_fact("decision", topic="x")).stored
            # and both entry points agree for this case
            assert p.receive(_fact("decision", topic="y")).stored

    def test_declared_potential_gates_enforced_path_bypass_admits(self, tmp_path):
        vpath = _write_vertex(
            tmp_path,
            'name "t"\nstore "{store}"\n'
            'observers {{ bot {{ grant {{ potential "log" }} }} }}\n'
            'loops {{\n'
            '  log {{ fold {{ items "collect" 5 }} }}\n'
            '  decision {{ fold {{ items "by" "topic" }} }}\n'
            '}}\n',
        )
        with load_vertex_program(vpath) as p:
            # in-potential admits
            assert p.receive_as(_fact("log", observer="bot", message="ok")).stored
            # out-of-potential rejects (grant gate: Receipt stored=False)
            r = p.receive_as(_fact("decision", observer="bot", topic="x"))
            assert not r.stored and r.fact_id is None
            # explicit bypass: raw receive with no grant admits the same fact
            assert p.receive(_fact("decision", observer="bot", topic="x")).stored
        assert _stored_kinds(tmp_path / "t.db") == ["log", "decision"]

    def test_aggregate_program_receive_as_refused(self, tmp_path):
        member = tmp_path / "m.vertex"
        member.write_text(
            'name "m"\nloops { decision { fold { items "by" "topic" } } }'
        )
        agg = tmp_path / "agg.vertex"
        agg.write_text('name "agg"\ndiscover "m.vertex"')
        with load_vertex_program(agg) as p:
            with pytest.raises(AggregateAdmissionUnsupported):
                p.receive_as(_fact("decision", topic="x"))

    def test_program_without_declaration_refuses_receive_as(self, tmp_path):
        from engine.program import VertexProgram
        from engine.vertex import Vertex

        p = VertexProgram(Vertex("bare"), [], [])
        with pytest.raises(AdmissionError):
            p.receive_as(_fact("decision", topic="x"))


# ---------------------------------------------------------------------------
# Strict enforcement at engine receive
# ---------------------------------------------------------------------------


_STRICT_VERTEX = 'name "t"\nstore "{store}"\nstrict true\n' + _DECISION_LOOP
_LOOSE_VERTEX = 'name "t"\nstore "{store}"\n' + _DECISION_LOOP


class TestStrictEnforcement:
    def test_undeclared_kind_typed_rejection_before_storage(self, tmp_path):
        vpath = _write_vertex(tmp_path, _STRICT_VERTEX)
        with load_vertex_program(vpath) as p:
            with pytest.raises(UndeclaredKind) as ei:
                p.receive(_fact("mystery", note="hi"))
            assert ei.value.kind == "mystery"
        assert _stored_kinds(tmp_path / "t.db") == []  # nothing stored

    def test_declared_kind_passes_under_strict(self, tmp_path):
        vpath = _write_vertex(tmp_path, _STRICT_VERTEX)
        with load_vertex_program(vpath) as p:
            assert p.receive(_fact("decision", topic="x")).stored
            # cite is implicitly registered on every vertex — still admitted
            assert p.receive(_fact("cite", items="decision:x")).stored

    def test_explicit_bypass_admits_undeclared(self, tmp_path):
        vpath = _write_vertex(tmp_path, _STRICT_VERTEX)
        with load_vertex_program(vpath) as p:
            r = p.receive(_fact("mystery", note="hi"), admit_undeclared=True)
            assert r.stored
        assert _stored_kinds(tmp_path / "t.db") == ["mystery"]

    def test_receive_as_enforces_strict_too(self, tmp_path):
        vpath = _write_vertex(tmp_path, _STRICT_VERTEX)
        with load_vertex_program(vpath) as p:
            with pytest.raises(UndeclaredKind):
                p.receive_as(_fact("mystery", note="hi"))
            assert p.receive_as(
                _fact("mystery", note="hi"), admit_undeclared=True
            ).stored

    def test_observer_state_kind_not_exempt_under_strict(self, tmp_path):
        # focus.* passes the ownership gate but is still an undeclared kind:
        # strict applies — undeclared is undeclared (deliberate choice).
        vpath = _write_vertex(tmp_path, _STRICT_VERTEX)
        with load_vertex_program(vpath) as p:
            with pytest.raises(UndeclaredKind):
                p.receive(_fact("focus.kyle", observer="kyle", target="x"))

    def test_strict_store_with_historical_undeclared_fact_still_loads(self, tmp_path):
        vpath = _write_vertex(tmp_path, _STRICT_VERTEX)
        with load_vertex_program(vpath) as p:
            p.receive(_fact("mystery", note="hi"), admit_undeclared=True)
        # replay bypasses receive — the historical undeclared row must not wedge
        with load_vertex_program(vpath) as p:
            assert p.receive(_fact("decision", topic="x")).stored

    def test_sync_lifecycle_facts_bypass_strict(self, tmp_path):
        """Executor's own `_sync` lifecycle facts are engine-internal, not
        client ingress — sync on a strict vertex must not raise on them."""
        vpath = _write_vertex(tmp_path, _STRICT_VERTEX)
        with load_vertex_program(vpath) as p:
            result = p.sync()  # no sources — still emits the `_sync` fact
            assert result.errors == []
        assert _stored_kinds(tmp_path / "t.db") == ["_sync"]

    def test_non_strict_preservation_verbatim(self, tmp_path):
        """Undeclared facts on a non-strict vertex: stored, raw-readable,
        and folded once the kind is later declared."""
        vpath = _write_vertex(tmp_path, _LOOSE_VERTEX)
        store = tmp_path / "t.db"
        with load_vertex_program(vpath) as p:
            r = p.receive(_fact("mystery", note="hi"))
            assert r.stored and r.fact_id  # stored despite being undeclared
            assert r.tick is None
        # raw-readable
        conn = sqlite3.connect(str(store))
        rows = conn.execute(
            "SELECT kind, payload FROM facts WHERE kind='mystery'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert json.loads(rows[0][1])["note"] == "hi"
        # declare the kind later → the historical fact folds on replay
        vpath.write_text(
            f'name "t"\nstore "{store}"\n'
            'loops {\n'
            '  decision { fold { items "by" "topic" } }\n'
            '  mystery { fold { items "collect" 5 } }\n'
            '}\n'
        )
        with load_vertex_program(vpath) as p:
            state = p.vertex._loops["mystery"].state
            assert any(item.get("note") == "hi" for item in state["items"])


# ---------------------------------------------------------------------------
# VertexHandle.receive_as
# ---------------------------------------------------------------------------


class TestHandleReceiveAs:
    def _open(self, tmp_path, body):
        from engine.handle import WriteCredentials, open_vertex
        from engine.sqlite_store import SqliteStore

        store = tmp_path / "t.db"
        vpath = tmp_path / "t.vertex"
        vpath.write_text(body.format(store=store))
        SqliteStore(
            path=store, serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        ).close()

        class _Creds:
            def for_write(self, vertex):
                return WriteCredentials()

        return open_vertex(vpath, credentials=_Creds()), store

    def test_enforced_rejects_unknown_observer_and_potential(self, tmp_path):
        handle, store = self._open(
            tmp_path,
            'name "t"\nstore "{store}"\n'
            'observers {{ bot {{ grant {{ potential "log" }} }} }}\n'
            'loops {{\n'
            '  log {{ fold {{ items "collect" 5 }} }}\n'
            '  decision {{ fold {{ items "by" "topic" }} }}\n'
            '}}\n',
        )
        try:
            with pytest.raises(UnknownObserver):
                handle.receive_as(_fact("decision", observer="mallory", topic="x"))
            # potential gate: rejection receipt, no write
            res = handle.receive_as(_fact("decision", observer="bot", topic="x"))
            assert not res.receipt.stored
            # in-potential admits
            res = handle.receive_as(_fact("log", observer="bot", message="ok"))
            assert res.receipt.stored
            # explicit bypass: raw handle.receive admits out-of-potential
            res = handle.receive(_fact("decision", observer="bot", topic="x"))
            assert res.receipt.stored
        finally:
            handle.close()
        assert _stored_kinds(store) == ["log", "decision"]

    def test_strict_flows_through_handle(self, tmp_path):
        handle, store = self._open(
            tmp_path, 'name "t"\nstore "{store}"\nstrict true\n' + _DECISION_LOOP
        )
        try:
            with pytest.raises(UndeclaredKind):
                handle.receive(_fact("mystery", note="hi"))
            res = handle.receive(_fact("mystery", note="hi"), admit_undeclared=True)
            assert res.receipt.stored
        finally:
            handle.close()
        assert _stored_kinds(store) == ["mystery"]
