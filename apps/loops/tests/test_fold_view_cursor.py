"""cli.views.fold — --at / --as-of end-to-end (0.8.0 temporal cursor, C1).

Drives the real ``read`` router → fold view → dispatch path against scratch
vertices with controlled fact/tick timestamps (raw sqlite appends, matching
the engine test convention in libs/engine/tests/test_witness_position.py —
precise rowid/ts control isn't reachable through the emit path's wall-clock
stamping). Engine-level correctness (receipt-group guard, adoption marker,
tick anchor) is proven in libs/engine/tests; this file proves the CLI wiring:
address-grammar dispatch, refusal + teaching text, snap reporting via the
mode line, and the JSON cursor field end-to-end.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from atoms import Fact

from engine.builder import fold_by, vertex
from engine.sqlite_store import SqliteStore, gen_id
from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import read as read_view

from .golden.helpers import block_to_text


def ctx(reporter: BufferReporter | None = None) -> Invocation:
    return Invocation(reporter=reporter or BufferReporter())


@pytest.fixture
def cursor_vertex(tmp_path):
    """A fresh (pre-genesis) store — the dominant live-corpus shape."""
    v = vertex("cursor").store("./c.db").loop("decision", fold_by("topic"))
    vpath = tmp_path / "cursor.vertex"
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


def _run(vpath, argv, *, reporter=None) -> tuple[int, BufferReporter]:
    r = reporter or BufferReporter()
    rc = read_view.run([str(vpath), *argv], ctx(r))
    return rc, r


class TestAtAddressForms:
    def test_head(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["--at", "head"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "alpha" in text
        assert "witness cursor" in text and "seq 1" in text

    def test_head_excludes_later_facts(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc1, r1 = _run(vpath, ["--at", "head"])
        _append(store, "decision", 101, topic="b", message="beta")
        rc2, r2 = _run(vpath, ["--at", "head"])
        assert rc1 == 0 and rc2 == 0
        assert "beta" not in block_to_text(r1.blocks[0])
        assert "beta" in block_to_text(r2.blocks[0])

    def test_fact_prefix(self, cursor_vertex):
        # Explicit ids, not gen_id() output: adjacent gen_id() calls can
        # correlate closely in their tail bits (the documented ~1/5000
        # within-ms inversion is a symptom of the same lack-of-independence),
        # so two back-to-back calls are not a safe source of a guaranteed-
        # unique prefix — this proves prefix EXPANSION, not id generation.
        vpath, store = cursor_vertex
        _append(store, "decision", 100, fid="01FACTPREFIXAAAAAAAAAAAAAA", topic="a", message="alpha")
        _append(store, "decision", 200, fid="01FACTPREFIXZZZZZZZZZZZZZZ", topic="b", message="beta")
        rc, r = _run(vpath, ["--at", "fact:01FACTPREFIXAAAA"])
        assert rc == 0, r.err_text
        text = block_to_text(r.blocks[0])
        assert "alpha" in text and "beta" not in text

    def test_seq(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        _append(store, "decision", 200, topic="b", message="beta")
        rc, r = _run(vpath, ["--at", "seq:1"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "alpha" in text and "beta" not in text

    def test_seq_out_of_range_refuses_with_teaching(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["--at", "seq:99"])
        assert rc == 2
        assert "out of range" in r.err_text

    def test_tick(self, cursor_vertex):
        vpath, store = cursor_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "cursor", 150.0, fact_cursor=f1)
        _append(store, "decision", 200, topic="b", message="beta")
        rc, r = _run(vpath, ["--at", "tick:cursor"])
        # tick: expects a tick ID, not a name — this should be an unknown handle.
        assert rc == 2
        assert "no tick with id" in r.err_text

    def test_tick_by_id(self, cursor_vertex):
        vpath, store = cursor_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        tid = _append_tick(store, "cursor", 150.0, fact_cursor=f1)
        _append(store, "decision", 200, topic="b", message="beta")
        rc, r = _run(vpath, ["--at", f"tick:{tid}"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "alpha" in text and "beta" not in text
        assert "anchored at tick 'cursor'" in text

    def test_wallclock_snaps_to_tick_floor(self, cursor_vertex):
        vpath, store = cursor_vertex
        f1 = _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "cursor", 150.0, fact_cursor=f1)
        f2 = _append(store, "decision", 200, topic="b", message="beta")
        _append_tick(store, "cursor", 250.0, fact_cursor=f2)
        _append(store, "decision", 300, topic="c", message="gamma")

        # A mark between the two ticks floors to the FIRST.
        from datetime import datetime, timezone

        mark = datetime.fromtimestamp(175.0, tz=timezone.utc).isoformat()
        rc, r = _run(vpath, ["--at", mark])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "alpha" in text and "beta" not in text and "gamma" not in text
        assert "anchored at tick 'cursor'" in text  # the snap is reported

    def test_wallclock_no_tick_refuses_naming_as_of(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["--at", "2026-01-01"])
        assert rc == 2
        assert "no witness-time anchor" in r.err_text or "no witness anchor" in r.err_text
        assert "--as-of" in r.err_text  # teaches the explicit event-time mode

    def test_ambiguous_fact_prefix_refuses(self, cursor_vertex):
        # Two explicit ids sharing a prefix — deterministic ambiguity,
        # surfaced as a clean CLI refusal rather than an unhandled ValueError.
        vpath, store = cursor_vertex
        _append(store, "decision", 100, fid="01AMBIGUOUSPREFIXAAAAAAAAA", topic="a", message="alpha")
        _append(store, "decision", 200, fid="01AMBIGUOUSPREFIXBBBBBBBBB", topic="b", message="beta")
        rc, r = _run(vpath, ["--at", "fact:01AMBIGUOUSPREFIX"])
        assert rc == 2
        assert "ambiguous" in r.err_text.lower()

    def test_unknown_fact_id_refuses(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["--at", "fact:01NONEXISTENTID0000000000"])
        assert rc == 2
        assert "no fact matches" in r.err_text

    def test_malformed_seq_refuses(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["--at", "seq:notanumber"])
        assert rc == 2
        assert "integer" in r.err_text


class TestAsOfProjection:
    def test_excludes_facts_after_cutoff(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        _append(store, "decision", 200, topic="b", message="beta")
        rc, r = _run(vpath, ["--as-of", "150"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "alpha" in text and "beta" not in text
        assert "event-time projection" in text

    def test_json_carries_mode_and_status(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        r = BufferReporter()
        rc = read_view.run([str(vpath), "--as-of", "150", "--json"], ctx(r))
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        assert payload["cursor"]["mode"] == "as_of"
        assert payload["cursor"]["status"] == "file-pre-genesis"
        assert payload["cursor"]["as_of"] == 150.0


class TestWitnessJson:
    def test_json_carries_witness_fields(self, cursor_vertex):
        vpath, store = cursor_vertex
        fid = _append(store, "decision", 100, topic="a", message="alpha")
        r = BufferReporter()
        rc = read_view.run([str(vpath), "--at", "head", "--json"], ctx(r))
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        cursor = payload["cursor"]
        assert cursor["mode"] == "witness"
        assert cursor["fact_id"] == fid
        assert cursor["seq"] == 1
        assert cursor["unadopted"] is True


class TestAggregateRefusal:
    def _aggregate(self, tmp_path, member_vpath):
        agg = tmp_path / "agg.vertex"
        agg.write_text(f'name "agg"\ncombine {{\n  vertex "{member_vpath}"\n}}\n')
        return agg

    def test_seq_form_teaches_member_addressing(self, tmp_path, cursor_vertex):
        member_vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        agg = self._aggregate(tmp_path, member_vpath)
        rc, r = _run(agg, ["--at", "seq:1"])
        assert rc == 2
        assert "member-scoped" in r.err_text

    def test_wallclock_form_teaches_not_yet_implemented(self, tmp_path, cursor_vertex):
        member_vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        agg = self._aggregate(tmp_path, member_vpath)
        rc, r = _run(agg, ["--at", "2026-01-01"])
        assert rc == 2
        assert "not yet implemented" in r.err_text

    def test_as_of_allowed_on_aggregate(self, tmp_path, cursor_vertex):
        member_vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        agg = self._aggregate(tmp_path, member_vpath)
        rc, r = _run(agg, ["--as-of", "150"])
        assert rc == 0
        assert "alpha" in block_to_text(r.blocks[0])


class TestWhyRefusesCursor:
    def test_why_with_at_refuses(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["decision/a", "--why", "--at", "head"])
        assert rc == 2
        assert "not supported together" in r.err_text
