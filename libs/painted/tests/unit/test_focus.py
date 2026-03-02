"""Tests for Focus primitive and navigation functions."""

import pytest

from painted.tui import Focus, linear_next, linear_prev, ring_next, ring_prev


class TestFocus:
    """Tests for Focus dataclass."""

    def test_immutable(self):
        """Focus is frozen."""
        f = Focus(id="a")
        with pytest.raises(AttributeError):
            f.id = "b"

    def test_default_captured_false(self):
        """Captured defaults to False."""
        f = Focus(id="a")
        assert f.captured is False

    def test_focus_changes_id_and_releases(self):
        """focus() changes id and releases capture."""
        f = Focus(id="a", captured=True)
        f2 = f.focus("b")
        assert f2.id == "b"
        assert f2.captured is False
        # Original unchanged
        assert f.id == "a"
        assert f.captured is True

    def test_capture(self):
        """capture() returns Focus with captured=True."""
        f = Focus(id="a")
        f2 = f.capture()
        assert f2.captured is True
        assert f.captured is False

    def test_release(self):
        """release() returns Focus with captured=False."""
        f = Focus(id="a", captured=True)
        f2 = f.release()
        assert f2.captured is False
        assert f.captured is True

    def test_toggle_capture(self):
        """toggle_capture() flips the captured flag."""
        f = Focus(id="a", captured=False)
        f2 = f.toggle_capture()
        assert f2.captured is True
        f3 = f2.toggle_capture()
        assert f3.captured is False


class TestRingNavigation:
    """Tests for ring navigation functions."""

    def test_ring_next_basic(self):
        """ring_next moves to next item."""
        items = ("a", "b", "c")
        assert ring_next(items, "a") == "b"
        assert ring_next(items, "b") == "c"

    def test_ring_next_wraps(self):
        """ring_next wraps at end."""
        items = ("a", "b", "c")
        assert ring_next(items, "c") == "a"

    def test_ring_prev_basic(self):
        """ring_prev moves to previous item."""
        items = ("a", "b", "c")
        assert ring_prev(items, "c") == "b"
        assert ring_prev(items, "b") == "a"

    def test_ring_prev_wraps(self):
        """ring_prev wraps at start."""
        items = ("a", "b", "c")
        assert ring_prev(items, "a") == "c"

    def test_ring_empty(self):
        """ring functions return current when empty."""
        assert ring_next((), "x") == "x"
        assert ring_prev((), "x") == "x"

    def test_ring_not_found(self):
        """ring functions return first item when current not found."""
        items = ("a", "b", "c")
        assert ring_next(items, "z") == "a"
        assert ring_prev(items, "z") == "a"


class TestLinearNavigation:
    """Tests for linear navigation functions."""

    def test_linear_next_basic(self):
        """linear_next moves to next item."""
        items = ("a", "b", "c")
        assert linear_next(items, "a") == "b"
        assert linear_next(items, "b") == "c"

    def test_linear_next_stops(self):
        """linear_next stops at end."""
        items = ("a", "b", "c")
        assert linear_next(items, "c") == "c"

    def test_linear_prev_basic(self):
        """linear_prev moves to previous item."""
        items = ("a", "b", "c")
        assert linear_prev(items, "c") == "b"
        assert linear_prev(items, "b") == "a"

    def test_linear_prev_stops(self):
        """linear_prev stops at start."""
        items = ("a", "b", "c")
        assert linear_prev(items, "a") == "a"

    def test_linear_empty(self):
        """linear functions return current when empty."""
        assert linear_next((), "x") == "x"
        assert linear_prev((), "x") == "x"

    def test_linear_not_found(self):
        """linear functions return first item when current not found."""
        items = ("a", "b", "c")
        assert linear_next(items, "z") == "a"
        assert linear_prev(items, "z") == "a"
