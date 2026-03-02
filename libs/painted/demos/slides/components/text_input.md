---
id: text_input
title: Text Input
group: components
order: 4
align: center
---

# Text Input

[spacer]

`TextInputState` + `text_input()`

[spacer]

[demo:text_input]

[spacer]

```python
state = TextInputState(text="hello")
state = state.insert("!")  # returns new state

inp = text_input(state, width=20, focused=True)
```
