# cells

A cell-buffer terminal UI framework for Python.

## Install

```bash
uv add cells
```

## Quick Start

```python
import asyncio
from cells import Surface, Block, Style, border

class HelloApp(Surface):
    def render(self):
        block = Block.text("Hello, cells!", Style(fg="green"))
        bordered = border(block, title="Demo")
        bordered.paint(self._buf)

asyncio.run(HelloApp().run())
```

## Overview

- **Cell/Style** — atomic display unit (char + style)
- **Buffer/BufferView** — 2D cell grid with region clipping
- **Block** — immutable rectangle of cells for composition
- **Span/Line** — styled text primitives
- **compose** — `join_horizontal`, `join_vertical`, `pad`, `border`, `truncate`
- **Surface** — async main loop with keyboard input and resize handling
- **components** — spinner, progress bar, list view, text input, table

Extracted from [experiments](https://github.com/kaygee/experiments).
