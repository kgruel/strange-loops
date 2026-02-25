---
id: rendering_pipeline
title: Rendering Pipeline
group: composition
order: 4
align: center
---

# Rendering Pipeline

[spacer]

[zoom:0]

the data flow is a small loop: `Block.paint → Buffer.diff → Writer.write_frame`

[spacer]

`Block` is immutable. `Buffer` is mutable. `paint()` copies cells into the current buffer.

[spacer]

`diff()` compares current vs previous and emits a minimal list of `CellWrite` operations.

[spacer]

↓ for more detail

[zoom:1]

*where it happens (simplified)*

[spacer]

```python
# Surface._flush() (simplified)
writes = buf.diff(prev)
writer.write_frame(writes)
prev = buf.clone()
```

[spacer]

`write_frame()` batches cell updates into ANSI cursor moves + SGR style sequences.

[zoom:2]

*the “diff → writer” bridge*

[spacer]

```python
@dataclass
class CellWrite:
    x: int
    y: int
    cell: Cell

writes: list[CellWrite] = buf.diff(prev)
writer.write_frame(writes)
```

