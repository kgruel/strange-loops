# painted.tui — Interactive App Subsystem

Full-screen terminal applications with keyboard input, modal dialogs, and diff rendering.

## Surface

The app base class. Manages alt screen, keyboard loop, and diff-based rendering.

```python
from painted.tui import Surface, BufferView

class MyApp(Surface):
    def __init__(self):
        super().__init__()
        self.count = 0

    def render(self, buf: BufferView) -> None:
        block = Block.text(f"Count: {self.count}", Style())
        block.paint(buf, 0, 0)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key == " ":
            self.count += 1

MyApp().run()
```

`run()` enters alt screen, starts keyboard + render loop, diff-flushes only changed cells.

## Layer Pattern

Modal stack on top of Surface. Top layer handles keys, all render bottom-to-top.

```python
from painted.tui import Layer, Stay, Pop, Push, Quit, Action

class ConfirmLayer(Layer):
    def handle(self, key, layer_state, app_state):
        if key == "y":
            return layer_state, app_state, Pop(result=True)
        if key == "n":
            return layer_state, app_state, Pop(result=False)
        return layer_state, app_state, Stay()

    def render(self, layer_state, app_state, buf):
        Block.text("Confirm? [y/n]", Style()).paint(buf, 0, 0)
```

Actions: `Stay` | `Pop(result)` | `Push(layer)` | `Quit`. Base layer never pops.

## Focus

Two-tier model: navigation vs widget capture.

```python
from painted.tui import Focus, ring_next, ring_prev

focus = Focus(id="sidebar")
focus = ring_next(focus, ["sidebar", "main", "footer"])  # cycle forward
focus.captured  # True when a widget owns all input (e.g., text input)
```

## Search

Query + selected index, with filter functions.

```python
from painted.tui import Search, filter_fuzzy, filter_prefix, filter_contains

search = Search(query="hel")
matches = filter_fuzzy(search, items, key=lambda x: x.name)
```

## Buffer / BufferView

Direct cell painting. BufferView clips and translates coordinates.

```python
from painted.tui import Buffer, BufferView, Region

buf = Buffer(80, 24)
view = Region(x=5, y=2, width=40, height=10).view(buf)
block.paint(view, 0, 0)  # paints at (5, 2) in buffer coordinates
```

## Testing

```python
from painted.tui import TestSurface, CapturedFrame

surface = TestSurface(MyApp(), keys=["j", "j", "enter", "q"])
frames: list[CapturedFrame] = surface.run()
assert "expected text" in frames[-1].text
```

`TestSurface` replays keys, captures frames and emissions. No real terminal needed.

## Exports

```python
from painted.tui import (
    Buffer, BufferView, CellWrite, KeyboardInput, Input,
    Surface, Emit, LifecycleHook,
    Layer, Stay, Pop, Push, Quit, Action, process_key, render_layers,
    Focus, ring_next, ring_prev, linear_next, linear_prev,
    Search, filter_fuzzy, filter_prefix, filter_contains,
    TestSurface, CapturedFrame,
    Region, Cursor, CursorMode,
)
```
