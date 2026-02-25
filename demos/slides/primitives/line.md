---
id: line
title: Line
group: primitives
order: 4
align: center
---

# Line

[spacer]

[zoom:0]

a sequence of Spans - styled inline text

[spacer:2]

```python
line = Line(spans=(
    Span("error: ", Style(fg="red", bold=True)),
    Span("file not found", Style(fg="white")),
))
# line.width = 21
```

[spacer]

↓ for more detail

[zoom:1]

`Line` is a sequence of `Spans`

[spacer]

```python
@dataclass(frozen=True)
class Line:
    spans: tuple[Span, ...] = ()
    style: Style | None = None  # fallback style

    @property
    def width(self) -> int:
        return sum(s.width for s in self.spans)

    def paint(self, view: BufferView, x: int, y: int):
        for span in self.spans:
            # paint each span, advancing x
```

[spacer]

`Line.plain(text, style)` - convenience constructor

[zoom:2]

from `fidelis/span.py`

[spacer]

```python
@dataclass(frozen=True)
class Line:
    """A sequence of Spans - styled inline text."""
    spans: tuple[Span, ...] = ()
    style: Style | None = None

    @property
    def width(self) -> int:
        return sum(s.width for s in self.spans)

    def paint(self, view: BufferView, x: int, y: int) -> int:
        """Paint spans left to right, return ending x."""
        for span in self.spans:
            view.put_text(x, y, span.text, span.style)
            x += span.width
        return x
```
