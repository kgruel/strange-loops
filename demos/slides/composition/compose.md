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

<!-- docgen:begin py:fidelis.compose:join_horizontal#signature -->
```python
def join_horizontal(*blocks: Block, gap: int = 0,
                    align: Align = Align.START) -> Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.compose:join_vertical#signature -->
```python
def join_vertical(*blocks: Block, gap: int = 0,
                  align: Align = Align.START) -> Block:
```
<!-- docgen:end -->
