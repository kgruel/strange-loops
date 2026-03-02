# painted

One library. Print to TUI. One dependency.

```python
from painted import show

show({"cpu": 67, "mem": 82, "disk": 45})
```

TTY gets a styled bar chart. Pipe gets plain text. `--json` gets JSON.
Same data, same function — the stack figures out the rest.

<!-- TODO: tapes/hero.gif — show() in TTY, pipe, JSON contexts -->

## Enter anywhere

Every entry point uses the same building blocks. Pick the one that fits your problem —
you never hand over control, and there's no cliff between them.

### Print styled output

Replace `print()` one call at a time. Auto-detects TTY — no ANSI garbage in pipes.

```python
from painted import Block, Style, print_block

block = Block.text("deploy OK", Style(fg="green", bold=True))
print_block(block)
```

<!-- TODO: tapes/styled.gif — print vs print_block contrast -->

### Compose

Blocks are immutable rectangles. Compose them with functions — no widget tree, no DOM.

```python
from painted import border, join_vertical, pad, ROUNDED

header = Block.text(" api-gateway ", Style(bold=True, reverse=True))
status = join_vertical(
    Block.text("  replicas: 2/3 ready", Style(fg="yellow")),
    Block.text("  /health:  200  12ms", Style(fg="green")),
)
card = border(join_vertical(header, status), chars=ROUNDED)
print_block(card)
```

<!-- TODO: tapes/compose.gif — bordered card output -->

### CLI harness

One render function, three output modes. Pipe gets static, TTY gets live updates,
`-i` gets full interactive.

```python
from painted import run_cli, CliContext, Block

def render(ctx: CliContext, data: dict) -> Block:
    # your render logic — returns a Block
    ...

def fetch() -> dict:
    return {"status": "ok", "replicas": 3}

run_cli(sys.argv[1:], render=render, fetch=fetch)
```

```bash
myapp              # auto-detect
myapp -q           # quiet (zoom 0)
myapp -v           # verbose (zoom 2)
myapp -i           # interactive TUI
myapp --json       # JSON output
myapp | grep ok    # plain text, no ANSI
```

<!-- TODO: tapes/zoom.gif — quiet/default/verbose spectrum -->

### Full TUI

Alt screen, keyboard input, async render loop, diff-flush. Subclass `Surface`,
override `render()` and `on_key()`.

```python
import asyncio
from painted import Block, Style, border
from painted.tui import Surface

class MyApp(Surface):
    def render(self):
        block = Block.text("Hello!", Style(fg="green"))
        border(block, title="Demo").paint(self._buf)

    def on_key(self, key: str):
        if key == "q":
            self.quit()

asyncio.run(MyApp().run())
```

<!-- TODO: tapes/tui.gif — alt screen flash with navigation -->

## Install

```bash
pip install painted
```

One dependency: [wcwidth](https://pypi.org/project/wcwidth/) (wide character display width).

## API

### Primitives

| Export | Purpose |
|--------|---------|
| `Cell` / `Style` | Atomic display unit (char + style, frozen) |
| `Span` / `Line` | Styled text with display-width awareness |
| `Block` | Immutable rectangle of cells for composition |

### Composition

| Export | Purpose |
|--------|---------|
| `join_horizontal` / `join_vertical` | Combine Blocks |
| `pad` / `border` / `truncate` | Transform Blocks |
| `BorderChars` | ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII presets |

### Display

| Export | Purpose |
|--------|---------|
| `show(data)` | Zero-config display with auto-detection |
| `print_block(block)` | Print a Block to stdout (TTY-aware) |
| `run_cli(args, render=, fetch=)` | CLI harness with zoom/mode/format |

### Views (`painted.views`)

| Export | Purpose |
|--------|---------|
| `shape_lens` | Auto-dispatch for exploration (numeric → chart, hierarchical → tree) |
| `tree_lens` / `chart_lens` | Explicit tree and chart strategies |
| `list_view` / `table` / `text_input` | Stateful interactive components |
| `spinner` / `progress_bar` / `sparkline` | Animation and data viz |

### TUI (`painted.tui`)

| Export | Purpose |
|--------|---------|
| `Surface` | Alt screen, keyboard, resize, diff-flush render loop |
| `Layer` | Modal stack: `Stay` / `Pop` / `Push` / `Quit` |
| `Buffer` / `BufferView` | 2D cell grid with region clipping |

### Aesthetic

| Export | Purpose |
|--------|---------|
| `Palette` | 5 semantic Style roles (success, warning, error, accent, muted) |
| `IconSet` | Glyph vocabulary with ASCII fallback |

## License

MIT
