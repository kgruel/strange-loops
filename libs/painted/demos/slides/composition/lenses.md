---
id: lenses
title: Lenses (views)
group: composition
order: 5
align: center
---

# Lenses (views)

[spacer]

[zoom:0]

`painted.views` lenses are pure helpers: **state → Block**

[spacer]

they take `zoom` and `width` explicitly: `value + zoom + width → Block`

[spacer]

`shape_lens` (generic python), `tree_lens` (hierarchies), `chart_lens` (sparklines/bars)

[spacer]

↓ for more detail

[zoom:1]

zoom is an axis: it changes the representation, not just “more lines”

[spacer]

width and zoom are orthogonal inputs — parents allocate width, callers choose zoom

[spacer]

`shape_lens` auto-dispatches: numeric data → `chart_lens`, hierarchical → `tree_lens`

[zoom:2]

*minimal usage (stable pattern)*

[spacer]

```python
from painted.views import shape_lens, tree_lens, chart_lens

block = shape_lens(data, zoom=zoom, width=width)
# or: tree_lens(data, zoom=zoom, width=width)
# or: chart_lens(values, zoom=zoom, width=width)
```

[spacer]

note: the tour’s `LensContext` / `section_lens` is internal; these are the public APIs

