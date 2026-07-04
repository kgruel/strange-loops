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
