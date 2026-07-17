"""Regression tests — 0.8.0 capstone review, CLI-range findings.

M3-CLI: --at tick:/wall-clock floor forms must snap out of a ceremony span
  rather than refuse (fact:/seq: exact forms keep refusing).
M4: --why combined with --diff must refuse, not silently drop --diff.
M5: interactive dispatch (-i --lens autoresearch) must refuse an active
  --at/--as-of selector rather than resolve it into an unused Operation.
M6: a render-only custom lens (correct default fetch, but a render
  signature that doesn't declare `cursor`) must still show the mode-line
  label in text — injected at the dispatch layer, not refused.
M8: --diff must report interval honesty (late arrivals + declaration
  changes) in both registers, and endpoint labels must carry anchor,
  portable/unadopted state, and honesty-ladder status.
M9 (partial — the remaining coverage gaps not already closed elsewhere):
  a render-only-lens test (M6, above), an interactive-refusal test (M5,
  above), and a --refs depth>1 + as_of-mode threading test. The CLI
  lineage-handle round-trip + wrong-lineage refusal is already covered by
  test_durable_handle.py (the engine agent's capstone commit).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

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


@pytest.fixture
def capstone_vertex(tmp_path):
    v = (
        vertex("capstone")
        .store("./capstone.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
        .loop("note", fold_collect("items"))
    )
    vpath = tmp_path / "capstone.vertex"
    v.write(vpath)
    store = tmp_path / "capstone.db"
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict,
    ).close()
    return vpath, store


def _run(vpath, argv, *, reporter=None):
    r = reporter or BufferReporter()
    rc = read_view.run([str(vpath), *argv], ctx(r))
    return rc, r


# ---------------------------------------------------------------------------
# M3-CLI — floor forms snap out of a ceremony span
# ---------------------------------------------------------------------------


class TestM3FloorFormsSnapOutOfCeremony:
    def _ceremony_store(self, store):
        """before(rowid1) — [ceremony: rowid2,3, shared ts+lineage] — after(rowid4)."""
        from lang.document import DECL_KIND_DEFINED

        before = _append(store, "decision", 100, topic="a")
        d1 = _append(
            store, DECL_KIND_DEFINED, 200,
            lineage="LIN", subject="decision", payload={"folds": [], "order": 0},
        )
        _append(
            store, DECL_KIND_DEFINED, 200,
            lineage="LIN", subject="thread", payload={"folds": [], "order": 1},
        )
        after = _append(store, "decision", 300, topic="b")
        return before, d1, after

    def test_tick_cursor_mid_ceremony_snaps_before_first_row(self, capstone_vertex):
        vpath, store = capstone_vertex
        before, d1, _after = self._ceremony_store(store)
        # A tick whose fact_cursor lands on the FIRST (mid) ceremony row —
        # the scenario a durable-handle re-resolution across stores (B1c)
        # or a merge can produce even though the origin store never has a
        # reader observe a partial ceremony directly.
        tick_id = _append_tick(store, "capstone", 250.0, fact_cursor=d1)

        from loops.cli.witness_address import resolve_at_address

        pos = resolve_at_address(store, f"tick:{tick_id}")
        assert pos.fact_id == before  # snapped BEFORE the ceremony's first row

    def test_wallclock_floor_landing_mid_ceremony_snaps(self, capstone_vertex):
        vpath, store = capstone_vertex
        before, d1, _after = self._ceremony_store(store)
        _append_tick(store, "capstone", 250.0, fact_cursor=d1)

        mark = datetime.fromtimestamp(275.0, tz=timezone.utc).isoformat()
        from loops.cli.witness_address import resolve_at_address

        pos = resolve_at_address(store, mark)
        assert pos.fact_id == before

    def test_exact_fact_form_still_refuses_mid_ceremony(self, capstone_vertex):
        # Regression guard: fact:/seq: (exact forms) keep the "refuse"
        # default — only floor-derived forms (tick:/wall-clock) snap.
        vpath, store = capstone_vertex
        _before, d1, _after = self._ceremony_store(store)

        from engine.witness import MidReceiptGroupPosition
        from loops.cli.witness_address import resolve_at_address

        with pytest.raises(MidReceiptGroupPosition):
            resolve_at_address(store, f"fact:{d1}")

    def test_cli_end_to_end_reads_the_snapped_position(self, capstone_vertex):
        vpath, store = capstone_vertex
        before, d1, after = self._ceremony_store(store)
        tick_id = _append_tick(store, "capstone", 250.0, fact_cursor=d1)

        rc, r = _run(vpath, ["--at", f"tick:{tick_id}"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "a" in text  # the "before" fact's topic
        assert "b" not in text.split("MESSAGE")[-1] or "b" not in text  # "after" excluded


# ---------------------------------------------------------------------------
# M4 — --why + --diff must refuse, not silently drop --diff
# ---------------------------------------------------------------------------


class TestM4WhyDiffRefuses:
    def test_why_with_diff_refuses(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["decision/a", "--why", "--diff", "head..head"])
        assert rc == 2
        assert "--diff" in r.err_text
        assert "not supported together" in r.err_text

    def test_why_alone_still_works(self, capstone_vertex):
        # Regression guard.
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        rc, r = _run(vpath, ["decision/a", "--why"])
        assert rc == 0


# ---------------------------------------------------------------------------
# M5 — interactive dispatch refuses an active cursor selector
# ---------------------------------------------------------------------------


class TestM5InteractiveRefusesCursor:
    def test_interactive_at_refuses(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")
        rc, r = _run(vpath, ["-i", "--lens", "autoresearch", "--at", "head"])
        assert rc == 2
        assert "head-only" in r.err_text

    def test_interactive_as_of_refuses(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")
        rc, r = _run(vpath, ["-i", "--lens", "autoresearch", "--as-of", "150"])
        assert rc == 2
        assert "head-only" in r.err_text

    def test_interactive_without_cursor_still_engages(self, capstone_vertex, monkeypatch):
        # Regression guard: -i alone (no cursor flag) must still reach the
        # TUI handler exactly as before this fix.
        from loops.tui.autoresearch_app import AutoresearchApp

        async def fake_run(self):
            return None

        monkeypatch.setattr(AutoresearchApp, "run", fake_run)
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")
        rc, _r = _run(vpath, ["-i", "--lens", "autoresearch"])
        assert rc == 0


# ---------------------------------------------------------------------------
# M6 — render-only custom lens still carries the mode-line label
# ---------------------------------------------------------------------------


class TestM6RenderOnlyLensKeepsTheLabel:
    def _write_plain_lens(self, vpath: Path) -> None:
        lenses_dir = vpath.parent / "lenses"
        lenses_dir.mkdir(exist_ok=True)
        (lenses_dir / "plain.py").write_text(
            "from painted import Block, Style\n"
            "def fold_view(data, zoom, width):\n"
            "    return Block.text('CUSTOM RENDER', Style(), width=width)\n"
        )

    def test_render_only_lens_gets_mode_line_injected(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        self._write_plain_lens(vpath)

        rc, r = _run(vpath, ["--lens", "plain", "--at", "head"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "CUSTOM RENDER" in text  # the lens's own (correct) output
        assert "witness cursor" in text  # the label the lens itself dropped

    def test_render_only_lens_without_cursor_is_unaffected(self, capstone_vertex):
        # Regression guard: no cursor flag → no injected label, output
        # unchanged from before this fix.
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        self._write_plain_lens(vpath)

        rc, r = _run(vpath, ["--lens", "plain"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert text.strip() == "CUSTOM RENDER"


# ---------------------------------------------------------------------------
# M8 — --diff interval honesty + rich endpoint labels
# ---------------------------------------------------------------------------


class TestM8DiffIntervalHonesty:
    def test_late_arrival_reported_in_json(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")  # rowid1, seq1
        late_id = _append(store, "decision", 50, topic="b")  # rowid2 backdated, seq2

        r = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--diff", "seq:1..seq:2", "--json"], ctx(r),
        )
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        interval = payload["interval"]
        assert interval["late_arrivals"][0]["id"] == late_id
        assert interval["declaration_changed"] is False

    def test_late_arrival_reported_in_text(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")
        _append(store, "decision", 50, topic="b")

        rc, r = _run(vpath, ["--diff", "seq:1..seq:2"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "late arrival" in text

    def test_no_late_arrival_no_interval_line(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")
        _append(store, "decision", 200, topic="b")

        rc, r = _run(vpath, ["--diff", "seq:1..seq:2"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "late arrival" not in text
        assert "declaration changed" not in text

    def test_declaration_change_reported(self, capstone_vertex):
        from lang.document import DECL_KIND_DEFINED

        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")
        _append(
            store, DECL_KIND_DEFINED, 200,
            lineage="LIN", subject="decision", payload={"folds": [], "order": 0},
        )
        _append(store, "decision", 300, topic="b")

        r = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--diff", "seq:1..seq:3", "--json"], ctx(r),
        )
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        assert payload["interval"]["declaration_changed"] is True

        rc2, r2 = _run(vpath, ["--diff", "seq:1..seq:3"])
        assert rc2 == 0
        assert "declaration changed" in block_to_text(r2.blocks[0])

    def test_endpoint_labels_carry_anchor_and_status(self, capstone_vertex):
        vpath, store = capstone_vertex
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "capstone", 150.0, fact_cursor=f1)
        _append(store, "decision", 200, topic="b")

        rc, r = _run(vpath, ["--diff", "seq:1..seq:2"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "from:" in text and "to:" in text
        assert "anchored at tick 'capstone'" in text  # endpoint 1's anchor
        assert "ontology" in text  # file-pre-genesis notice on both endpoints

    def test_endpoint_json_still_carries_full_meta(self, capstone_vertex):
        vpath, store = capstone_vertex
        _append(store, "decision", 100, topic="a")
        _append(store, "decision", 200, topic="b")

        r = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--diff", "seq:1..seq:2", "--json"], ctx(r),
        )
        assert rc == 0
        payload = json.loads(r.out_lines[0])
        assert set(payload["from"]) >= {
            "mode", "status", "fact_id", "seq", "unadopted", "durable_handle", "portable",
        }


# ---------------------------------------------------------------------------
# M9 — --refs depth>1 threaded under as_of mode
# ---------------------------------------------------------------------------


class TestRefsDepthTwoUnderAsOf:
    def test_two_hop_walk_reflects_the_as_of_cutoff(self, capstone_vertex):
        vpath, store = capstone_vertex
        # decision/a --ref--> thread/t1 --ref--> note (collect, no ref target
        # needed) — use decision -> thread -> decision chain instead so both
        # hops are keyed (by-fold) and diffable by content.
        _append(
            store, "decision", 100, topic="a", message="alpha",
            ref="thread:t1",
        )
        _append(
            store, "thread", 100, name="t1", message="hop1",
            ref="decision:b",
        )
        _append(store, "decision", 100, topic="b", message="hop2-before")
        cutoff = 150.0
        # A later update to the depth-2 target, AFTER the as_of cutoff.
        _append(store, "decision", 200, topic="b", message="hop2-after")

        rc, r = _run(
            vpath, ["decision/a", "--as-of", str(cutoff), "--refs", "2"],
        )
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "hop1" in text          # depth-1 walked item
        assert "hop2-before" in text   # depth-2 walked item, AS OF the cutoff
        assert "hop2-after" not in text  # post-cutoff update excluded

    def test_two_hop_walk_at_head_sees_the_latest(self, capstone_vertex):
        # Regression guard: an uncursored refs walk is unaffected.
        vpath, store = capstone_vertex
        _append(
            store, "decision", 100, topic="a", message="alpha",
            ref="thread:t1",
        )
        _append(
            store, "thread", 100, name="t1", message="hop1",
            ref="decision:b",
        )
        _append(store, "decision", 100, topic="b", message="hop2-before")
        _append(store, "decision", 200, topic="b", message="hop2-after")

        rc, r = _run(vpath, ["decision/a", "--refs", "2"])
        assert rc == 0
        text = block_to_text(r.blocks[0])
        assert "hop2-after" in text
