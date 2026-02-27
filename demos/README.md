# painted demos

Demonstrations of the painted library, organized by complexity.

## Quick Start

```bash
# Run the interactive teaching platform
uv run python demos/tour.py

# Run a primitive demo (CLI, prints output)
uv run python demos/primitives/cell.py

# Run an app demo (TUI, interactive)
uv run python demos/apps/minimal.py
```

## Structure

```
demos/
├── tour.py              # Interactive teaching platform
├── primitives/           # CLI demos (print and exit)
├── apps/                 # TUI demos (interactive)
└── patterns/             # Real-world patterns
```

## Primitives

Non-interactive demos that demonstrate core concepts. Run these to understand the building blocks.

| File | Concept | Run |
|------|---------|-----|
| `cell.py` | Cell + Style: the atomic unit | `uv run python demos/primitives/cell.py` |
| `buffer.py` | Buffer: the 2D canvas | `uv run python demos/primitives/buffer.py` |
| `buffer_view.py` | BufferView: clipped regions | `uv run python demos/primitives/buffer_view.py` |
| `block.py` | Block: immutable rectangles | `uv run python demos/primitives/block.py` |
| `compose.py` | Composition: join, pad, border | `uv run python demos/primitives/compose.py` |
| `span_line.py` | Span + Line: styled text | `uv run python demos/primitives/span_line.py` |

**Learning path:** cell → buffer → buffer_view → block → compose → span_line

## Apps

Interactive TUI applications demonstrating different features.

| File | Feature | Run |
|------|---------|-----|
| `minimal.py` | Simplest Surface app | `uv run python demos/apps/minimal.py` |
| `widgets.py` | Component showcase | `uv run python demos/apps/widgets.py` |
| `layers.py` | Modal layer stack | `uv run python demos/apps/layers.py` |
| `lens.py` | Shape lens zooming | `uv run python demos/apps/lens.py` |
| `lenses.py` | Tree + Chart lenses | `uv run python demos/apps/lenses.py` |
| `mouse.py` | Mouse input canvas | `uv run python demos/apps/mouse.py` |
| `big_text.py` | Block character rendering | `uv run python demos/apps/big_text.py` |

## Patterns

Real-world patterns showing lens selection and the CLI→TUI spectrum.

| File | Pattern | Run |
|------|---------|-----|
| `rendering.py` | Rendering patterns: lens API, custom render, palette | `uv run python demos/patterns/rendering.py` |
| `fidelity.py` | CLI harness at 4 zoom levels | `uv run python demos/patterns/fidelity.py -vv` |
| `live.py` | Live streaming: fetch_stream + spinners | `uv run python demos/patterns/live.py` |

The fidelity demo supports:
- `-q` : One-line summary
- (default) : Directory list
- `-v` : Styled bars
- `-vv -i` : Interactive tree browser

## Teaching Platform

`tour.py` is the primary entry point for learning painted. It provides:
- 2D slide navigation (←→ topics, ↑↓ zoom levels)
- Interactive widget demos
- Source code exploration
- Help overlay (press `?`)
- Search/jump (press `/`)

```bash
uv run python demos/tour.py
```
