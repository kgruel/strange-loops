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

from `painted/block.py`

[spacer]

<!-- docgen:begin py:painted.block:Block.text#signature -->
```python
    @staticmethod
    def text(content: str, style: Style, *, width: int | None = None,
             wrap: Wrap = Wrap.NONE, id: str | None = None) -> Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.block:Block.empty#signature -->
```python
    @staticmethod
    def empty(width: int, height: int, style: Style = Style(), *, id: str | None = None) -> Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.block:Block.paint#signature -->
```python
    def paint(self, buffer: Buffer | BufferView, x: int = 0, y: int = 0) -> None:
```
<!-- docgen:end -->
