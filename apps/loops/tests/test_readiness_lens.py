"""Tests for the readiness lens — classification + rendering."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atoms import FoldItem, FoldSection, FoldState
from painted import Zoom

from .helpers import block_to_text

# readiness.py lives under experiments/config-reference/lenses/
_CONFIG_LENSES = str(Path(__file__).resolve().parents[3] / "experiments" / "config-reference" / "lenses")
if _CONFIG_LENSES not in sys.path:
    sys.path.insert(0, _CONFIG_LENSES)

from readiness import _classify, fold_view  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(payload: dict, **kw) -> FoldItem:
    return FoldItem(payload=payload, **kw)


def _state(*sections: FoldSection, vertex: str = "test") -> FoldState:
    return FoldState(sections=sections, vertex=vertex)


def _thread_section(*items: FoldItem) -> FoldSection:
    return FoldSection(kind="thread", fold_type="by", key_field="name", items=items)


def _task_section(*items: FoldItem) -> FoldSection:
    return FoldSection(kind="task", fold_type="by", key_field="name", items=items)


def _decision_section(*items: FoldItem) -> FoldSection:
    return FoldSection(kind="decision", fold_type="by", key_field="topic", items=items)


def _render_text(data: FoldState, zoom: Zoom = Zoom.SUMMARY) -> str:
    block = fold_view(data, zoom, width=None)
    return block_to_text(block)


# ---------------------------------------------------------------------------
# Classification unit tests
# ---------------------------------------------------------------------------

class TestClassify:
    def test_resolved_returns_none(self):
        for status in ("resolved", "completed", "done", "closed", "dissolved", "shipped"):
            item = _item({"name": "x", "status": status})
            assert _classify(item) is None, f"{status} should be closed"

    def test_parked(self):
        assert _classify(_item({"name": "x", "status": "parked"})) == "parked"
        assert _classify(_item({"name": "x", "message": "deferred to later"})) == "parked"
        assert _classify(_item({"name": "x", "message": "not now"})) == "parked"

    def test_ready(self):
        assert _classify(_item({"name": "x", "message": "Design complete, ready to implement"})) == "ready"
        assert _classify(_item({"name": "x", "status": "approved"})) == "ready"
        assert _classify(_item({"name": "x", "message": "Implementation plan drafted"})) == "ready"

    def test_resolution(self):
        assert _classify(_item({"name": "x", "status": "needs-resolution"})) == "resolution"
        assert _classify(_item({"name": "x", "message": "Open question: which approach?"})) == "resolution"
        assert _classify(_item({"name": "x", "message": "Blocker: waiting on API"})) == "resolution"

    def test_design_is_default(self):
        assert _classify(_item({"name": "x", "status": "open"})) == "design"
        assert _classify(_item({"name": "x", "status": "exploring"})) == "design"
        assert _classify(_item({"name": "x"})) == "design"


# ---------------------------------------------------------------------------
# Rendering tests
# ---------------------------------------------------------------------------

class TestFoldView:
    def test_empty_fold(self):
        data = _state()
        text = _render_text(data)
        assert "nothing tracked" in text

    def test_empty_after_all_resolved(self):
        data = _state(
            _thread_section(
                _item({"name": "done-thread", "status": "resolved"}),
            ),
        )
        text = _render_text(data)
        assert "nothing tracked" in text

    def test_minimal_counts(self):
        data = _state(
            _thread_section(
                _item({"name": "a", "message": "Design complete"}),
                _item({"name": "b", "status": "needs-resolution"}),
                _item({"name": "c", "status": "open"}),
                _item({"name": "d", "status": "parked"}),
            ),
        )
        text = _render_text(data, Zoom.MINIMAL)
        assert "1 ready to build" in text
        assert "1 needs resolution" in text
        assert "1 design" in text
        assert "1 parked" in text

    def test_summary_shows_names(self):
        data = _state(
            _thread_section(
                _item({"name": "siftd-redesign", "message": "Design complete, 5-phase plan"}),
                _item({"name": "observer-disco", "status": "needs-resolution", "message": "Where does observer name live?"}),
            ),
        )
        text = _render_text(data, Zoom.SUMMARY)
        assert "siftd-redesign" in text
        assert "observer-disco" in text
        assert "Ready to build" in text
        assert "Needs resolution" in text

    def test_detailed_shows_description(self):
        data = _state(
            _thread_section(
                _item({"name": "thread-a", "status": "open", "message": "Exploring three approaches to vertex routing"}),
            ),
        )
        text = _render_text(data, Zoom.DETAILED)
        assert "open threads, not yet converged" in text
        assert "thread-a" in text

    def test_full_shows_timestamps_and_observer(self):
        data = _state(
            _thread_section(
                _item({"name": "t1", "status": "open"}, ts=1736942400.0, observer="kyle"),
            ),
        )
        text = _render_text(data, Zoom.FULL)
        assert "kyle" in text
        assert "2025-01-15" in text

    def test_full_shows_decisions(self):
        data = _state(
            _thread_section(
                _item({"name": "t1", "status": "open"}),
            ),
            _decision_section(
                _item({"topic": "Use SQLite"}, ts=1736942400.0),
            ),
        )
        text = _render_text(data, Zoom.FULL)
        assert "Recent decisions" in text
        assert "Use SQLite" in text

    def test_tasks_classified(self):
        data = _state(
            _task_section(
                _item({"name": "build-widget", "status": "open"}),
                _item({"name": "done-thing", "status": "completed"}),
            ),
        )
        text = _render_text(data, Zoom.SUMMARY)
        assert "build-widget" in text
        assert "done-thing" not in text

    def test_mixed_threads_and_tasks(self):
        data = _state(
            _thread_section(
                _item({"name": "thread-ready", "message": "Design complete"}),
            ),
            _task_section(
                _item({"name": "task-open", "status": "open"}),
            ),
        )
        text = _render_text(data, Zoom.SUMMARY)
        assert "thread-ready" in text
        assert "task-open" in text

    def test_non_thread_task_sections_ignored(self):
        """Only thread and task sections contribute to readiness tree."""
        data = _state(
            _decision_section(
                _item({"topic": "some-decision"}),
            ),
        )
        text = _render_text(data, Zoom.SUMMARY)
        assert "nothing tracked" in text
