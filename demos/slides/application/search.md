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

```python
@dataclass(frozen=True)
class Search:
    """Immutable search state: query + selected index."""
    query: str = ""
    selected: int = 0

    def type(self, char: str) -> "Search":
        return replace(self, query=self.query + char, selected=0)

    def backspace(self) -> "Search":
        return replace(self, query=self.query[:-1], selected=0)

def filter_fuzzy(items: Sequence[str], query: str) -> list[str]:
    """Filter items by fuzzy match (chars in order)."""
    if not query:
        return list(items)
    return [item for item in items if _fuzzy_match(item, query)]
```
