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

from `painted/buffer.py`

[spacer]

<!-- docgen:begin py:painted.buffer:Buffer.put#signature -->
```python
    def put(self, x: int, y: int, char: str, style: Style) -> None:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.buffer:Buffer.put_text#signature -->
```python
    def put_text(self, x: int, y: int, text: str, style: Style) -> None:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.buffer:Buffer.fill#signature -->
```python
    def fill(self, x: int, y: int, w: int, h: int, char: str, style: Style) -> None:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.buffer:Buffer.region#signature -->
```python
    def region(self, x: int, y: int, w: int, h: int) -> BufferView:
```
<!-- docgen:end -->
