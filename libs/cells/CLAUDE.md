# CLAUDE.md — cells

Terminal UI framework built on cell buffers. Answers: **where is state displayed?**

## Build & Test

```bash
uv run --package cells pytest libs/cells/tests
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
state ──→ Lens.render(state, w, h) ──→ Block
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
| `Lens` | render function + max_zoom. `shape_lens` for convention-based rendering |

### Components
| Type | Purpose |
|------|---------|
| `SpinnerState` / `spinner` | animated spinner (DOTS, LINE, BRAILLE) |
| `ProgressState` / `progress_bar` | horizontal progress bar |
| `ListState` / `list_view` | scrollable list with selection |
| `TextInputState` / `text_input` | single-line input with cursor |
| `TableState` / `table` | scrollable table with headers |

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
- `shape_lens` renders any Python value at zoom levels 0 (minimal), 1 (summary), 2 (full).
- `Emit` is the feedback boundary — Surface emits observations that become Facts upstream.

## Pipeline Role

```
Projection.state ──→ Lens.render() ──→ Block ──→ Surface ──→ terminal
                                                    │
Surface.emit(kind, **data) ──→ Fact.of() ──→ Stream  (feedback loop)

Three emission strata:
  Raw input    (auto)  "ui.key"     {key: "j"}
  UI structure (auto)  "ui.action"  {action: "pop", layer: "confirm"}
  Domain       (manual) (any)    {item: "deploy-prod"}
```

## Source Layout

```
src/cells/
  cell.py           # Cell, Style, EMPTY_CELL
  span.py           # Span, Line
  buffer.py         # Buffer, BufferView, CellWrite
  block.py          # Block, Wrap
  borders.py        # BorderChars presets
  compose.py        # join, pad, border, truncate, Align
  region.py         # Region
  writer.py         # Writer, ColorDepth, print_block
  keyboard.py       # KeyboardInput
  focus.py          # Focus, FocusRing, ring/linear navigation
  search.py         # Search, filter_contains/prefix/fuzzy
  lens.py           # Lens, shape_lens
  layer.py          # Layer, Action (Stay/Pop/Push/Quit), process_key, render_layers
  app.py            # Surface, Emit
  theme.py          # Style constants (header, footer, levels, etc.)
  timer.py          # FrameTimer, FrameRecord (profiling)
  components/
    spinner.py      # SpinnerState, SpinnerFrames, spinner
    progress.py     # ProgressState, progress_bar
    list_view.py    # ListState, list_view
    text_input.py   # TextInputState, text_input
    table.py        # Column, TableState, table
tests/
  test_span.py      test_focus.py     test_search.py
  test_layer.py     test_lens.py      test_surface.py
```
