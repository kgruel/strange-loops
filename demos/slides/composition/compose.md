---
id: compose
title: Compose
group: composition
order: 2
align: center
---

# Compose

[spacer]

[zoom:0]

combine blocks spatially

[spacer]

```python
join_horizontal(a, b, gap=1)  # side by side
join_vertical(a, b)           # stacked
pad(block, left=2, top=1)     # margins
border(block, ROUNDED)        # box drawing
truncate(block, width=20)     # cut to size
```

[zoom:1]

from `fidelis/compose.py`

[spacer]

```python
def join_horizontal(*blocks: Block, gap: int = 0) -> Block:
    """Place blocks side by side."""
    if not blocks:
        return Block.empty(0, 0)
    max_h = max(b.height for b in blocks)
    rows = []
    for y in range(max_h):
        row = []
        for i, block in enumerate(blocks):
            if i > 0 and gap > 0:
                row.extend([EMPTY_CELL] * gap)
            if y < block.height:
                row.extend(block.rows[y])
            else:
                row.extend([EMPTY_CELL] * block.width)
        rows.append(row)
    return Block(rows=rows, width=sum(len(r) for r in [rows[0]]))
```
