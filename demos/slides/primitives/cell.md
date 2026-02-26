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

from `painted/cell.py`

[spacer]

<!-- docgen:begin py:painted.cell:Cell#definition -->
```python
@dataclass(frozen=True)
class Cell:
    """Atomic display unit: a single character with style."""

    char: str
    style: Style

    def __post_init__(self):
        if len(self.char) != 1:
            raise ValueError(f"Cell char must be a single character, got {self.char!r}")
```
<!-- docgen:end -->
