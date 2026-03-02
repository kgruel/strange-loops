# painted — API Guide

Terminal UI framework built on cell buffers. Start at Level 0. Only escalate when you hit a trigger.

---

## Level 0 — Display data

**Trigger**: I have data and want it to look decent in a terminal.

```python
from painted import show

show({"status": "ok", "items": 42})       # auto-formats by shape
show(data, zoom=Zoom.DETAILED)            # more detail
show(data, zoom=Zoom.MINIMAL)             # one-liner
```

`show()` auto-dispatches by data shape: dict → key-value, list → items, numeric → chart. This is the right starting point 80% of the time.

**Don't reach for yet**: Block, join, border, run_cli.

---

## Level 1 — Compose layout

**Trigger**: I need custom layout — columns, borders, padding.

```python
from painted import Block, Style, join_horizontal, border, pad, print_block

left = Block.text("Name: Alice", Style(bold=True))
right = Block.text("Score: 98", Style(fg="green"))
row = join_horizontal(left, Block.text("  "), right)
print_block(border(pad(row, 1)))
```

Key types:
- `Block` — immutable rectangle of cells. `Block.text()`, `Block.empty(w, h)`.
- `join_vertical`, `join_horizontal` — compose Blocks.
- `border`, `pad`, `truncate` — transform Blocks.
- `Style` — `fg`, `bg`, `bold`, `italic`, `underline`, `reverse`, `dim`. Composable.
- `Span` — text + style, width-aware. `Line` — tuple of Spans.

All immutable. All return new Blocks. Still just printing — no state, no framework.

**Don't reach for yet**: run_cli, Surface, Layer.

---

## Level 2 — CLI tool

**Trigger**: I need `-v`/`-q`, `--json`, pipe detection, help text.

```python
from painted import run_cli, CliContext, Block

def render(ctx: CliContext, data: dict) -> Block:
    return status_view(data, zoom=ctx.zoom, width=ctx.width)

def fetch() -> dict:
    return {"status": "ok"}

run_cli(sys.argv[1:], render=render, fetch=fetch)
```

You provide `render(ctx, data) → Block` and `fetch() → data`. The framework handles zoom/format/mode automatically.

Three orthogonal dimensions:
- **Zoom** (`-q`/`-v`/`-vv`): MINIMAL, SUMMARY, DETAILED, FULL
- **Format** (`--json`/`--plain`): ANSI (TTY default), PLAIN (pipe default), JSON
- **Mode** (`-i`/`--static`/`--live`): AUTO detects from TTY

Streaming: add `fetch_stream` for live updates.

**Don't reach for yet**: Surface, Layer, InPlaceRenderer (unless you need custom animation outside the CLI harness).

---

## Level 3 — Live animation

**Trigger**: I need progress updates without alt-screen, outside the CLI harness.

```python
from painted import InPlaceRenderer, Block, Style
import time

with InPlaceRenderer() as r:
    for i in range(100):
        r.render(Block.text(f"Progress: {i}%", Style()))
        time.sleep(0.05)
    r.finalize(Block.text("Done!", Style(fg="green")))
```

Cursor-controlled in-place rewriting. Note: `run_cli` with `fetch_stream` already does this — only use `InPlaceRenderer` directly for custom animation outside the CLI harness.

**Don't reach for yet**: Surface, Layer.

---

## Level 4 — Interactive TUI

**Trigger**: I need keyboard input, full-screen, modal dialogs.

**Most tools don't need this.** Exhaust levels 0–3 first.

See `tui/CLAUDE.md` for the interactive app subsystem.

---

## Key invariants

- **Frozen types**: all types are immutable. Create new instances, don't mutate.
- **Width-aware**: wcwidth handles emoji/CJK. Display width ≠ `len()`.
- **Style is composable**: `Style(fg="green", bold=True)`.
- **Zoom propagates**: render functions receive zoom level, bifurcate detail.
- **Format auto-detects**: TTY → ANSI, pipe → PLAIN.

## Data rendering

For lenses (auto-dispatch, tree, chart, flame) and components (spinner, progress, list, table, text input):

```python
from painted.views import shape_lens, tree_lens, chart_lens, flame_lens
from painted.views import spinner, list_view, progress_bar, table, text_input
```

See `views/CLAUDE.md` for details.

## Aesthetic customization

```python
from painted import use_palette, NORD_PALETTE, use_icons, ASCII_ICONS

use_palette(NORD_PALETTE)   # set globally
use_icons(ASCII_ICONS)      # set globally

with use_palette(NORD_PALETTE):  # or scoped override
    show(data)
```

`Palette` — 5 semantic Style roles (success, warning, error, accent, muted).
`IconSet` — named glyph slots (spinner, progress, tree, sparkline).
Both use ContextVar — scoped overrides via context manager.
