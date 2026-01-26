"""Search: filtered selection primitive."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Search:
    """Immutable search state for filtered selection.

    Tracks the query string and selected index within filtered results.
    """

    query: str = ""
    selected: int = 0

    def type(self, char: str) -> Search:
        """Return new Search with char appended to query, resetting selection."""
        return Search(query=self.query + char, selected=0)

    def backspace(self) -> Search:
        """Return new Search with last char removed from query."""
        if not self.query:
            return self
        return Search(query=self.query[:-1], selected=0)

    def clear(self) -> Search:
        """Return new Search with empty query."""
        return Search(query="", selected=0)

    def select_next(self, match_count: int) -> Search:
        """Return new Search with selection moved to next match (wrapping)."""
        if match_count == 0:
            return self
        return replace(self, selected=(self.selected + 1) % match_count)

    def select_prev(self, match_count: int) -> Search:
        """Return new Search with selection moved to previous match (wrapping)."""
        if match_count == 0:
            return self
        return replace(self, selected=(self.selected - 1) % match_count)

    def selected_item(self, matches: Sequence[str]) -> str | None:
        """Return the currently selected item from matches, or None if empty."""
        if not matches or self.selected >= len(matches):
            return None
        return matches[self.selected]


# Filter functions — pure functions for matching


def filter_contains(items: Sequence[str], query: str) -> tuple[str, ...]:
    """Filter items by case-insensitive substring match."""
    if not query:
        return tuple(items)
    q = query.lower()
    return tuple(item for item in items if q in item.lower())


def filter_prefix(items: Sequence[str], query: str) -> tuple[str, ...]:
    """Filter items by case-insensitive prefix match."""
    if not query:
        return tuple(items)
    q = query.lower()
    return tuple(item for item in items if item.lower().startswith(q))


def filter_fuzzy(items: Sequence[str], query: str) -> tuple[str, ...]:
    """Filter items by fuzzy match (characters appear in order).

    Example: "fb" matches "FooBar" because 'f' and 'b' appear in order.
    """
    if not query:
        return tuple(items)

    def matches(item: str, q: str) -> bool:
        item_lower = item.lower()
        q_lower = q.lower()
        idx = 0
        for char in q_lower:
            idx = item_lower.find(char, idx)
            if idx == -1:
                return False
            idx += 1
        return True

    return tuple(item for item in items if matches(item, query))
