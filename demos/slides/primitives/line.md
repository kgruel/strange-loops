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

<!-- docgen:begin py:fidelis.span:Line#signature -->
```python
@dataclass(frozen=True, slots=True)
class Line:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.span:Line.paint#definition -->
```python
    def paint(self, view: BufferView, x: int, y: int) -> None:
        """Render spans into a BufferView, merging base style onto each span."""
        col = x
        for span in self.spans:
            merged = self.style.merge(span.style)
            view.put_text(col, y, span.text, merged)
            col += span.width
```
<!-- docgen:end -->
