"""cli.views.fold — --diff end-to-end (0.8.0 temporal cursor, C2).

Same scratch-store conventions as test_fold_view_cursor.py — raw sqlite
appends for controlled rowid/ts. Proves: structural diff correctness
(added/removed/changed), the collect-fold count-only degradation, the
backdated-arrival case (two witness positions differ via revision count
even though the VISIBLE winning payload agrees — the point of the ``_n``
synthetic field), the alt ``--at A --diff B`` syntax, mixed-mode refusal,
and aggregate refusal.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from atoms import Fact

from engine.builder import fold_by, fold_collect, vertex
from engine.sqlite_store import SqliteStore, gen_id
from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import read as read_view

from .golden.helpers import block_to_text


def ctx(reporter: BufferReporter | None = None) -> Invocation:
    return Invocation(reporter=reporter or BufferReporter())


@pytest.fixture
def diff_vertex(tmp_path):
    v = (
        vertex("diffv")
        .store("./d.db")
        .loop("decision", fold_by("topic"))
        .loop("note", fold_collect("items"))
    )
    vpath = tmp_path / "diffv.vertex"
    v.write(vpath)
    store = tmp_path / "d.db"
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


def _run(vpath, argv, *, reporter=None) -> tuple[int, BufferReporter]:
    r = reporter or BufferReporter()
    rc = read_view.run([str(vpath), *argv], ctx(r))
    return rc, r


class TestDiffCorrectness:
    def test_added_key(self, diff_vertex):
        vpath, store = diff_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc1, r1 = _run(vpath, ["--at", "head"])
        assert rc1 == 0
        _append(store, "decision", 200, topic="b", message="beta")
        rc, r = _run(vpath, ["--diff", "seq:1..seq:2"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "decision: +1 added, -0 removed, ~0 changed" in text
        assert "+ b" in text

    def test_removed_key_via_json(self, diff_vertex):
        # A "removed" key needs a position that HAD it and one that doesn't —
        # seq:1 has only 'a', seq:1 (reversed order in the diff call) shows
        # the mirror: diffing seq:2..seq:1 shows 'b' as removed.
        vpath, store = diff_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        _append(store, "decision", 200, topic="b", message="beta")
        r = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--diff", "seq:2..seq:1", "--json"], ctx(r),
        )
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        assert payload["mode"] == "diff"
        section = next(s for s in payload["sections"] if s["kind"] == "decision")
        assert section["removed"] == ["b"]
        assert section["added"] == []

    def test_changed_key(self, diff_vertex):
        vpath, store = diff_vertex
        _append(store, "decision", 100, topic="a", message="alpha", status="open")
        rc1, _ = _run(vpath, ["--at", "head"])
        assert rc1 == 0
        _append(store, "decision", 200, topic="a", message="alpha", status="resolved")
        r = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--diff", "seq:1..seq:2", "--json"], ctx(r),
        )
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        section = next(s for s in payload["sections"] if s["kind"] == "decision")
        assert [c["key"] for c in section["changed"]] == ["a"]
        changed = section["changed"][0]
        assert changed["before"]["status"] == "open"
        assert changed["after"]["status"] == "resolved"

    def test_no_differences(self, diff_vertex):
        vpath, store = diff_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["--diff", "head..head"])
        assert rc == 0
        assert "no differences" in block_to_text(r.blocks[0])

    def test_collect_fold_is_count_only(self, diff_vertex):
        vpath, store = diff_vertex
        _append(store, "note", 100, text="one")
        rc1, _ = _run(vpath, ["--at", "head"])
        assert rc1 == 0
        _append(store, "note", 200, text="two")
        r = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--diff", "seq:1..seq:2", "--json"], ctx(r),
        )
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        section = next(s for s in payload["sections"] if s["kind"] == "note")
        assert section["collect_count"] == {"before": 1, "after": 2}

    def test_at_diff_alt_syntax(self, diff_vertex):
        vpath, store = diff_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc1, _ = _run(vpath, ["--at", "head"])
        assert rc1 == 0
        _append(store, "decision", 200, topic="b", message="beta")
        rc, r = _run(vpath, ["--at", "seq:1", "--diff", "seq:2"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "+ b" in text


class TestBackdatedArrivalDiff:
    def test_witness_positions_differ_via_revision_count(self, diff_vertex):
        """Two witness positions can differ (a receipt happened) even when
        the VISIBLE winning payload is identical — a later-received fact
        with an EARLIER ts loses (ts, id) replay to the fact already there,
        so the rendered value never changes, but the receipt count (`_n`)
        does. This is exactly why the cursor axis is witness order, not a
        ts-projection: something happened between these two positions that
        a ts-only view could never distinguish."""
        vpath, store = diff_vertex
        # A: ts=100 (rowid 1) — the eventual (ts,id) winner.
        _append(store, "decision", 100, topic="x", message="alpha")
        rc1, _ = _run(vpath, ["--at", "head"])
        assert rc1 == 0
        # B: backdated ts=50 (rowid 2) — loses to A under (ts, id) replay.
        _append(store, "decision", 50, topic="x", message="beta")

        r = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--diff", "seq:1..seq:2", "--json"], ctx(r),
        )
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        section = next(s for s in payload["sections"] if s["kind"] == "decision")
        assert [c["key"] for c in section["changed"]] == ["x"]
        changed = section["changed"][0]
        # The visible winning field never changed — A (ts=100) wins both times.
        assert changed["before"]["message"] == "alpha"
        assert changed["after"]["message"] == "alpha"
        # ...but the receipt count did: seq:2 has RECEIVED both rows.
        assert changed["before"]["_n"] == 1
        assert changed["after"]["_n"] == 2

    def test_head_render_unaffected_by_the_backdated_loser(self, diff_vertex):
        # Confirms the *rendered* fold state at head also shows A winning —
        # the diff's "_n only" finding isn't a diff-layer artifact.
        vpath, store = diff_vertex
        _append(store, "decision", 100, topic="x", message="alpha")
        _append(store, "decision", 50, topic="x", message="beta")
        rc, r = _run(vpath, ["--at", "head"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "alpha" in text and "beta" not in text


class TestDiffRefusals:
    def test_missing_second_address(self, diff_vertex):
        vpath, _store = diff_vertex
        rc, r = _run(vpath, ["--diff", "headonly"])
        assert rc == 2
        assert "two addresses" in r.err_text

    def test_diff_and_at_both_full_forms_refused(self, diff_vertex):
        vpath, _store = diff_vertex
        rc, r = _run(vpath, ["--at", "head", "--diff", "head..head"])
        assert rc == 2
        assert "not both" in r.err_text

    def test_mixed_mode_as_of_and_diff_refused(self, diff_vertex):
        vpath, _store = diff_vertex
        rc, r = _run(vpath, ["--as-of", "30d", "--diff", "head..head"])
        assert rc == 2
        assert "mixed modes" in r.err_text

    def test_unresolvable_endpoint_refuses(self, diff_vertex):
        vpath, store = diff_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["--diff", "head..seq:99"])
        assert rc == 2
        assert "out of range" in r.err_text


class TestDiffAggregateRefusal:
    def test_diff_on_aggregate_refuses_per_endpoint(self, tmp_path, diff_vertex):
        member_vpath, store = diff_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        agg = tmp_path / "agg.vertex"
        agg.write_text(f'name "agg"\ncombine {{\n  vertex "{member_vpath}"\n}}\n')
        rc, r = _run(agg, ["--diff", "seq:1..seq:2"])
        assert rc == 2
        assert "member-scoped" in r.err_text
