"""Tests for test lens — parse pipeline test results."""

from painted import Zoom

from .helpers import block_text as _text


def test_test_warning():
    from loops.lenses.test import test_view
    assert "Warning" in _text(test_view({"warning": "No parse pipeline"}, Zoom.SUMMARY, 80))

def test_test_minimal():
    from loops.lenses.test import test_view
    data = {"results": [{"name": "x"}], "skipped": 2}
    assert "1 parsed" in _text(test_view(data, Zoom.MINIMAL, 80))

def test_test_summary_non_dict():
    from loops.lenses.test import test_view
    data = {"results": ["raw text"], "skipped": 0}
    assert "raw text" in _text(test_view(data, Zoom.SUMMARY, 80))

def test_test_detailed():
    from loops.lenses.test import test_view
    data = {"results": [{"a": 1, "b": 2}], "skipped": 0}
    t = _text(test_view(data, Zoom.DETAILED, 80))
    assert "a" in t

def test_test_no_width():
    from loops.lenses.test import test_view
    data = {"results": [{"a": 1}], "skipped": 0}
    block = test_view(data, Zoom.SUMMARY, None)  # width=None → piped
    assert block is not None
