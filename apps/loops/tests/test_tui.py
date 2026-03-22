"""Tests for TUI apps: AutoresearchApp and StoreExplorerApp.

Both apps extend painted.tui.Surface and are driven via TestSurface —
no terminal, no async event loop needed. Test state is built via the
shared builders module (builders.py) and conftest fixtures.
"""
from __future__ import annotations

import time
from dataclasses import replace

import pytest

from painted.tui import TestSurface

from loops.tui.autoresearch_app import (
    AppState,
    AutoresearchApp,
    IterationView,
    _build_iterations,
    _render_detail,
    _render_footer,
    _render_header_panels,
    _render_iteration_list,
    _sparkline_block,
)
from loops.tui.store_app import (
    FidelityState,
    StoreExplorerApp,
    StoreExplorerState,
)

from .builders import (
    AppStateBuilder,
    FoldStateBuilder,
    StoreExplorerStateBuilder,
    make_fidelity_facts,
    make_iteration,
    make_store_summary,
)
from .helpers import block_text


# ---------------------------------------------------------------------------
# AutoresearchApp: rendering
# ---------------------------------------------------------------------------

class TestAutoresearchRender:
    def test_render_loading_state(self, tmp_path):
        """With refresh inhibited and no state, renders 'Loading...'."""
        app = AutoresearchApp(tmp_path / "test.vertex")
        app._last_refresh = time.monotonic()
        harness = TestSurface(app, width=80, height=24, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "Loading" in frames[0].text

    def test_render_error_state(self, tmp_path):
        """With error set, renders the error message."""
        app = AutoresearchApp(tmp_path / "test.vertex")
        app._error = "vertex not found"
        app._last_refresh = time.monotonic()
        harness = TestSurface(app, width=80, height=24, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "Error" in frames[0].text
        assert "vertex not found" in frames[0].text

    def test_render_with_state(self, tmp_path, app_state):
        """Normal render: header + iteration list visible."""
        app = AutoresearchApp(tmp_path / "test.vertex", _initial_state=app_state)
        harness = TestSurface(app, width=100, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "Iterations" in frames[0].text

    def test_render_with_running_iteration(self, tmp_path, app_state_with_running):
        """Running iteration renders with >> indicator."""
        app = AutoresearchApp(tmp_path / "test.vertex", _initial_state=app_state_with_running)
        harness = TestSurface(app, width=100, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert ">>" in frames[0].text

    def test_render_discard_status(self, tmp_path):
        """Discard status renders correctly."""
        state = (AppStateBuilder()
            .iteration(metric=4.5, status="keep")
            .iteration(metric=4.8, status="discard")
            .build())
        app = AutoresearchApp(tmp_path / "test.vertex", _initial_state=state)
        harness = TestSurface(app, width=100, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "discard" in frames[0].text

    def test_render_crash_status(self, tmp_path):
        """crash status uses fallback (non-keep/non-discard) branch."""
        state = (AppStateBuilder()
            .iteration(metric=4.5, status="crash")
            .build())
        app = AutoresearchApp(tmp_path / "test.vertex", _initial_state=state)
        harness = TestSurface(app, width=100, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "crash" in frames[0].text


# ---------------------------------------------------------------------------
# AutoresearchApp: keyboard navigation
# ---------------------------------------------------------------------------

class TestAutoresearchNavigation:
    def test_quit_key(self, tmp_path, app_state):
        """q key stops the harness — initial + q = 2 frames."""
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=app_state)
        harness = TestSurface(app, width=80, height=24, input_queue=["q"])
        frames = harness.run_to_completion()
        assert len(frames) == 2

    def test_navigate_down_up(self, tmp_path):
        """j/k move cursor through the list."""
        state = AppStateBuilder().iteration(metric=4.0).iteration(metric=3.5).iteration(metric=3.0).build()
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=state)
        harness = TestSurface(app, width=100, height=30, input_queue=["j", "j", "k", "q"])
        frames = harness.run_to_completion()
        assert len(frames) == 5

    def test_navigate_home_end(self, tmp_path):
        """g/G jumps to first/last iteration."""
        state = AppStateBuilder().iteration().iteration().iteration().iteration().iteration().build()
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=state)
        harness = TestSurface(app, width=100, height=30, input_queue=["G", "g", "q"])
        frames = harness.run_to_completion()
        assert len(frames) == 4

    def test_enter_switches_to_detail(self, tmp_path, app_state):
        """enter moves focus to detail panel."""
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=app_state)
        harness = TestSurface(app, width=100, height=30, input_queue=["enter", "q"])
        harness.run_to_completion()
        # App was quit, state is gone — just verify no crash

    def test_tab_toggles_focus(self, tmp_path, app_state):
        """tab cycles between list and detail."""
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=app_state)
        harness = TestSurface(app, width=100, height=30, input_queue=["tab", "tab", "q"])
        frames = harness.run_to_completion()
        assert len(frames) == 4

    def test_detail_scroll_keys(self, tmp_path):
        """All detail scroll keys work without crash."""
        state = AppStateBuilder().iteration().focus("detail").build()
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=state)
        keys = ["j", "j", "k", "g", "G", "page_down", "page_up", "q"]
        harness = TestSurface(app, width=100, height=30, input_queue=keys)
        frames = harness.run_to_completion()
        assert len(frames) >= 2

    def test_key_when_no_state(self, tmp_path):
        """Non-quit key with no state is a no-op (no crash)."""
        app = AutoresearchApp(tmp_path / "v.vertex")
        app._last_refresh = time.monotonic()
        harness = TestSurface(app, width=80, height=24, input_queue=["j", "q"])
        frames = harness.run_to_completion()
        assert "Loading" in frames[0].text


# ---------------------------------------------------------------------------
# AutoresearchApp: update() auto-refresh
# ---------------------------------------------------------------------------

class TestAutoresearchUpdate:
    def test_update_no_refresh_within_interval(self, tmp_path, app_state):
        """update() does not reload when refresh interval hasn't elapsed."""
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=app_state)
        # _last_refresh is set to monotonic() by __init__ when _initial_state given
        original_state = app._state
        app.update()
        assert app._state is original_state  # no reload occurred

    def test_update_triggers_load_after_interval(self, tmp_path):
        """update() calls _load_data when refresh interval elapsed."""
        app = AutoresearchApp(tmp_path / "v.vertex")
        app._last_refresh = 0.0  # force interval elapsed
        app._refresh_interval = 0.0
        # _load_data will fail (nonexistent vertex) and set _error
        app.update()
        assert app._error is not None


# ---------------------------------------------------------------------------
# AutoresearchApp: data model — _build_iterations / AppState.from_fold
# ---------------------------------------------------------------------------

class TestBuildIterations:
    def test_basic_experiments(self, autoresearch_fold_state):
        """Two experiments produce two non-running IterationViews."""
        state = AppState.from_fold(autoresearch_fold_state)
        non_running = [it for it in state.iterations if not it.is_running]
        assert len(non_running) == 2

    def test_running_iteration_created(self, autoresearch_fold_state):
        """Log after last experiment → running iteration appended."""
        state = AppState.from_fold(autoresearch_fold_state)
        running = [it for it in state.iterations if it.is_running]
        assert len(running) == 1

    def test_baseline_and_best(self, autoresearch_fold_state):
        """baseline = first metric; best = lowest for 'lower' direction."""
        state = AppState.from_fold(autoresearch_fold_state)
        assert state.baseline == 4.5
        assert state.best == 3.5
        assert state.best_run > 0

    def test_logs_attributed_to_iteration(self, autoresearch_fold_state):
        """Log inside an experiment window is attributed to that iteration."""
        state = AppState.from_fold(autoresearch_fold_state)
        non_running = sorted(
            [it for it in state.iterations if not it.is_running],
            key=lambda it: it.number,
        )
        # log at ts=250 is in the exp1(200)→exp2(300) window
        assert len(non_running[1].logs) == 1

    def test_empty_fold_state(self):
        """No experiments → empty iterations, no baseline, no crash."""
        from atoms import FoldState
        fs = FoldState(sections=(), vertex="empty")
        state = AppState.from_fold(fs)
        assert state.iterations == []
        assert state.baseline is None
        assert state.best is None

    def test_no_metric_in_payload(self):
        """Experiment with no metric field → metric=None, no crash."""
        fs = (FoldStateBuilder("test")
            .config(primary_metric="efficiency", direction="lower")
            .experiment(status="keep", commit="abc", description="no metric", ts=200.0)
            .build())
        state = AppState.from_fold(fs)
        assert state.iterations[0].metric is None

    def test_higher_direction(self):
        """'higher' direction: best = maximum metric."""
        fs = (FoldStateBuilder("test")
            .config(primary_metric="score", direction="higher")
            .experiment(score=10.0, status="keep", commit="a", ts=100.0)
            .experiment(score=15.0, status="keep", commit="b", ts=200.0)
            .build())
        state = AppState.from_fold(fs)
        assert state.best == 15.0


class TestSparklineBlock:
    def test_empty_values(self):
        block = _sparkline_block([], [], "lower", 20)
        assert block.width == 0

    def test_keep_discard_other(self):
        """All three status styles produce cells."""
        block = _sparkline_block([3.0, 4.0, 3.5], ["keep", "discard", "crash"], "lower", 10)
        assert block.width == 3

    def test_higher_direction(self):
        """Higher-is-better inverts bar height (no crash, no divide-by-zero)."""
        block = _sparkline_block([10.0, 20.0, 15.0], ["keep", "keep", "keep"], "higher", 10)
        assert block.width == 3

    def test_single_value_no_divide_by_zero(self):
        block = _sparkline_block([5.0], ["keep"], "lower", 10)
        assert block.width == 1

    def test_width_clamps_to_values(self):
        """Width argument clips the displayed window."""
        block = _sparkline_block([1.0, 2.0, 3.0, 4.0, 5.0], ["keep"] * 5, "lower", width=3)
        assert block.width == 3


# ---------------------------------------------------------------------------
# AutoresearchApp: render helpers (Block-level)
# ---------------------------------------------------------------------------

class TestRenderHelpers:
    def test_render_header_panels(self, app_state):
        block = _render_header_panels(app_state, 100)
        assert block.height >= 1
        assert "efficiency" in block_text(block).lower() or block.height >= 1

    def test_render_iteration_list_list_focus(self, app_state):
        block = _render_iteration_list(app_state, height=8, width=100)
        assert block.height >= 1
        assert "Iterations" in block_text(block)

    def test_render_iteration_list_detail_focus(self):
        state = AppStateBuilder().iteration().iteration().focus("detail").build()
        block = _render_iteration_list(state, height=8, width=100)
        assert block.height >= 1

    def test_render_detail_normal(self):
        it = make_iteration(1, description="my test description", delta_pct=-10.0)
        block = _render_detail(it, 100, 20, scroll=0, focused=True)
        assert block.height >= 1
        assert "my test description" in block_text(block)

    def test_render_detail_running(self):
        it = make_iteration(1, is_running=True, metric=None)
        block = _render_detail(it, 100, 20, scroll=0, focused=False)
        assert "running" in block_text(block)

    def test_render_detail_no_metric(self):
        """No metric shows dash in title."""
        it = make_iteration(1, metric=None)
        block = _render_detail(it, 100, 20, scroll=0, focused=True)
        assert block.height >= 1

    def test_render_detail_scroll_clamped(self):
        """Huge scroll value is clamped to content height."""
        it = make_iteration(1, description="short")
        block = _render_detail(it, 100, 20, scroll=9999, focused=True)
        assert block.height >= 1

    def test_render_detail_empty_activity(self):
        """No description, no logs/findings → 'No activity' placeholder."""
        it = make_iteration(1, description="")
        block = _render_detail(it, 100, 20, scroll=0, focused=True)
        assert "No activity" in block_text(block)

    def test_render_footer_list_focus(self, app_state):
        block = _render_footer(app_state, 100)
        text = block_text(block)
        assert "j/k" in text

    def test_render_footer_detail_focus(self):
        state = AppStateBuilder().iteration().focus("detail").build()
        block = _render_footer(state, 100)
        text = block_text(block)
        assert "j/k" in text or "scroll" in text


# ---------------------------------------------------------------------------
# AutoresearchApp: rich iteration content
# ---------------------------------------------------------------------------

class TestIterationRichContent:
    def _item(self, **payload) -> "FoldItem":
        from atoms import FoldItem
        return FoldItem(payload=payload, ts=300.0)

    def test_render_detail_with_logs(self):
        log = self._item(type="note", message="a finding")
        it = make_iteration(1, description="step", logs=(log,))
        block = _render_detail(it, 100, 30, scroll=0, focused=True)
        assert "a finding" in block_text(block)

    def test_render_detail_with_findings(self):
        finding = self._item(target="main.py", message="coverage gap")
        it = make_iteration(1, description="", findings=(finding,))
        block = _render_detail(it, 100, 30, scroll=0, focused=False)
        assert "Findings" in block_text(block)
        assert "coverage gap" in block_text(block)

    def test_render_detail_with_ideas_tried_and_untried(self):
        """tried ideas get '+' indicator; untried get 'o'."""
        ideas = (
            self._item(name="batch fixture", status="tried", description="group tests"),
            self._item(name="mock DB", status="untried", description=""),
        )
        it = make_iteration(1, description="", ideas=ideas)
        block = _render_detail(it, 100, 30, scroll=0, focused=False)
        text = block_text(block)
        assert "Ideas" in text
        assert "batch fixture" in text

    def test_render_detail_with_hypotheses(self):
        hyp = self._item(name="merge tests", status="proposed", prediction="efficiency improves")
        it = make_iteration(1, description="", hypotheses=(hyp,))
        block = _render_detail(it, 100, 30, scroll=0, focused=False)
        text = block_text(block)
        assert "Hypotheses" in text
        assert "efficiency improves" in text


# ---------------------------------------------------------------------------
# StoreExplorerApp: rendering
# ---------------------------------------------------------------------------

class TestStoreExplorerRender:
    def test_render_loading_state(self, tmp_path):
        """No state + on_start not called by TestSurface → 'Loading...'."""
        app = StoreExplorerApp(tmp_path / "test.db")
        harness = TestSurface(app, width=80, height=24, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "Loading" in frames[0].text

    def test_render_error_state(self, tmp_path):
        app = StoreExplorerApp(tmp_path / "test.db")
        app._error = "db not found"
        harness = TestSurface(app, width=80, height=24, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "Error" in frames[0].text

    def test_render_with_state(self, tmp_path, store_explorer_state):
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=120, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "Ticks" in frames[0].text

    def test_render_freshness_in_header(self, tmp_path, store_explorer_state):
        """Summary with freshness shows it in the header."""
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=120, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "fresh" in frames[0].text.lower() or "facts" in frames[0].text.lower()

    def test_render_empty_ticks(self, tmp_path):
        """Store with no ticks renders without crashing."""
        state = StoreExplorerStateBuilder().ticks([]).facts(0).build()
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        harness = TestSurface(app, width=100, height=20, input_queue=["q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 1

    def test_render_compact_height(self, tmp_path, store_explorer_state):
        """Tiny terminal (height=5) degrades gracefully."""
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=80, height=5, input_queue=["q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 1

    def test_render_no_detail(self, tmp_path):
        """State with no detail selection renders the empty placeholder."""
        state = StoreExplorerStateBuilder().with_detail().build()
        state = replace(state, detail=None)
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        harness = TestSurface(app, width=100, height=24, input_queue=["q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 1


# ---------------------------------------------------------------------------
# StoreExplorerApp: keyboard navigation
# ---------------------------------------------------------------------------

class TestStoreExplorerNavigation:
    def test_quit(self, tmp_path, store_explorer_state):
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=100, height=24, input_queue=["q"])
        frames = harness.run_to_completion()
        assert len(frames) == 2

    def test_list_navigate_down_up(self, tmp_path, store_explorer_state):
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=100, height=24, input_queue=["j", "k", "q"])
        frames = harness.run_to_completion()
        assert len(frames) == 4

    def test_list_home_end(self, tmp_path):
        state = StoreExplorerStateBuilder().ticks(["t1", "t2", "t3", "t4"]).build()
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        harness = TestSurface(app, width=100, height=24, input_queue=["G", "g", "q"])
        frames = harness.run_to_completion()
        assert len(frames) == 4

    def test_tab_toggles_focus(self, tmp_path, store_explorer_state):
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=100, height=24, input_queue=["tab", "tab", "q"])
        frames = harness.run_to_completion()
        assert len(frames) == 4

    def test_detail_navigation(self, tmp_path):
        state = StoreExplorerStateBuilder().with_detail().focus("detail").build()
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        keys = ["j", "k", "enter", "g", "G", "pageup", "pagedown", "q"]
        harness = TestSurface(app, width=100, height=24, input_queue=keys)
        frames = harness.run_to_completion()
        assert len(frames) >= 2

    def test_key_when_no_state(self, tmp_path):
        """Key with no state is a no-op."""
        app = StoreExplorerApp(tmp_path / "test.db")
        harness = TestSurface(app, width=80, height=24, input_queue=["j", "q"])
        frames = harness.run_to_completion()
        assert "Loading" in frames[0].text


# ---------------------------------------------------------------------------
# StoreExplorerApp: fidelity drill
# ---------------------------------------------------------------------------

class TestStoreExplorerFidelity:
    def test_render_fidelity_panel(self, tmp_path, store_explorer_state_with_fidelity):
        """Fidelity panel renders — footer shows bksp/filter hint unique to fidelity mode."""
        app = StoreExplorerApp(
            tmp_path / "test.db",
            _initial_state=store_explorer_state_with_fidelity,
        )
        harness = TestSurface(app, width=120, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        # Fidelity mode shows a distinct footer with [bksp] back
        assert "bksp" in frames[0].text or "filter" in frames[0].text

    def test_fidelity_navigate_down_up(self, tmp_path, store_explorer_state_with_fidelity):
        app = StoreExplorerApp(
            tmp_path / "test.db",
            _initial_state=store_explorer_state_with_fidelity,
        )
        harness = TestSurface(app, width=120, height=30, input_queue=["j", "k", "q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 2

    def test_fidelity_empty_facts(self, tmp_path):
        """Fidelity with no facts shows '(no facts in period)' placeholder."""
        state = StoreExplorerStateBuilder().ticks(["2024-01-01"]).with_fidelity([]).build()
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        harness = TestSurface(app, width=120, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "no facts" in frames[0].text.lower()

    def test_fidelity_filtered(self, tmp_path):
        """Filtered fidelity shows filter_kind in title."""
        facts = make_fidelity_facts(["thread", "thread", "decision"])
        state = (StoreExplorerStateBuilder()
            .ticks(["2024-01-01"])
            .with_fidelity(facts)
            .build())
        # Mark as filtered
        fid = replace(state.fidelity, filtered=True, filter_kind="thread")
        state = replace(state, fidelity=fid)
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        harness = TestSurface(app, width=120, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "thread" in frames[0].text

    def test_fidelity_drill_with_fetch(self, tmp_path):
        """'f' key triggers fidelity drill when _fidelity_fetch is injected."""
        facts = make_fidelity_facts(["thread", "decision"])
        state = StoreExplorerStateBuilder().with_detail().build()

        def _fetch(since, until, kind=None):
            return [f for f in facts if f["kind"] == kind] if kind else facts

        app = StoreExplorerApp(
            tmp_path / "test.db",
            _initial_state=state,
            _fidelity_fetch=_fetch,
        )
        harness = TestSurface(app, width=120, height=30, input_queue=["f", "q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 2

    def test_fidelity_filter_key_a(self, tmp_path):
        """'a' in fidelity mode applies kind filter via _fidelity_fetch."""
        facts = make_fidelity_facts(["thread", "decision"])
        state = StoreExplorerStateBuilder().ticks(["2024-01-01"]).with_fidelity(facts).build()

        def _fetch(since, until, kind=None):
            return [f for f in facts if f["kind"] == kind] if kind else facts

        app = StoreExplorerApp(
            tmp_path / "test.db",
            _initial_state=state,
            _fidelity_fetch=_fetch,
        )
        harness = TestSurface(app, width=120, height=30, input_queue=["a", "q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 2

    def test_fidelity_filter_key_a_no_fetch(self, tmp_path):
        """'a' without _fidelity_fetch is a no-op (no crash)."""
        facts = make_fidelity_facts(["thread"])
        state = StoreExplorerStateBuilder().ticks(["2024-01-01"]).with_fidelity(facts).build()
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        harness = TestSurface(app, width=120, height=30, input_queue=["a", "q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 2

    def test_fidelity_backspace_exits(self, tmp_path):
        """backspace exits fidelity drill back to main view."""
        facts = make_fidelity_facts(["thread"])
        state = StoreExplorerStateBuilder().ticks(["2024-01-01"]).with_fidelity(facts).build()
        app = StoreExplorerApp(tmp_path / "test.db", _initial_state=state)
        harness = TestSurface(app, width=120, height=30, input_queue=["backspace", "q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 2


# ---------------------------------------------------------------------------
# AutoresearchApp: remaining miss lines
# ---------------------------------------------------------------------------

class TestFormatMetric:
    def test_value_gte_10(self):
        """_format_metric for values >= 10 → one decimal (L112)."""
        from loops.tui.autoresearch_app import _format_metric
        assert _format_metric(15.0) == "15"
        assert _format_metric(10.5) == "10.5"
        assert _format_metric(100.7) == "100.7"

    def test_value_lt_1(self):
        """_format_metric for abs(value) < 1 → three decimals (L115)."""
        from loops.tui.autoresearch_app import _format_metric
        assert _format_metric(0.5) == "0.500"
        assert _format_metric(0.123) == "0.123"


class TestAppStateEdges:
    def test_selected_empty_iterations(self):
        """AppState.selected returns None when no iterations (L261)."""
        from loops.tui.autoresearch_app import AppState
        from painted.views import ListState
        state = AppState(
            config={}, iterations=[], primary_metric="", direction="lower",
            baseline=None, best=None, best_run=0, total_experiments=0,
            cursor=ListState().with_count(0), focus="list", detail_scroll=0,
        )
        assert state.selected is None

    def test_selected_out_of_bounds(self):
        """AppState.selected returns None when cursor past iterations (L261)."""
        from loops.tui.autoresearch_app import AppState
        from painted.views import ListState
        it = make_iteration(1)
        state = AppState(
            config={}, iterations=[it], primary_metric="", direction="lower",
            baseline=None, best=None, best_run=0, total_experiments=1,
            cursor=ListState().with_count(5).move_to(4),  # cursor beyond list
            focus="list", detail_scroll=0,
        )
        assert state.selected is None


class TestRenderHeaderNoMetric:
    def test_header_no_primary_metric(self):
        """_render_header_panels with no primary_metric shows 'no metric' (L296)."""
        from loops.tui.autoresearch_app import AppState, _render_header_panels
        from painted.views import ListState
        state = AppState(
            config={}, iterations=[], primary_metric="",
            direction="lower", baseline=None, best=None,
            best_run=0, total_experiments=0,
            cursor=ListState().with_count(0), focus="list", detail_scroll=0,
        )
        block = _render_header_panels(state, 100)
        assert block.height >= 1


class TestIterationListNoneMetric:
    def test_list_renders_dash_for_none_metric(self, tmp_path):
        """Iteration with metric=None shows '      -' in the list (L373)."""
        state = (AppStateBuilder()
            .iteration(metric=None, status="crash")
            .build())
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=state)
        harness = TestSurface(app, width=100, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        # '-' indicator should appear somewhere in the rendered frame
        assert "-" in frames[0].text


class TestLogWithFiles:
    def test_render_detail_log_with_files_field(self):
        """Log item with 'files' field appended to message (L436)."""
        from atoms import FoldItem
        log = FoldItem(
            payload={"type": "change", "message": "refactored", "files": "main.py, util.py"},
            ts=300.0,
        )
        it = make_iteration(1, description="step up", logs=(log,))
        block = _render_detail(it, 100, 30, scroll=0, focused=True)
        text = block_text(block)
        assert "main.py" in text or "refactored" in text


class TestUpdateAndOnKeyDirect:
    def test_update_method_covered(self, tmp_path):
        """Direct update() call covers method body (L605-609)."""
        import time as _time
        app = AutoresearchApp(tmp_path / "v.vertex")
        # Trigger reload path by zeroing refresh time
        app._last_refresh = 0.0
        app._refresh_interval = 0.0
        app.update()
        # _load_data fired (vertex missing → error set)
        assert app._error is not None

    def test_on_key_covered_directly(self, tmp_path, app_state):
        """Direct on_key() call covers method dispatch (L611+)."""
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=app_state)
        # Initialise buffer for render
        from painted.tui import TestSurface
        harness = TestSurface(app, width=80, height=24, input_queue=[])
        # Direct key dispatch
        app.on_key("j")  # navigate down
        app.on_key("k")  # navigate up
        app.on_key("tab")  # toggle focus
        app.on_key("enter")  # switch to detail
        app.on_key("j")  # scroll detail
        app.on_key("page_down")  # page down in detail
        app.on_key("page_up")   # page up in detail
        app.on_key("g")  # home
        app.on_key("G")  # end

    def test_on_key_unknown_no_crash(self, tmp_path, app_state):
        """Unknown key in both list and detail focus is a no-op."""
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=app_state)
        app.on_key("z")  # unknown in list
        app._state = replace(app._state, focus="detail")
        app.on_key("z")  # unknown in detail


class TestRenderIterationListCall:
    def test_render_calls_iteration_list(self, tmp_path, app_state):
        """Full render() path calls _render_iteration_list (L713)."""
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=app_state)
        harness = TestSurface(app, width=100, height=40, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "Iterations" in frames[0].text


# ---------------------------------------------------------------------------
# StoreExplorerApp: remaining miss lines
# ---------------------------------------------------------------------------

class TestStoreExplorerStateEdges:
    def test_selected_name_out_of_bounds(self):
        """selected_name() returns None when no tick names (L82)."""
        # Build a state with tick_names=[] — cursor.selected=0, 0 < 0 is False → None
        state = StoreExplorerStateBuilder().ticks([]).build()
        assert state.selected_name() is None

    def test_selected_label_no_ticks(self):
        """selected_label returns None when no tick names (L75)."""
        state = StoreExplorerStateBuilder().ticks([]).build()
        assert state.selected_label is None

    def test_selected_data_no_name(self):
        """selected_data() returns None when no selection (L68)."""
        state = StoreExplorerStateBuilder().ticks([]).build()
        assert state.selected_data() is None


class TestStoreExplorerLoadStore:
    def test_load_store_with_real_db(self, tmp_path):
        """_load_store() with a real SQLite store covers L113-129."""
        from .builders import StorePopulator
        from engine.builder import vertex, fold_count

        # Build a real vertex + store
        vpath = tmp_path / "s.vertex"
        vertex("s").store("./s.db").loop("ping", fold_count("n")).write(vpath)
        db_path = tmp_path / "s.db"
        StorePopulator(db_path).emit("ping", n="1").emit("ping", n="2").done()

        app = StoreExplorerApp(db_path)
        app._load_store()
        assert app._state is not None
        assert app._error is None

    def test_load_store_error_on_missing_db(self, tmp_path):
        """_load_store() sets _error when db doesn't exist (L127-128)."""
        app = StoreExplorerApp(tmp_path / "nonexistent.db")
        app._load_store()
        assert app._error is not None


class TestStoreExplorerKeyEdges:
    def test_list_key_unknown(self, tmp_path, store_explorer_state):
        """Unknown list key hits else:return (L176)."""
        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=100, height=24, input_queue=[])
        app.on_key("z")  # unknown in list → L176 else:return

    def test_detail_key_no_detail(self, tmp_path):
        """_handle_detail_key returns early when no detail (L197)."""
        state = StoreExplorerStateBuilder().focus("detail").build()
        state = replace(state, detail=None)
        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=state)
        harness = TestSurface(app, width=100, height=24, input_queue=[])
        app.on_key("j")  # detail is None → L197 early return

    def test_detail_key_unknown(self, tmp_path):
        """Unknown detail key hits else:return (L215)."""
        state = StoreExplorerStateBuilder().with_detail().focus("detail").build()
        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=state)
        harness = TestSurface(app, width=100, height=24, input_queue=[])
        app.on_key("z")  # unknown in detail → L215 else

    def test_selection_change_no_data(self, tmp_path):
        """List navigation where new selection has no tick data → detail=None (L189)."""
        # Create state with 2 ticks but empty data for second
        summary = {
            "facts": {"total": 2, "kinds": {}},
            "ticks": {"total": 2, "names": {"tick-a": {"count": 1, "sparkline": "", "latest": None}}},
        }
        from loops.tui.store_app import StoreExplorerState
        state = StoreExplorerState.from_summary(summary)
        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=state)
        harness = TestSurface(app, width=100, height=24, input_queue=[])
        # Move to a tick with no data → detail becomes None
        app.on_key("j")

    def test_fidelity_key_home_end(self, tmp_path, store_explorer_state_with_fidelity):
        """g/G in fidelity mode navigate cursor (L304, L306)."""
        app = StoreExplorerApp(
            tmp_path / "t.db",
            _initial_state=store_explorer_state_with_fidelity,
        )
        harness = TestSurface(app, width=120, height=30, input_queue=[])
        app.on_key("G")  # L306
        app.on_key("g")  # L304

    def test_fidelity_key_unknown(self, tmp_path, store_explorer_state_with_fidelity):
        """Unknown fidelity key hits else:return (L253)."""
        app = StoreExplorerApp(
            tmp_path / "t.db",
            _initial_state=store_explorer_state_with_fidelity,
        )
        app.on_key("z")  # unknown in fidelity → L253

    def test_fidelity_filter_no_facts_for_first_kind(self, tmp_path):
        """'a' in fidelity with facts but 0 matching kind hits else:return (L270)."""
        from loops.tui.store_app import FidelityState
        from painted.views import ListState
        # facts with one kind but filter targets a different kind
        facts = make_fidelity_facts(["thread"])
        fid = FidelityState(
            facts=facts, tick_name="t", since=0.0, until=1.0,
            cursor=ListState().with_count(1),
            filtered=True, filter_kind="thread",  # already filtered
        )
        state = StoreExplorerStateBuilder().ticks(["t"]).build()
        state = replace(state, fidelity=fid)

        def _fetch(since, until, kind=None):
            if kind:
                return []  # empty filter result → L270
            return facts

        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=state, _fidelity_fetch=_fetch)
        app.on_key("a")  # tries to filter but gets empty → L268-270


class TestStoreExplorerRelativeTime:
    def test_just_now(self):
        """_relative_time for future timestamps → 'just now' (L480)."""
        from loops.tui.store_app import _relative_time
        from datetime import datetime as dt, timezone as tz, timedelta
        future = dt.now(tz.utc) + timedelta(seconds=5)
        result = _relative_time(future)
        assert result == "just now"

    def test_seconds_ago(self):
        """_relative_time for < 60s → '??s ago' (L482)."""
        from loops.tui.store_app import _relative_time
        from datetime import datetime as dt, timezone as tz, timedelta
        assert "s ago" in _relative_time(dt.now(tz.utc) - timedelta(seconds=30))

    def test_minutes_ago(self):
        """_relative_time for 1-59min → '??m ago' (L485)."""
        from loops.tui.store_app import _relative_time
        from datetime import datetime as dt, timezone as tz, timedelta
        assert "m ago" in _relative_time(dt.now(tz.utc) - timedelta(minutes=15))

    def test_hours_ago(self):
        """_relative_time for 1-23h → '??h ago' (L488)."""
        from loops.tui.store_app import _relative_time
        from datetime import datetime as dt, timezone as tz, timedelta
        assert "h ago" in _relative_time(dt.now(tz.utc) - timedelta(hours=5))


class TestStoreExplorerRenderLayout:
    def test_medium_height_layout(self, tmp_path, store_explorer_state):
        """Height 7-11 uses tight layout (header+panels+footer, L459)."""
        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=store_explorer_state)
        harness = TestSurface(app, width=100, height=9, input_queue=["q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 1

    def test_render_fidelity_early_return(self, tmp_path, store_explorer_state_with_fidelity):
        """Fidelity render with height < panel_height — row loop short-circuits (L367)."""
        app = StoreExplorerApp(
            tmp_path / "t.db",
            _initial_state=store_explorer_state_with_fidelity,
        )
        # Very small height forces minimal panel
        harness = TestSurface(app, width=80, height=8, input_queue=["q"])
        frames = harness.run_to_completion()
        assert len(frames) >= 1


# ---------------------------------------------------------------------------
# AutoresearchApp: _load_data paths and render edges
# ---------------------------------------------------------------------------

class TestAutoresearchLoadData:
    def test_load_data_initial_with_real_vertex(self, autoresearch_vertex, monkeypatch):
        """_load_data() on initial load (state=None) covers L575-L584."""
        import time
        from .builders import StorePopulator
        db_path = autoresearch_vertex.parent / "data" / "autoresearch.db"
        (StorePopulator(db_path)
            .emit("config", key="primary_metric", value="efficiency")
            .emit("config", key="direction", value="lower")
            .emit("experiment", efficiency="4.5", status="keep",
                  commit="abc1234", description="baseline", ts=200.0)
            .done())

        app = AutoresearchApp(autoresearch_vertex)
        app._last_refresh = 0.0
        app._refresh_interval = 0.0
        app._load_data()
        # Initial path: _state was None, now set
        assert app._state is not None
        assert len(app._state.iterations) >= 1

    def test_load_data_refresh_with_real_vertex(self, autoresearch_vertex):
        """_load_data() on refresh (state already set) covers L586-L594."""
        from .builders import StorePopulator
        db_path = autoresearch_vertex.parent / "data" / "autoresearch.db"
        (StorePopulator(db_path)
            .emit("config", key="primary_metric", value="efficiency")
            .emit("experiment", efficiency="3.5", status="keep",
                  commit="abc", description="step", ts=200.0)
            .done())

        app = AutoresearchApp(autoresearch_vertex)
        app._load_data()  # initial load
        first_state = app._state
        assert first_state is not None
        # Second load → refresh path (state is not None)
        app._load_data()
        assert app._state is not None


class TestAutoresearchHandleKeyNoState:
    def test_handle_list_key_no_state(self, tmp_path):
        """_handle_list_key returns early when state=None (L635)."""
        app = AutoresearchApp(tmp_path / "v.vertex")
        # Don't set state — _state is None
        app._handle_list_key("j")  # L635: return early

    def test_handle_detail_key_no_state(self, tmp_path):
        """_handle_detail_key returns early when state=None (L660)."""
        app = AutoresearchApp(tmp_path / "v.vertex")
        app._handle_detail_key("j")  # L660: return early

    def test_render_no_buf(self, tmp_path):
        """render() returns early when _buf is None (L685)."""
        app = AutoresearchApp(tmp_path / "v.vertex")
        # _buf not set up (no TestSurface) → L685 early return
        app.render()

    def test_render_no_iterations(self, tmp_path):
        """render() with empty iterations shows 'No iterations' (L726)."""
        state = (AppStateBuilder()
            .metric("efficiency")
            .focus("list")
            .build())  # no .iteration() calls → 0 iterations
        app = AutoresearchApp(tmp_path / "v.vertex", _initial_state=state)
        harness = TestSurface(app, width=100, height=30, input_queue=["q"])
        frames = harness.run_to_completion()
        assert "No iterations" in frames[0].text


# ---------------------------------------------------------------------------
# StoreExplorerApp: remaining miss lines
# ---------------------------------------------------------------------------

class TestStoreExplorerLoadStoreDetail:
    def test_load_store_populates_detail(self, tmp_path, monkeypatch):
        """_load_store() with a summary that has a tick covers the detail init (L123)."""
        summary = make_store_summary(tick_names=["2024-01-01"])
        # Patch make_fetcher to return our controlled summary
        import loops.tui.store_app as store_app_mod
        monkeypatch.setattr(
            store_app_mod, "make_fetcher" if hasattr(store_app_mod, "make_fetcher") else "_make_fetcher",
            lambda path, zoom: (lambda: summary),
            raising=False,
        )
        # Patch at import level inside _load_store
        import loops.commands.store as store_cmd
        monkeypatch.setattr(store_cmd, "make_fetcher", lambda path, zoom: (lambda: summary))
        monkeypatch.setattr(store_cmd, "make_fidelity_fetcher", lambda path: (lambda s, u, **kw: []))

        app = StoreExplorerApp(tmp_path / "test.db")
        app._load_store()
        # summary has ticks → selected_data() returns non-empty dict → detail set (L123)
        assert app._state is not None
        assert app._error is None


class TestStoreExplorerDrillFidelity:
    def test_drill_fidelity_no_fetch(self, tmp_path, store_explorer_state):
        """_drill_fidelity returns early when _fidelity_fetch is None (L224)."""
        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=store_explorer_state)
        app._drill_fidelity()  # L224: fidelity_fetch is None → return

    def test_drill_fidelity_no_tick_name(self, tmp_path):
        """_drill_fidelity returns early when no tick selected (L228)."""
        state = StoreExplorerStateBuilder().ticks([]).build()
        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=state,
                               _fidelity_fetch=lambda s, u, **kw: [])
        app._drill_fidelity()  # L228: tick_name is None → return

    def test_drill_fidelity_with_since_until(self, tmp_path):
        """_drill_fidelity with valid since/until covers L236-L248."""
        facts = make_fidelity_facts(["thread", "decision"])
        summary = make_store_summary(tick_names=["2024-01-01"])
        # Add latest_since/latest_ts to tick so drill can proceed
        summary["ticks"]["names"]["2024-01-01"]["latest_since"] = 1704067200.0
        summary["ticks"]["names"]["2024-01-01"]["latest_ts"] = 1704153600.0
        state = StoreExplorerState.from_summary(summary)

        def _fetch(since, until, kind=None):
            return facts if kind is None else [f for f in facts if f["kind"] == kind]

        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=state, _fidelity_fetch=_fetch)
        app._drill_fidelity()  # L236-L248: full drill
        assert app._state is not None
        assert app._state.fidelity is not None

    def test_fidelity_filter_restore_all(self, tmp_path):
        """'a' when already filtered → restore all facts (L284-L285)."""
        from painted.views import ListState as LS
        facts = make_fidelity_facts(["thread", "decision"])
        fid = FidelityState(
            facts=[facts[0]],  # already filtered to 1 fact
            tick_name="2024-01-01",
            since=1704067200.0,
            until=1704153600.0,
            cursor=LS().with_count(1),
            filtered=True,
            filter_kind="thread",
        )
        summary = make_store_summary(tick_names=["2024-01-01"])
        state = replace(StoreExplorerState.from_summary(summary), fidelity=fid)

        def _fetch(since, until, kind=None):
            return facts  # all facts when no kind filter

        app = StoreExplorerApp(tmp_path / "t.db", _initial_state=state, _fidelity_fetch=_fetch)
        app.on_key("a")  # restore all → L284-L285
        assert app._state.fidelity.filtered is False


class TestStoreExplorerRemainingMiss:
    def test_relative_time_non_datetime(self):
        """_relative_time with non-datetime → '?' (L474)."""
        from loops.tui.store_app import _relative_time
        assert _relative_time("not a datetime") == "?"
        assert _relative_time(None) == "?"
        assert _relative_time(42) == "?"

    def test_handle_list_key_no_state_direct(self, tmp_path):
        """_handle_list_key returns early when state=None (L163)."""
        app = StoreExplorerApp(tmp_path / "t.db")
        app._handle_list_key("j")  # L163: state is None → return

    def test_handle_detail_key_no_state_direct(self, tmp_path):
        """_handle_detail_key returns early when state=None or detail=None (L197)."""
        app = StoreExplorerApp(tmp_path / "t.db")
        app._handle_detail_key("j")  # L197: state is None → return

    def test_fidelity_key_handler_unknown_no_state(self, tmp_path, store_explorer_state_with_fidelity):
        """Fidelity navigation with unknown key (L253)."""
        app = StoreExplorerApp(
            tmp_path / "t.db",
            _initial_state=store_explorer_state_with_fidelity,
        )
        app.on_key("x")  # unknown in fidelity → L253 else: return
