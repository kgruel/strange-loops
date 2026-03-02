---
id: style
title: Style
group: primitives
order: 2
align: center
---

# Style

[spacer]

[zoom:0]

colors and attributes for rendering

[spacer:2]

```python
Style(fg="red")           # foreground color
Style(bg="blue")          # background color
Style(bold=True)          # bold text
Style(fg="#ff6b35")       # hex colors
Style(fg=196)             # 256-palette
```

↓ for more detail

[zoom:1]

`Style` attributes

[spacer]

```python
@dataclass(frozen=True)
class Style:
    fg: str | int | None = None   # foreground
    bg: str | int | None = None   # background
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
```

[spacer]

`Style.merge(other)` combines styles - other wins on conflict

[zoom:2]

from `painted/cell.py`

[spacer]

<!-- docgen:begin py:painted.cell:Style#definition -->
```python
@dataclass(frozen=True)
class Style:
    """Immutable text style with color and attribute flags."""

    fg: Color = None
    bg: Color = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    dim: bool = False

    def merge(self, other: Style) -> Style:
        """Combine styles. `other` overrides non-None/non-False fields."""
        return Style(
            fg=other.fg if other.fg is not None else self.fg,
            bg=other.bg if other.bg is not None else self.bg,
            bold=other.bold or self.bold,
            italic=other.italic or self.italic,
            underline=other.underline or self.underline,
            reverse=other.reverse or self.reverse,
            dim=other.dim or self.dim,
        )
```
<!-- docgen:end -->
