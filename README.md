# fidelis

A cell-buffer terminal UI framework

## Atom

```
Cell
 ├─ char: str       # single character
 └─ style: Style
     ├─ fg: str     # foreground color
     ├─ bg: str     # background color
     ├─ bold: bool
     ├─ dim: bool
     ├─ italic: bool
     └─ ...
```

## Usage

```python
import asyncio
from fidelis import Surface, Block, Style, border

class HelloApp(Surface):
    def render(self):
        block = Block.text("Hello, fidelis!", Style(fg="green"))
        bordered = border(block, title="Demo")
        bordered.paint(self._buf)

asyncio.run(HelloApp().run())
```

## API

| Export | Purpose |
|--------|---------|
| `Cell` / `Style` | Atomic display unit (char + style) |
| `Buffer` / `BufferView` | 2D cell grid with region clipping |
| `Block` | Immutable rectangle of cells for composition |
| `Span` / `Line` | Styled text primitives |
| `join_horizontal`, `join_vertical`, `pad`, `border`, `truncate` | Composition functions |
| `Surface` | Async main loop with keyboard input and resize handling |
| `Layer` / `Lens` | Layered rendering and viewport |
