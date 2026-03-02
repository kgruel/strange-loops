---
id: progress
title: Progress Bar
group: components
order: 2
align: center
---

# Progress Bar

[spacer]

`ProgressState` + `progress_bar()`

[spacer]

[demo:progress]

[spacer]

```python
state = ProgressState(value=0.5)
state = state.set(0.75)  # returns new state

bar = progress_bar(state, width=30)
```
