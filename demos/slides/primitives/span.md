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

from `painted/span.py`

[spacer]

<!-- docgen:begin py:painted.span:Span#definition -->
```python
@dataclass(frozen=True, slots=True)
class Span:
    """A run of text with a single style."""

    text: str
    style: Style = Style()

    @property
    def width(self) -> int:
        """Display width, accounting for wide characters."""
        w = wcswidth(self.text)
        if w < 0:
            # Fallback for strings containing non-printable chars
            return len(self.text)
        return w
```
<!-- docgen:end -->
