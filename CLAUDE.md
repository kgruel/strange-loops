# CLAUDE.md — painted

Terminal UI framework built on cell buffers. Answers: **where is state displayed?**

## Build & Test

```bash
uv run --package painted pytest tests/ -q
```

## Atom

```
Cell
 ├─ char: str     # single character (validated)
 └─ style: Style  # fg, bg, bold, italic, underline, reverse, dim
```

## Layer Stack

```
Surface (app base)
  └─ Layer[] (modal stack)
       ├─ handle(key, layer_state, app_state) -> (layer_state, app_state, Action)
       └─ render(layer_state, app_state, BufferView) -> None

Actions: Stay | Pop(result) | Push(layer) | Quit
```

## Rendering Pipeline

```
state ──→ lens_fn(state, zoom, w) ──→ Block
Block ──→ Buffer.paint(block, x, y)
Buffer ──→ diff(prev) ──→ CellWrite[]
CellWrite[] ──→ Writer.write_frame() ──→ ANSI escape sequences
```

## Key Types

### Primitives
| Type | Purpose |
|------|---------|
| `Cell` | char + style (frozen) |
| `Style` | fg, bg, bold, italic, underline, reverse, dim (frozen, merge-able) |
| `Span` | text + style, width-aware (wcwidth) |
| `Line` | tuple of Spans, paint/truncate/to_block |

### Buffers
| Type | Purpose |
|------|---------|
| `Buffer` | 2D cell grid (row-major), diff, clone |
| `BufferView` | clipped coordinate-translating window into Buffer |
| `CellWrite` | single cell change (x, y, cell) for diff output |

### Composition
| Type | Purpose |
|------|---------|
| `Block` | immutable rectangle of cells. `Block.text()`, `Block.empty()` |
| `Region` | x, y, width, height -> BufferView |
| `join_horizontal`, `join_vertical` | compose Blocks |
| `pad`, `border`, `truncate` | transform Blocks |
| `BorderChars` | ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII presets |
| `Align` | START, CENTER, END |

### State
| Type | Purpose |
|------|---------|
| `Focus` | id + captured (two-tier: navigation vs widget capture) |
| `Search` | query + selected (fuzzy, prefix, contains filters) |

### Components
| Type | Purpose |
|------|---------|
| `SpinnerState` / `spinner` | animated spinner (DOTS, LINE, BRAILLE) |
| `ProgressState` / `progress_bar` | horizontal progress bar |
| `ListState` / `list_view` | scrollable list with selection |
| `TextInputState` / `text_input` | single-line input with cursor |
| `TableState` / `table` | scrollable table with headers |

### Aesthetic
| Type | Purpose |
|------|---------|
| `Palette` | 5 semantic Style roles (success, warning, error, accent, muted), ContextVar |
| `IconSet` | Named glyph slots (spinner, progress, tree, sparkline), ContextVar |

### Application
| Type | Purpose |
|------|---------|
| `Surface` | base class: alt screen, keyboard, render loop, diff flush |
| `Emit` | `Callable[[str, dict], None]` — observation callback |
| `Writer` | ANSI output: move, style, frame sync (mode 2026) |
| `KeyboardInput` | cbreak-mode key reader, escape sequence parsing |

## Invariants

- All state types frozen. Components follow `State + render_fn(state, ...) -> Block` pattern.
- Surface diff-renders: only changed cells written to terminal.
- Layer stack: top handles keys, all render bottom-to-top. Base layer never pops.
- `shape_lens` auto-dispatches by data shape: numeric → chart, hierarchical → tree, else built-in rendering.
- `Emit` is the feedback boundary — Surface emits observations that become Facts upstream.

## Pipeline Role

```
Projection.state ──→ lens_fn() ──→ Block ──→ Surface ──→ terminal
                                                    │
Surface.emit(kind, **data) ──→ Fact.of() ──→ Stream  (feedback loop)

Three emission strata:
  Raw input    (auto)  "ui.key"     {key: "j"}
  UI structure (auto)  "ui.action"  {action: "pop", layer: "confirm"}
  Domain       (manual) (any)    {item: "deploy-prod"}
```

## CLI Harness (fidelity)

Three orthogonal dimensions for CLI output control:

```
ZOOM (what to show)              OUTPUT MODE (how to deliver)
├─ 0: MINIMAL (-q/--quiet)       ├─ STATIC: print and scroll
├─ 1: SUMMARY (default)          ├─ LIVE: cursor-controlled updates
├─ 2: DETAILED (-v)              └─ INTERACTIVE: alt screen + keyboard
└─ 3: FULL (-vv)

FORMAT (serialization)
├─ ANSI: styled terminal (TTY default)
├─ PLAIN: no styles (pipe default)
└─ JSON: machine-readable (--json)
```

### Usage

```python
from painted.fidelity import run_cli, CliContext, Zoom, OutputMode

def render(ctx: CliContext, data: dict) -> Block:
    return status_view(data, zoom=ctx.zoom, width=ctx.width)

def fetch() -> dict:
    return {"status": "ok"}

# Simple case: auto-detects mode from TTY
run_cli(sys.argv[1:], render=render, fetch=fetch)

# With custom TUI handler
run_cli(
    sys.argv[1:],
    render=render,
    fetch=fetch,
    handlers={OutputMode.INTERACTIVE: lambda ctx: MyApp().run()},
)
```

### CLI Flags

```bash
myapp              # zoom=1 (SUMMARY), mode=AUTO
myapp -q           # zoom=0 (MINIMAL)
myapp -v           # zoom=2 (DETAILED)
myapp -vv          # zoom=3 (FULL)
myapp -i           # mode=INTERACTIVE (TUI)
myapp --static     # mode=STATIC (no animation)
myapp --live       # mode=LIVE (in-place updates)
myapp --json       # format=JSON (implies static)
myapp --plain      # format=PLAIN (implies static)
```

AUTO collapses to STATIC when: `--json`, `--plain`, `-q`, or pipe.
Flags are filtered by capability — only modes the CLI supports appear in `--help`.
See `docs/MODE_RESOLUTION.md` for full rules.

## Package Structure

Layered submodules — CLI core at top level, TUI features in subpackages:

```python
from painted import Style, Cell, Span, Line, Block, print_block  # CLI core
from painted import Zoom, OutputMode, Format, CliContext, run_cli # CLI harness
from painted import Palette, IconSet, current_palette, use_palette # Aesthetic
from painted.tui import Surface, Layer, Focus, Search             # Interactive apps
from painted.views import shape_lens, tree_lens, chart_lens        # Data rendering
from painted.views import flame_lens                               # Proportional viz
from painted.views import spinner, list_view, progress_bar         # Components
from painted.mouse import MouseEvent, MouseButton                 # Optional mouse
from painted.views import render_big                               # Visual effects
```

## Documentation

```
docs/
  ARCHITECTURE.md     # Stack visualization, data flow, layer pattern
  PRIMITIVES.md       # Quick reference for all primitives
  DATA_PATTERNS.md    # Frozen state + pure functions patterns
  MOUSE.md            # Terminal mouse protocol research
  VIEWPORT_DESIGN.md  # Scroll state management
  ZOOM_PATTERNS.md    # Lens zoom propagation patterns
  MODE_RESOLUTION.md  # AUTO mode collapse rules, capability filtering
  DEMO_PATTERNS.md    # TUI app pattern, demo organization
```

## Source Layout

```
src/painted/
  __init__.py       # CLI core exports + Palette/IconSet
  cell.py           # Cell, Style, EMPTY_CELL
  span.py           # Span, Line
  block.py          # Block, Wrap
  compose.py        # join, pad, border, truncate, Align
  borders.py        # BorderChars presets
  writer.py         # Writer, ColorDepth, print_block
  fidelity.py       # Zoom, OutputMode, Format, CliContext, run_cli (CLI harness)
  palette.py        # Palette (5 Style roles), ContextVar, presets
  icon_set.py       # IconSet (glyph vocabulary), ContextVar, ASCII fallback
  inplace.py        # InPlaceRenderer (cursor-controlled animation)
  big_text.py       # render_big implementation
  _lens.py          # Lens implementations (internal)
  _mouse.py         # Mouse implementations (internal)
  tui/              # Interactive app primitives
    __init__.py     # Buffer, Surface, Layer, Focus, Search, KeyboardInput
  lens/             # Data structure rendering
    __init__.py     # shape_lens, tree_lens, chart_lens, flame_lens
  widgets/          # Pre-built components
    __init__.py     # spinner, progress_bar, list_view, text_input, table
  mouse/            # Mouse support
    __init__.py     # MouseEvent, MouseButton, MouseAction
  effects/          # Visual effects
    __init__.py     # render_big, BigTextFormat
  components/       # Component implementations
    spinner.py, progress.py, list_view.py, text_input.py, table.py
```
