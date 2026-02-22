"""Tests for Search primitive and filter functions."""

import pytest
from fidelis.tui import Search, filter_contains, filter_prefix, filter_fuzzy


class TestSearch:
    """Tests for Search dataclass."""

    def test_immutable(self):
        """Search is frozen."""
        s = Search()
        with pytest.raises(AttributeError):
            s.query = "test"

    def test_default_empty(self):
        """Default Search has empty query and zero selection."""
        s = Search()
        assert s.query == ""
        assert s.selected == 0

    def test_type_appends_char(self):
        """type() appends character to query."""
        s = Search()
        s2 = s.type("a")
        assert s2.query == "a"
        s3 = s2.type("b")
        assert s3.query == "ab"
        # Original unchanged
        assert s.query == ""

    def test_type_resets_selection(self):
        """type() resets selection to 0."""
        s = Search(query="test", selected=3)
        s2 = s.type("x")
        assert s2.selected == 0

    def test_backspace_removes_char(self):
        """backspace() removes last character."""
        s = Search(query="abc")
        s2 = s.backspace()
        assert s2.query == "ab"
        # Original unchanged
        assert s.query == "abc"

    def test_backspace_on_empty(self):
        """backspace() on empty query returns same."""
        s = Search()
        s2 = s.backspace()
        assert s2.query == ""

    def test_clear(self):
        """clear() returns empty query."""
        s = Search(query="test", selected=2)
        s2 = s.clear()
        assert s2.query == ""
        assert s2.selected == 0

    def test_select_next(self):
        """select_next() moves selection forward, wrapping."""
        s = Search(selected=0)
        s2 = s.select_next(3)
        assert s2.selected == 1
        s3 = s2.select_next(3)
        assert s3.selected == 2
        s4 = s3.select_next(3)
        assert s4.selected == 0  # wraps

    def test_select_prev(self):
        """select_prev() moves selection backward, wrapping."""
        s = Search(selected=1)
        s2 = s.select_prev(3)
        assert s2.selected == 0
        s3 = s2.select_prev(3)
        assert s3.selected == 2  # wraps

    def test_select_with_zero_matches(self):
        """select_next/prev with zero matches returns same."""
        s = Search(selected=0)
        assert s.select_next(0).selected == 0
        assert s.select_prev(0).selected == 0

    def test_selected_item(self):
        """selected_item() returns item at selected index."""
        s = Search(selected=1)
        matches = ("a", "b", "c")
        assert s.selected_item(matches) == "b"

    def test_selected_item_empty(self):
        """selected_item() returns None for empty matches."""
        s = Search(selected=0)
        assert s.selected_item(()) is None

    def test_selected_item_out_of_bounds(self):
        """selected_item() returns None if selected >= len(matches)."""
        s = Search(selected=5)
        matches = ("a", "b")
        assert s.selected_item(matches) is None


class TestFilterContains:
    """Tests for filter_contains function."""

    def test_empty_query_returns_all(self):
        """Empty query returns all items."""
        items = ("apple", "banana", "cherry")
        assert filter_contains(items, "") == items

    def test_matches_substring(self):
        """Matches items containing substring."""
        items = ("apple", "banana", "cherry")
        assert filter_contains(items, "an") == ("banana",)

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        items = ("Apple", "BANANA", "cherry")
        assert filter_contains(items, "app") == ("Apple",)
        assert filter_contains(items, "BAN") == ("BANANA",)

    def test_no_matches(self):
        """Returns empty tuple when no matches."""
        items = ("apple", "banana")
        assert filter_contains(items, "xyz") == ()


class TestFilterPrefix:
    """Tests for filter_prefix function."""

    def test_empty_query_returns_all(self):
        """Empty query returns all items."""
        items = ("apple", "banana")
        assert filter_prefix(items, "") == items

    def test_matches_prefix(self):
        """Matches items starting with prefix."""
        items = ("apple", "apricot", "banana")
        assert filter_prefix(items, "ap") == ("apple", "apricot")

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        items = ("Apple", "apricot")
        assert filter_prefix(items, "AP") == ("Apple", "apricot")

    def test_no_matches(self):
        """Returns empty when no prefix matches."""
        items = ("apple", "banana")
        assert filter_prefix(items, "ch") == ()


class TestFilterFuzzy:
    """Tests for filter_fuzzy function."""

    def test_empty_query_returns_all(self):
        """Empty query returns all items."""
        items = ("apple", "banana")
        assert filter_fuzzy(items, "") == items

    def test_matches_chars_in_order(self):
        """Matches items with chars appearing in order."""
        items = ("FooBar", "fob", "fb", "bfx")
        assert filter_fuzzy(items, "fb") == ("FooBar", "fob", "fb")

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        items = ("FooBar",)
        assert filter_fuzzy(items, "FB") == ("FooBar",)
        assert filter_fuzzy(items, "fb") == ("FooBar",)

    def test_no_matches(self):
        """Returns empty when no fuzzy matches."""
        items = ("apple", "banana")
        assert filter_fuzzy(items, "xyz") == ()

    def test_order_matters(self):
        """Characters must appear in order."""
        items = ("abc", "cba")
        assert filter_fuzzy(items, "ac") == ("abc",)  # 'a' before 'c' in "abc"
