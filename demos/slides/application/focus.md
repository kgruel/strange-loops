---
id: focus
title: Focus
group: application
order: 2
align: center
---

# Focus

[spacer]

[zoom:0]

immutable state: `id` + `captured` flag

[spacer]

```python
focus = Focus(id="sidebar")
focus = focus.capture()   # widget handles keys
focus = focus.release()   # nav handles keys
```

[spacer]

navigation patterns: `ring_next`, `linear_prev`, ...

[spacer]

↓ for navigation demo

[zoom:1]

pure functions: `items` + `current` -> `next`

[spacer]

```python
items = ("a", "b", "c")
current = "b"

ring_next(items, current)    # "c"
ring_next(items, "c")        # "a" (wraps)

linear_next(items, current)  # "c"
linear_next(items, "c")      # "c" (stops)
```

[spacer]

[demo:focus_nav]

[zoom:2]

from `fidelis/focus.py`

[spacer]

```python
@dataclass(frozen=True)
class Focus:
    """Immutable focus state: id + captured flag."""
    id: str = ""
    captured: bool = False

    def capture(self) -> "Focus":
        return replace(self, captured=True)

    def release(self) -> "Focus":
        return replace(self, captured=False)

def ring_next(items: Sequence[T], current: T) -> T:
    """Next item, wrapping at end."""
    idx = items.index(current)
    return items[(idx + 1) % len(items)]
```
