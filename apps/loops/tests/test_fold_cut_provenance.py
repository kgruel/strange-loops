"""Honest seal-cut provenance — the ``cut`` render_context/JSON contract
(0.9.0 S6, friction:seal-provenance-not-passed-to-lenses).

Two tiers, mirroring test_fold_view_cursor.py / test_fold_cursor_render.py:

- End-to-end (``TestResolveCutEndToEnd*``): drives the real ``read`` router
  through ``cli.witness_address.resolve_cut``/``cut_from_witness_position``
  against scratch stores with controlled fact/tick timestamps (raw sqlite
  appends — the same convention test_fold_view_cursor.py uses for precise
  rowid/ts control).
- Dispatch-level (``TestJsonCutField``): the render_context["cut"] → JSON
  merge, on both the gate-pass (Surface) and gate-fail (raw dump) branches,
  against a hand-built FoldState — no store needed, purely the plumbing
  test_fold_cursor_render.py already proves for "cursor".
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from atoms import Fact, FoldItem, FoldSection, FoldState
from painted import Fidelity
from painted.cli import Format

from engine.builder import fold_by, vertex
from engine.sqlite_store import SqliteStore, gen_id
from loops.cli.dispatch import dispatch
from loops.cli.invocation import Invocation
from loops.cli.operation import Operation
from loops.cli.output import BufferReporter
from loops.cli.views import read as read_view
from loops.cli import witness_address
from loops.lens_resolver import call_lens

from .golden.helpers import block_to_text


def ctx(reporter: BufferReporter | None = None, *, isatty: bool = False) -> Invocation:
    return Invocation(reporter=reporter or BufferReporter(), isatty=isatty)


@pytest.fixture
def cut_vertex(tmp_path):
    """A fresh (pre-genesis, never-sealed) store — same shape as
    test_fold_view_cursor.py's cursor_vertex fixture."""
    v = vertex("cut").store("./c.db").loop("decision", fold_by("topic"))
    vpath = tmp_path / "cut.vertex"
    v.write(vpath)
    store = tmp_path / "c.db"
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict,
    ).close()
    return vpath, store


def _append(store, kind, ts, *, fid=None, observer="kyle", **payload) -> str:
    conn = sqlite3.connect(str(store))
    fid = fid or gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (fid, kind, ts, observer, "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()
    return fid


def _append_tick(store, name, ts, *, fact_cursor=None) -> str:
    conn = sqlite3.connect(str(store))
    tid = gen_id()
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload, fact_cursor) "
        "VALUES (?, ?, ?, 0.0, '', '{}', ?)",
        (tid, name, ts, fact_cursor),
    )
    conn.commit()
    conn.close()
    return tid


def _run(vpath, argv, *, reporter=None, isatty=False) -> tuple[int, BufferReporter]:
    r = reporter or BufferReporter()
    rc = read_view.run([str(vpath), *argv], ctx(r, isatty=isatty))
    return rc, r


def _read_json(vpath, argv, *, isatty=False) -> dict:
    rc, r = _run(vpath, [*argv, "--json"], isatty=isatty)
    assert rc == 0, r.err_text
    return json.loads(r.out_lines[0])


# ---------------------------------------------------------------------------
# End-to-end: default (head) read
# ---------------------------------------------------------------------------


class TestResolveCutEndToEndDefaultRead:
    def test_fresh_never_sealed_store(self, cut_vertex):
        vpath, store = cut_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        payload = _read_json(vpath, [])
        cut = payload["cut"]
        assert cut["available"] is True
        assert cut["anchor"] is None
        assert cut["sealed_to_head"] is False
        assert cut["tick_total"] == 0
        assert cut["facts_beyond_seal"] == 1

    def test_present_on_tty_and_piped(self, cut_vertex):
        vpath, store = cut_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        for isatty in (True, False):
            payload = _read_json(vpath, [], isatty=isatty)
            assert payload["cut"]["available"] is True

    def test_sealed_to_head(self, cut_vertex):
        vpath, store = cut_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "cut", 150.0, fact_cursor=f1)
        payload = _read_json(vpath, [])
        cut = payload["cut"]
        assert cut["available"] is True
        assert cut["sealed_to_head"] is True
        assert cut["anchor"]["name"] == "cut"
        assert cut["tick_total"] == 1
        assert cut["facts_beyond_seal"] == 0

    def test_sealed_with_unsealed_tail(self, cut_vertex):
        vpath, store = cut_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "cut", 150.0, fact_cursor=f1)
        _append(store, "decision", 200, topic="b", message="beta")
        _append(store, "decision", 300, topic="c", message="gamma")
        payload = _read_json(vpath, [])
        cut = payload["cut"]
        assert cut["available"] is True
        assert cut["sealed_to_head"] is False
        assert cut["anchor"]["name"] == "cut"
        assert cut["tick_total"] == 1
        assert cut["facts_beyond_seal"] == 2

    def test_uncreated_store_is_unavailable_not_a_crash(self, tmp_path):
        v = vertex("nostore").store("./nope.db").loop("decision", fold_by("topic"))
        vpath = tmp_path / "nostore.vertex"
        v.write(vpath)
        # deliberately never create ./nope.db
        payload = _read_json(vpath, [])
        cut = payload["cut"]
        assert cut["available"] is False
        assert cut["reason"]
        assert "unsealed" not in cut["reason"].lower()
        assert "live" not in cut["reason"].lower()

    def test_aggregate_vertex_refuses_gracefully(self, tmp_path, cut_vertex):
        member_vpath, store = cut_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        agg = tmp_path / "agg.vertex"
        agg.write_text(f'name "agg"\ncombine {{\n  vertex "{member_vpath}"\n}}\n')
        payload = _read_json(agg, [])
        cut = payload["cut"]
        assert cut["available"] is False
        assert "aggregate vertex" in cut["reason"]
        assert "no single witness cut across members" in cut["reason"]


# ---------------------------------------------------------------------------
# End-to-end: --at / --as-of interplay (AC7/AC8)
# ---------------------------------------------------------------------------


class TestResolveCutEndToEndCursorInterplay:
    def test_at_head_carries_witness_mode_cut_with_no_extra_fields(self, cut_vertex):
        vpath, store = cut_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "cut", 150.0, fact_cursor=f1)
        payload = _read_json(vpath, ["--at", "head"])
        # existing cursor contract is untouched
        assert payload["cursor"]["mode"] == "witness"
        assert payload["cursor"]["fact_id"] == f1
        # new cut contract rides alongside it, derived from the SAME position
        cut = payload["cut"]
        assert cut["available"] is True
        assert cut["mode"] == "witness"
        assert cut["sealed_to_head"] is True
        assert cut["anchor"]["name"] == "cut"
        # zero-extra-I/O fields: not resolved in witness mode
        assert cut["tick_total"] is None
        assert cut["facts_beyond_seal"] is None

    def test_as_of_cut_is_unavailable_with_reason(self, cut_vertex):
        vpath, store = cut_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        payload = _read_json(vpath, ["--as-of", "150"])
        assert payload["cursor"]["mode"] == "as_of"  # untouched
        cut = payload["cut"]
        assert cut["available"] is False
        assert cut["mode"] == "as_of"
        assert "event-time" in cut["reason"]


# ---------------------------------------------------------------------------
# Unit: witness_address.resolve_cut / cut_from_witness_position directly
# ---------------------------------------------------------------------------


class TestResolveCutUnit:
    def test_empty_store(self, cut_vertex):
        _vpath, store = cut_vertex
        cut = witness_address.resolve_cut(_vpath)
        assert cut == {
            "available": True,
            "mode": "head",
            "anchor": None,
            "sealed_to_head": False,
            "tick_total": 0,
            "facts_beyond_seal": 0,
            "reason": None,
        }

    def test_no_seal_store(self, cut_vertex):
        vpath, store = cut_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        cut = witness_address.resolve_cut(vpath)
        assert cut["available"] is True
        assert cut["anchor"] is None
        assert cut["sealed_to_head"] is False
        assert cut["facts_beyond_seal"] == 1

    def test_sealed_store(self, cut_vertex):
        vpath, store = cut_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "cut", 150.0, fact_cursor=f1)
        cut = witness_address.resolve_cut(vpath)
        assert cut["sealed_to_head"] is True
        assert cut["facts_beyond_seal"] == 0

    def test_seal_plus_tail_store(self, cut_vertex):
        vpath, store = cut_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "cut", 150.0, fact_cursor=f1)
        _append(store, "decision", 200, topic="b", message="beta")
        cut = witness_address.resolve_cut(vpath)
        assert cut["sealed_to_head"] is False
        assert cut["facts_beyond_seal"] == 1

    def test_unavailable_cut_shape(self):
        assert witness_address.unavailable_cut("as_of", "because") == {
            "available": False,
            "mode": "as_of",
            "anchor": None,
            "sealed_to_head": False,
            "tick_total": None,
            "facts_beyond_seal": None,
            "reason": "because",
        }


# ---------------------------------------------------------------------------
# Dispatch-level: render_context["cut"] -> JSON merge, both branches
# ---------------------------------------------------------------------------


def _state() -> FoldState:
    return FoldState(
        sections=(
            FoldSection(
                kind="decision",
                items=(
                    FoldItem(payload={"topic": "a", "message": "alpha"}, ts=100.0),
                ),
                fold_type="by",
                key_field="topic",
            ),
        ),
        vertex="t",
    )


_AVAILABLE_CUT = {
    "available": True,
    "mode": "head",
    "anchor": None,
    "sealed_to_head": False,
    "tick_total": 0,
    "facts_beyond_seal": 0,
    "reason": None,
}


class TestJsonCutField:
    def test_gate_pass_json_carries_cut(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold", format=Format.JSON,
            render_context={"cut": _AVAILABLE_CUT},
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        payload = json.loads(reporter.out_lines[0])
        assert "rows" in payload  # the Surface (gate-pass) shape
        assert payload["cut"] == _AVAILABLE_CUT

    def test_gate_fail_json_carries_cut(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold", format=Format.JSON,
            lens_override="autoresearch",  # resolvable, != built-in → gate fails
            render_context={"cut": _AVAILABLE_CUT},
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        payload = json.loads(reporter.out_lines[0])
        assert "sections" in payload["data"]
        assert payload["cut"] == _AVAILABLE_CUT

    def test_cut_and_cursor_both_merge_gate_pass(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold", format=Format.JSON,
            render_context={"cut": _AVAILABLE_CUT, "cursor": {"mode": "as_of"}},
        )
        reporter = BufferReporter()
        dispatch(op, reporter=reporter)
        payload = json.loads(reporter.out_lines[0])
        assert payload["cut"] == _AVAILABLE_CUT
        assert payload["cursor"] == {"mode": "as_of"}

    def test_no_cut_key_omits_field(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold", format=Format.JSON,
        )
        reporter = BufferReporter()
        dispatch(op, reporter=reporter)
        payload = json.loads(reporter.out_lines[0])
        assert "cut" not in payload


# ---------------------------------------------------------------------------
# A lens declaring a `cut` kwarg receives it — call_lens's EXISTING
# signature-filtered dispatch, zero changes needed (AC10).
# ---------------------------------------------------------------------------


class TestLensReceivesCutKwarg:
    def test_fake_lens_declaring_cut_receives_it(self):
        received = {}

        def fake_lens(data, zoom, width, *, cut=None):
            received["cut"] = cut
            return "ok"

        result = call_lens(
            fake_lens, "data", Fidelity(), 80,
            cut=_AVAILABLE_CUT, vertex_name="p",
        )
        assert result == "ok"
        assert received["cut"] == _AVAILABLE_CUT

    def test_lens_without_cut_param_does_not_receive_it(self):
        def fake_lens(data, zoom, width):
            return "plain"

        # No error, no crash — kwarg is silently dropped like any other
        # unrecognized context kwarg (existing call_lens contract).
        result = call_lens(fake_lens, "data", Fidelity(), 80, cut=_AVAILABLE_CUT)
        assert result == "plain"


# ---------------------------------------------------------------------------
# cut_line — the shared honesty-ladder render helper (AC10/AC12)
# ---------------------------------------------------------------------------


class TestCutLine:
    def test_unavailable_never_claims_live_unsealed(self):
        from loops.lenses._grammar import cut_line

        cut = {"available": False, "reason": "aggregate vertex"}
        text = block_to_text(cut_line(cut, None))
        assert "unavailable" in text
        assert "aggregate vertex" in text
        assert "live unsealed" not in text.lower()

    def test_sealed_to_head(self):
        from loops.lenses._grammar import cut_line

        cut = {
            "available": True,
            "sealed_to_head": True,
            "anchor": {"name": "cut", "ts": 150.0, "fact_cursor": "x"},
        }
        text = block_to_text(cut_line(cut, None))
        assert "sealed" in text
        assert "cut" in text

    def test_live_with_anchor(self):
        from loops.lenses._grammar import cut_line

        cut = {
            "available": True,
            "sealed_to_head": False,
            "anchor": {"name": "cut", "ts": 150.0, "fact_cursor": "x"},
            "facts_beyond_seal": 2,
        }
        text = block_to_text(cut_line(cut, None))
        assert "2 fact(s)" in text
        assert "beyond the last seal" in text

    def test_live_no_anchor_never_sealed(self):
        from loops.lenses._grammar import cut_line

        cut = {"available": True, "sealed_to_head": False, "anchor": None}
        text = block_to_text(cut_line(cut, None))
        assert "unsealed tail — no prior tick anchor" in text
        assert "sealed as of" not in text
