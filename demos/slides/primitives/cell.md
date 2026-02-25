---
id: cell
title: Cell
group: primitives
order: 1
align: center
---

# Cell

[spacer]

[zoom:0]

the atomic unit: one `character` + one `style`

[spacer]

```python
cell = Cell("A", Style(fg="red", bold=True))
```

[spacer]

↓ for more detail

[zoom:1]

`Cell` is a frozen dataclass - **immutable** by design

[spacer]

```python
@dataclass(frozen=True)
class Cell:
    char: str
    style: Style

EMPTY_CELL = Cell(" ", Style())
```

[spacer]

`EMPTY_CELL` is the default for unfilled buffer positions

[zoom:2]

from `fidelis/cell.py`

[spacer]

```python
@dataclass(frozen=True)
class Cell:
    """A single cell in the buffer: one character + one style."""
    char: str = " "
    style: Style = field(default_factory=Style)

    def __post_init__(self):
        # Enforce single character (but allow multi-byte)
        if len(self.char) != 1:
            object.__setattr__(self, "char", self.char[0] if self.char else " ")

EMPTY_CELL = Cell(" ", Style())
```
