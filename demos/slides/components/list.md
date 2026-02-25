---
id: list
title: List View
group: components
order: 3
align: center
---

# List View

[spacer]

`ListState` + `list_view()`

[spacer]

[demo:list]

[spacer]

```python
state = ListState(cursor=Cursor(count=5))
state = state.move_down()  # returns new state

items = [Line.plain("Apple"), ...]
state = state.scroll_into_view(visible_height=5)
lst = list_view(state, items, visible_height=5)
```
