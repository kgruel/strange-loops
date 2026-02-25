---
id: search
title: Search
group: application
order: 3
align: center
---

# Search

[spacer]

[zoom:0]

filtered selection: `query` + `selected` index

[spacer]

```python
search = Search()
search = search.type("f")     # query="f"
search = search.type("o")     # query="fo"
search = search.backspace()   # query="f"
```

[spacer]

filter patterns: `contains`, `prefix`, `fuzzy`

[spacer]

↓ for interactive demo

[zoom:1]

type to filter, `up/down` to select, `m` to change mode

[spacer]

[demo:search]

[zoom:2]

from `fidelis/search.py`

[spacer]

<!-- docgen:begin py:fidelis.search:Search#definition -->
```python
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
        cursor = Cursor(index=self.selected, count=match_count, mode=CursorMode.WRAP).next()
        return replace(self, selected=cursor.index)

    def select_prev(self, match_count: int) -> Search:
        """Return new Search with selection moved to previous match (wrapping)."""
        if match_count == 0:
            return self
        cursor = Cursor(index=self.selected, count=match_count, mode=CursorMode.WRAP).prev()
        return replace(self, selected=cursor.index)

    def selected_item(self, matches: Sequence[str]) -> str | None:
        """Return the currently selected item from matches, or None if empty."""
        if not matches or self.selected >= len(matches):
            return None
        return matches[self.selected]
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.search:filter_fuzzy#definition -->
```python
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
```
<!-- docgen:end -->
