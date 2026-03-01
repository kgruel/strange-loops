# CLAUDE.md — painted (contributor guide)

> **Using painted in your project?** See `src/painted/CLAUDE.md` for the consumer API guide.

## Build & Test

```bash
./dev check              # success gate: arch → ty + format → unit → golden
./dev test [-v]          # pytest wrapper, passthrough args
./dev lint               # ty check + ruff format check
./dev cov [--html]       # coverage report (target: ≥93%)
./dev fmt                # auto-format (ruff)
```

`./dev check` must pass before any commit. Lint is **ty** (type checking) + **ruff** (formatting only).

## Invariants

- All state types frozen. Components follow `State + render_fn(state, ...) -> Block` pattern.
- Surface diff-renders: only changed cells written to terminal.
- Layer stack: top handles keys, all render bottom-to-top. Base layer never pops.
- `shape_lens` auto-dispatches by data shape: numeric → chart, hierarchical → tree, else built-in rendering.
- `Emit` is the feedback boundary — Surface emits observations that become Facts upstream.

## Source Layout

```
src/painted/
  CLAUDE.md         # Consumer API guide (ships with package)
  __init__.py       # CLI core exports + Palette/IconSet + show()
  cell.py           # Cell, Style, EMPTY_CELL
  span.py           # Span, Line
  block.py          # Block, Wrap
  compose.py        # join, pad, border, truncate, Align
  borders.py        # BorderChars presets
  buffer.py         # Buffer, BufferView, CellWrite
  writer.py         # Writer, ColorDepth, print_block
  fidelity.py       # Zoom, OutputMode, Format, CliContext, run_cli (CLI harness)
  palette.py        # Palette (5 Style roles), ContextVar, presets
  icon_set.py       # IconSet (glyph vocabulary), ContextVar, ASCII fallback
  inplace.py        # InPlaceRenderer (cursor-controlled animation)
  big_text.py       # render_big implementation
  _lens.py          # Lens implementations (internal; re-exported via painted.views)
  _mouse.py         # Mouse protocol implementation (internal)
  _components/      # Stateful view implementations (internal; re-exported via painted.views)
    spinner.py, progress.py, list_view.py, text_input.py, table.py, sparkline.py, data_explorer.py
  tui/              # Interactive app primitives
    __init__.py     # Buffer, Surface, Layer, Focus, Search, KeyboardInput
  views/            # Public view-layer namespace (lenses + components + aesthetics)
    __init__.py     # shape_lens, tree_lens, chart_lens, flame_lens, spinner, etc.
  mouse/            # Mouse support
    __init__.py     # MouseEvent, MouseButton, MouseAction
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
