---
id: block
title: Block
group: composition
order: 1
align: center
---

# Block

[spacer]

[zoom:0]

immutable rectangle of Cells - the composition unit

[spacer:2]

```python
block = Block.text("hello", Style(fg="cyan"))
# block.width = 5, block.height = 1

block.paint(buf, x=10, y=5)  # copy into buffer
```

[spacer]

↓ for more detail

[zoom:1]

`Block` stores rows of `Cells` - **immutable**

[spacer]

```python
@dataclass(frozen=True)
class Block:
    rows: list[list[Cell]]
    width: int

    @classmethod
    def text(cls, text: str, style: Style) -> Block:
        # create block from string

    @classmethod
    def empty(cls, width: int, height: int) -> Block:
        # create blank block
```

[spacer]

compose via `join`, `pad`, `border`

[zoom:2]

from `fidelis/block.py`

[spacer]

```python
@dataclass(frozen=True)
class Block:
    """Immutable rectangle of Cells."""
    rows: list[list[Cell]]
    width: int

    @property
    def height(self) -> int:
        return len(self.rows)

    @classmethod
    def text(cls, text: str, style: Style) -> "Block":
        """Create a Block from a string."""
        cells = [Cell(ch, style) for ch in text]
        return cls(rows=[cells], width=len(cells))

    def paint(self, view: BufferView, x: int, y: int):
        """Copy this block into the view."""
        for row_idx, row in enumerate(self.rows):
            for col_idx, cell in enumerate(row):
                view.put(x + col_idx, y + row_idx, cell.char, cell.style)
```
