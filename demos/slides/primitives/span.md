---
id: span
title: Span
group: primitives
order: 3
align: center
---

# Span

[spacer]

[zoom:0]

a run of text with one style

[spacer:2]

```python
span = Span("hello", Style(fg="green", bold=True))
# span.text = "hello"
# span.width = 5
```

[spacer]

↓ for more detail

[zoom:1]

`Span` handles wide characters via **wcwidth**

[spacer]

```python
@dataclass(frozen=True)
class Span:
    text: str
    style: Style = Style()

    @property
    def width(self) -> int:
        # accounts for CJK double-width chars
        return span_width(self.text)
```

[spacer]

`span.width` is display width, not `len(text)`

[zoom:2]

from `fidelis/span.py`

[spacer]

```python
def span_width(text: str) -> int:
    """Calculate display width accounting for wide chars."""
    total = 0
    for ch in text:
        w = wcwidth(ch)
        if w < 0:
            w = 0  # control chars
        total += w
    return total

@dataclass(frozen=True)
class Span:
    """A run of text with one style."""
    text: str
    style: Style = field(default_factory=Style)

    @property
    def width(self) -> int:
        return span_width(self.text)
```
