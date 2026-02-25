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

<!-- docgen:begin py:fidelis.focus:Focus#definition -->
```python
@dataclass(frozen=True, slots=True)
class Focus:
    """Immutable focus state primitive.

    Tracks what's focused and whether the focused component has captured
    keyboard input (two-tier focus: navigation vs widget interaction).
    """

    id: str
    captured: bool = False

    def focus(self, id: str) -> Focus:
        """Return new Focus on the given id, releasing capture."""
        return Focus(id=id, captured=False)

    def capture(self) -> Focus:
        """Return new Focus with keyboard captured by current component."""
        return replace(self, captured=True)

    def release(self) -> Focus:
        """Return new Focus with keyboard released to navigation."""
        return replace(self, captured=False)

    def toggle_capture(self) -> Focus:
        """Return new Focus with capture toggled."""
        return replace(self, captured=not self.captured)
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.focus:ring_next#definition -->
```python
def ring_next(items: Sequence[str], current: str) -> str:
    """Move to next item in ring, wrapping at end."""
    if not items:
        return current
    try:
        idx = list(items).index(current)
        return items[(idx + 1) % len(items)]
    except ValueError:
        return items[0] if items else current
```
<!-- docgen:end -->
