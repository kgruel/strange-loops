# render — Interactive Terminal UI Engine

A diff-capable terminal engine for building keyboard-driven interactive apps in Python. Cell buffer + diff means only changed cells get written to the terminal — the architectural piece that Rich is missing.

## What it is

The Python equivalent of Ratatui: a toolkit for interactive terminal applications with explicit composition, frozen-state components, and minimal terminal I/O.

```
Rich        — great output, weak interactivity (Live is a polling hack)
render      — interactive apps with diff-based output (this)
Textual     — full widget framework (CSS, DOM, messages). Heavy.
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│  App (RenderApp lifecycle)                       │
│  update/render/on_key loop, adaptive sleep       │
├─────────────────────────────────────────────────┤
│  Components (frozen state + transitions + view)  │
│  ListState, TextInputState, TableState, etc.     │
├─────────────────────────────────────────────────┤
│  Description Layer (Span/Line)                   │
│  Styled text runs. No cells until paint.         │
├─────────────────────────────────────────────────┤
│  Spatial Layer (Block + compose)                 │
│  2D cell grids: borders, padding, joins.         │
├─────────────────────────────────────────────────┤
│  Frame Buffer (Buffer + Writer)                  │
│  Cell grid, diff, ANSI output. Mode 2026.        │
├─────────────────────────────────────────────────┤
│  Terminal I/O (KeyboardInput + Writer)            │
│  Raw input (cbreak, CSI/SS3, UTF-8), output.     │
└─────────────────────────────────────────────────┘
```

## Core concepts

**Composition vocabulary** — three levels, each with a paint boundary:
- **Span** — `(str, Style)`. The atom.
- **Line** — sequence of Spans. Inline composition (90% of cases).
- **Block** — 2D cell grid. Spatial composition (borders, side-by-side panes).

**Components** — frozen dataclasses (state + transitions + render function). State flows down, styled output flows up. No mutation, no side effects.

**The diff** — Buffer holds current frame, prev holds last frame. `diff()` emits only changed cells as ANSI escape sequences. This is why high-throughput streaming doesn't choke the terminal.

## Dependencies

- `wcwidth` (Unicode character widths)
- stdlib only for everything else

## Usage

```python
from render import RenderApp, Style, Line, Span, Block, ListState, list_view

class MyApp(RenderApp):
    def __init__(self):
        super().__init__(fps_cap=30)
        self._list = ListState(item_count=100)

    def on_key(self, key: str) -> None:
        if key == "up": self._list = self._list.move_up()
        if key == "down": self._list = self._list.move_down()
        if key == "q": self.quit()

    def render(self) -> None:
        items = [Line.plain(f"Item {i}") for i in range(100)]
        block = list_view(self._list, items, self._buf.height)
        view = self._buf.view(0, 0, self._buf.width, self._buf.height)
        block.paint(view, 0, 0)
```
