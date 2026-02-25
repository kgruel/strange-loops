---
id: buffer
title: Buffer
group: composition
order: 3
align: center
---

# Buffer

[spacer]

[zoom:0]

the 2D canvas - a grid of Cells

[spacer:2]

```python
buf = Buffer(80, 24)
buf.put(0, 0, "A", Style(fg="red"))
buf.put_text(0, 1, "hello", Style())
buf.fill(10, 10, 5, 3, "X", Style(fg="blue"))
```

↓ for more detail

[zoom:1]

a clipped, translated region of a Buffer

[spacer]

```python
view = buf.region(10, 5, 20, 10)
# view.width = 20, view.height = 10
# writes at (0,0) in view -> (10,5) in buffer
# writes outside view bounds are clipped
```

[spacer]

paint into views without bounds checking

[zoom:2]

from `fidelis/buffer.py`

[spacer]

```python
class Buffer:
    """2D grid of Cells - the rendering canvas."""

    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height
        self._cells = [[EMPTY_CELL] * width for _ in range(height)]

    def put(self, x: int, y: int, char: str, style: Style):
        """Set a single cell."""
        if 0 <= x < self._width and 0 <= y < self._height:
            self._cells[y][x] = Cell(char, style)

    def region(self, x: int, y: int, w: int, h: int) -> BufferView:
        """Get a clipped, translated view of this buffer."""
        return BufferView(self, x, y, w, h)
```
