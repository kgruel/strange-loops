"""Horizon — the open-window-against-boundary view (build-1).

Covers the net-new open-window reconstruction (newest tick ts per series →
facts strictly after → aggregate by kind), the two boundary shapes rendered
honestly (count-based proximity meter vs kind-based fact-count wording), the
never-sealed and no-boundary honest degrades, and both registers. Channel
parity is pinned by the harness; the cross-command grammar golden carries the
byte-level surface (the grammar fixture's vertex-level boundary is one row).
"""
from __future__ import annotations

from atoms import Fact
from engine import load_vertex_program
from painted import Zoom

from loops.commands.fetch import fetch_horizon
from loops.lenses.horizon import _meter, horizon_view

from .helpers import block_to_text
from .parity import assert_register_parity

_T0 = 1735732800.0


def _count_vertex(dir_path, *, count: int, n_facts: int, name: str = "h"):
    """A vertex with a count-based per-loop boundary (``every=count``)."""
    vp = dir_path / f"{name}.vertex"
    vp.write_text(
        f'name "{name}"\nstore "./{name}.db"\n\nloops {{\n'
        f'  decision {{ fold {{ items "by" "topic" }}\n'
        f'    boundary every="{count}" }}\n'
        f'  thread {{ fold {{ items "by" "name" }} }}\n'
        "}\n"
    )
    prog = load_vertex_program(vp)
    for i in range(n_facts):
        prog.receive(Fact.of("decision", "kyle", ts=_T0 + i, topic=f"x{i}", message="m"))
    return vp


def _vertex_boundary(dir_path, name: str = "v"):
    """A vertex with a kind-based vertex-level boundary (``when session closed``).

    One decision, then a session close (fires the seal), then one more decision
    landing in the open window.
    """
    vp = dir_path / f"{name}.vertex"
    vp.write_text(
        f'name "{name}"\nstore "./{name}.db"\n\nloops {{\n'
        '  decision { fold { items "by" "topic" } }\n'
        '  session { fold { items "by" "name" } }\n\n'
        '  boundary when="session" status="closed"\n'
        "}\n"
    )
    prog = load_vertex_program(vp)
    prog.receive(Fact.of("decision", "kyle", ts=_T0, topic="a", message="m"))
    prog.receive(Fact.of("session", "kyle", ts=_T0 + 1, name="s1", status="closed"))
    prog.receive(Fact.of("decision", "kyle", ts=_T0 + 2, topic="b", message="m"))
    return vp


def _two_vertex_boundaries(dir_path, name: str = "tv"):
    """A vertex declaring TWO vertex-level boundaries (``session closed`` and
    ``seal``). Both must render as their own honest row — earlier declarations
    were previously dropped (friction:vertex-boundary-last-declaration-wins).
    """
    vp = dir_path / f"{name}.vertex"
    vp.write_text(
        f'name "{name}"\nstore "./{name}.db"\n\nloops {{\n'
        '  decision { fold { items "by" "topic" } }\n'
        '  session { fold { items "by" "name" } }\n\n'
        '  boundary when="session" status="closed"\n'
        '  boundary when="seal"\n'
        "}\n"
    )
    prog = load_vertex_program(vp)
    prog.receive(Fact.of("decision", "kyle", ts=_T0, topic="a", message="m"))
    return vp


def _no_boundary(dir_path, name: str = "nb"):
    vp = dir_path / f"{name}.vertex"
    vp.write_text(
        f'name "{name}"\nstore "./{name}.db"\n\nloops {{\n'
        '  decision { fold { items "by" "topic" } }\n'
        "}\n"
    )
    prog = load_vertex_program(vp)
    prog.receive(Fact.of("decision", "kyle", ts=_T0, topic="a", message="m"))
    return vp


def _render(data, zoom=Zoom.SUMMARY, width=100, *, piped=False) -> str:
    return block_to_text(horizon_view(data, zoom, width, piped=piped), use_ansi=False)


class TestOpenWindow:
    def test_count_proximity_math(self, tmp_path):
        # 5 facts, every=3 → one seal at the 3rd; window = the 2 facts after.
        data = fetch_horizon(_count_vertex(tmp_path, count=3, n_facts=5))
        assert data["armed"] == 1  # the un-boundaried thread loop is omitted
        row = data["loops"][0]
        assert row["mode"] == "every"
        assert row["count"] == 3
        assert row["window_facts"] == 2  # strictly after the seal
        assert row["never_sealed"] is False
        assert data["total_unsealed"] == 2

    def test_never_ticked_loop(self, tmp_path):
        # 4 facts, every=10 → never fires; the whole history is the open window.
        data = fetch_horizon(_count_vertex(tmp_path, count=10, n_facts=4))
        row = data["loops"][0]
        assert row["never_sealed"] is True
        assert row["last_sealed"] is None
        assert row["window_facts"] == 4  # window starts at the first fact

    def test_kind_based_vertex_boundary(self, tmp_path):
        data = fetch_horizon(_vertex_boundary(tmp_path))
        assert data["armed"] == 1
        row = data["loops"][0]
        assert row["scope"] == "vertex"
        assert row["mode"] == "when"
        assert row["trigger_kind"] == "session"
        assert row["match"] == [["status", "closed"]]
        # The vertex-level window spans ALL kinds after the seal — one decision.
        assert row["window_facts"] == 1
        assert row["window_kinds"] == {"decision": 1}

    def test_multiple_vertex_boundaries_each_render_a_row(self, tmp_path):
        data = fetch_horizon(_two_vertex_boundaries(tmp_path))
        # Both vertex-level boundaries are armed rows — neither is dropped.
        assert data["armed"] == 2
        vrows = [r for r in data["loops"] if r["scope"] == "vertex"]
        assert len(vrows) == 2
        triggers = {r["trigger_kind"] for r in vrows}
        assert triggers == {"session", "seal"}
        # Both share the vertex-named tick series but differ by trigger.
        assert all(r["name"] == "tv" for r in vrows)

    def test_no_boundary_vertex_has_empty_roster(self, tmp_path):
        data = fetch_horizon(_no_boundary(tmp_path))
        assert data["armed"] == 0
        assert data["loops"] == []

    def test_last_sealed_is_json_clean_float(self, tmp_path):
        data = fetch_horizon(_count_vertex(tmp_path, count=3, n_facts=5))
        assert isinstance(data["loops"][0]["last_sealed"], float)
        assert isinstance(data["now"], float)


class TestMeter:
    def test_saturates_not_overflows(self):
        # More unsealed facts than the count still fills, never exceeds width.
        assert _meter(9, 3, width=8) == "▓" * 8
        assert _meter(0, 3, width=8) == "░" * 8
        assert len(_meter(2, 3, width=8)) == 8

    def test_empty_for_no_total(self):
        assert _meter(2, 0) == ""


class TestRegisters:
    def test_no_armed_loops_honest_line(self, tmp_path):
        text = _render(fetch_horizon(_no_boundary(tmp_path)))
        assert "No armed loops" in text

    def test_minimal_is_one_line(self, tmp_path):
        data = fetch_horizon(_count_vertex(tmp_path, count=3, n_facts=5))
        text = _render(data, zoom=Zoom.MINIMAL).rstrip("\n")
        assert "\n" not in text
        assert "1 armed loop" in text and "2 unsealed" in text

    def test_count_row_shows_proximity_and_meter(self, tmp_path):
        data = fetch_horizon(_count_vertex(tmp_path, count=3, n_facts=5))
        text = _render(data)
        assert "2/3" in text
        assert "▓" in text  # the TTY-only proximity meter

    def test_kind_row_has_no_fake_meter(self, tmp_path):
        text = _render(fetch_horizon(_vertex_boundary(tmp_path)))
        assert "waiting on session" in text
        assert "▓" not in text  # kind-based boundary NEVER invents a bar

    def test_never_sealed_wording(self, tmp_path):
        text = _render(fetch_horizon(_count_vertex(tmp_path, count=10, n_facts=4)))
        assert "never sealed" in text

    def test_detailed_shows_conditions(self, tmp_path):
        text = _render(fetch_horizon(_vertex_boundary(tmp_path)), zoom=Zoom.DETAILED)
        assert "status=closed" in text  # payload match condition surfaced

    def test_piped_carries_iso_stamp_and_full_shape(self, tmp_path):
        text = _render(fetch_horizon(_vertex_boundary(tmp_path)), piped=True)
        assert "when session" in text
        assert "2025-01-01" in text  # absolute seal stamp on the agent channel
        assert "vertex" in text  # scope word


def _multi_strata(dir_path, name="ms"):
    """A vertex spanning all three proximity strata, declared out of sort order.

    * ``decision`` every=10, 19 facts → sealed, window 9, ratio .9 (approaching:
      ≥ the palette's critical threshold .85, ▲ ≡ critical)
    * ``thread``   every=4, 5 facts  → sealed, window 1, ratio .25
    * ``note``     when=ping          → kind-based, sealed, window 1
    * ``task``     every=10, 4 facts  → never sealed
    * ``observation``                 → no boundary, omitted

    Expected proximity order: decision, thread (count sealed, ratio desc), note
    (kind sealed), task (never sealed last).
    """
    vp = dir_path / f"{name}.vertex"
    vp.write_text(
        f'name "{name}"\nstore "./{name}.db"\n\nloops {{\n'
        '  task { fold { items "by" "name" }\n    boundary every="10" }\n'
        '  note { fold { items "by" "topic" }\n    boundary when="ping" }\n'
        '  thread { fold { items "by" "name" }\n    boundary every="4" }\n'
        '  decision { fold { items "by" "topic" }\n    boundary every="10" }\n'
        '  ping { fold { items "by" "topic" } }\n'
        '  observation { fold { items "by" "topic" } }\n'
        "}\n"
    )
    prog = load_vertex_program(vp)
    for i in range(19):
        prog.receive(Fact.of("decision", "kyle", ts=_T0 + i, topic=f"d{i}", message="m"))
    for i in range(5):
        prog.receive(Fact.of("thread", "kyle", ts=_T0 + 100 + i, name=f"t{i}"))
    for i in range(4):
        prog.receive(Fact.of("task", "kyle", ts=_T0 + 200 + i, name=f"k{i}"))
    prog.receive(Fact.of("note", "kyle", ts=_T0 + 300, topic="n0", message="m"))
    prog.receive(Fact.of("ping", "kyle", ts=_T0 + 301, topic="p"))  # seals note
    prog.receive(Fact.of("note", "kyle", ts=_T0 + 302, topic="n1", message="m"))
    return vp


class TestProximitySort:
    def test_three_strata_order(self, tmp_path):
        data = fetch_horizon(_multi_strata(tmp_path))
        names = [r["name"] for r in data["loops"]]
        assert names == ["decision", "thread", "note", "task"]
        # never-sealed truly last, whatever its window size
        assert data["loops"][-1]["never_sealed"] is True

    def test_count_stratum_sorts_by_ratio_desc(self, tmp_path):
        data = fetch_horizon(_multi_strata(tmp_path))
        # decision ratio .9 outranks thread ratio .25
        dec = next(r for r in data["loops"] if r["name"] == "decision")
        thr = next(r for r in data["loops"] if r["name"] == "thread")
        assert data["loops"].index(dec) < data["loops"].index(thr)
        assert dec["window_facts"] / dec["count"] == 0.9
        assert thr["window_facts"] / thr["count"] == 0.25

    def test_rerun_is_byte_identical_both_registers(self, tmp_path):
        vp = _multi_strata(tmp_path)
        for piped in (False, True):
            a = _render(fetch_horizon(vp), piped=piped)
            b = _render(fetch_horizon(vp), piped=piped)
            assert a == b  # unchanged store → identical bytes


def _tie(dir_path, name="tie"):
    """Two count loops at the same ratio, declared name-descending.

    ``zeta`` and ``alpha`` both every=2 with 3 facts → window 1, ratio .5.
    Declaration order (zeta, alpha) must win over name order (alpha, zeta).
    """
    vp = dir_path / f"{name}.vertex"
    vp.write_text(
        f'name "{name}"\nstore "./{name}.db"\n\nloops {{\n'
        '  zeta { fold { items "by" "topic" }\n    boundary every="2" }\n'
        '  alpha { fold { items "by" "topic" }\n    boundary every="2" }\n'
        "}\n"
    )
    prog = load_vertex_program(vp)
    for i in range(3):
        prog.receive(Fact.of("zeta", "kyle", ts=_T0 + i, topic=f"z{i}", message="m"))
    for i in range(3):
        prog.receive(Fact.of("alpha", "kyle", ts=_T0 + 10 + i, topic=f"a{i}", message="m"))
    return vp


class TestTieBreak:
    def test_declaration_order_beats_name(self, tmp_path):
        data = fetch_horizon(_tie(tmp_path))
        names = [r["name"] for r in data["loops"]]
        # both ratio .5 → decl order (zeta first), NOT name order (alpha first)
        assert names == ["zeta", "alpha"]


class TestApproachingSignal:
    def test_glyph_tty_word_piped(self, tmp_path):
        # ▲ ≡ critical: fires at the palette's .85 ramp threshold. The TTY
        # gutter carries the glyph; the pipe carries the WORD (G4: pipes carry
        # words, not glyphs) — same signal, register-idiomatic form.
        data = fetch_horizon(_multi_strata(tmp_path))
        tty = _render(data)
        piped = _render(data, piped=True)
        assert "▲" in tty  # decision at ratio .9 approaches
        assert "▲" not in piped
        assert "approaching" in piped

    def test_threshold_matches_meter_critical(self, tmp_path):
        # every=20, 37 facts → seal at 20, window 17 → ratio .85 exactly: the
        # inclusive boundary — glyph and critical ramp flip together.
        data = fetch_horizon(
            _count_vertex(tmp_path, count=20, n_facts=37)
        )
        assert data["loops"][0]["window_facts"] / data["loops"][0]["count"] == 0.85
        assert "▲" in _render(data)
        assert "approaching" in _render(data, piped=True)

    def test_no_signal_below_threshold(self, tmp_path):
        # every=5, 9 facts → sealed, window 4 → ratio .8: warn ramp, NOT
        # approaching (the old lens-local .8 threshold is gone — palette owns
        # the one threshold at critical).
        data = fetch_horizon(_count_vertex(tmp_path, count=5, n_facts=9))
        row = data["loops"][0]
        assert row["never_sealed"] is False
        assert row["window_facts"] / row["count"] == 0.8
        assert "▲" not in _render(data)
        assert "approaching" not in _render(data, piped=True)

    def test_never_sealed_never_approaches(self, tmp_path):
        # every=10, 4 facts → ratio .4, never-sealed
        data = fetch_horizon(_count_vertex(tmp_path, count=10, n_facts=4))
        assert "▲" not in _render(data)
        assert "approaching" not in _render(data, piped=True)

    def test_kind_based_never_approaches(self, tmp_path):
        data = fetch_horizon(_vertex_boundary(tmp_path))
        assert "▲" not in _render(data)
        assert "approaching" not in _render(data, piped=True)


class TestParity:
    def test_register_parity_count(self, tmp_path):
        data = fetch_horizon(_count_vertex(tmp_path, count=3, n_facts=5))
        assert_register_parity(
            horizon_view, data,
            load_bearing=["decision", "2/3", "1 armed", "2 unsealed"],
        )

    def test_register_parity_kind(self, tmp_path):
        data = fetch_horizon(_vertex_boundary(tmp_path))
        assert_register_parity(
            horizon_view, data,
            load_bearing=["session", "1 armed", "1 unsealed"],
        )
