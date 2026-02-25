---
id: layers
title: Layers
group: application
order: 4
align: center
---

# Layers

[spacer]

[zoom:0]

`Layer` is a small modal stack API: help overlays, search overlays, dialogs

[spacer]

input routes **top-down** (top layer handles first)

[spacer]

render paints **bottom-up** (base renders first, overlays on top)

[spacer]

actions are values: `Stay()` · `Pop(result=...)` · `Push(layer)` · `Quit()`

[spacer]

↓ for more detail

[zoom:1]

*the API surface*

[spacer]

```python
Layer[S](
    name: str,
    state: S,
    handle: (key, layer_state, app_state) -> (layer_state, app_state, Action),
    render: (layer_state, app_state, view) -> None,
)
```

[spacer]

```python
new_state, should_quit, pop_result = process_key(
    key, state, get_layers, set_layers,
)
render_layers(state, buf, get_layers)
```

[zoom:2]

*you’ve already used this in the tour*

[spacer]

`demos/tour.py` calls `process_key(...)` to route keys and `render_layers(...)` to paint the stack.

