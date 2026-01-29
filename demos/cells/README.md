# cells demos

Demonstrations of the cells library, organized by complexity.

## Quick Start

```bash
# Run the interactive teaching platform
uv run python demos/cells/bench.py

# Run a primitive demo (CLI, prints output)
uv run python demos/cells/primitives/cell.py

# Run an app demo (TUI, interactive)
uv run python demos/cells/apps/minimal.py
```

## Structure

```
demos/cells/
├── bench.py              # Interactive teaching platform
├── primitives/           # CLI demos (print and exit)
├── apps/                 # TUI demos (interactive)
└── patterns/             # Real-world patterns
```

## Primitives

Non-interactive demos that demonstrate core concepts. Run these to understand the building blocks.

| File | Concept | Run |
|------|---------|-----|
| `cell.py` | Cell + Style: the atomic unit | `uv run python demos/cells/primitives/cell.py` |
| `buffer.py` | Buffer: the 2D canvas | `uv run python demos/cells/primitives/buffer.py` |
| `buffer_view.py` | BufferView: clipped regions | `uv run python demos/cells/primitives/buffer_view.py` |
| `block.py` | Block: immutable rectangles | `uv run python demos/cells/primitives/block.py` |
| `compose.py` | Composition: join, pad, border | `uv run python demos/cells/primitives/compose.py` |
| `span_line.py` | Span + Line: styled text | `uv run python demos/cells/primitives/span_line.py` |

**Learning path:** cell → buffer → buffer_view → block → compose → span_line

## Apps

Interactive TUI applications demonstrating different features.

| File | Feature | Run |
|------|---------|-----|
| `minimal.py` | Simplest Surface app | `uv run python demos/cells/apps/minimal.py` |
| `widgets.py` | Component showcase | `uv run python demos/cells/apps/widgets.py` |
| `layers.py` | Modal layer stack | `uv run python demos/cells/apps/layers.py` |
| `lens.py` | Shape lens zooming | `uv run python demos/cells/apps/lens.py` |
| `lenses.py` | Tree + Chart lenses | `uv run python demos/cells/apps/lenses.py` |
| `mouse.py` | Mouse input canvas | `uv run python demos/cells/apps/mouse.py` |
| `big_text.py` | Block character rendering | `uv run python demos/cells/apps/big_text.py` |

## Patterns

Real-world patterns showing the CLI→TUI spectrum.

| File | Pattern | Run |
|------|---------|-----|
| `verbosity.py` | Task runner at 4 verbosity levels | `uv run python demos/cells/patterns/verbosity.py -vv` |
| `verbosity_disk.py` | Disk usage browser | `uv run python demos/cells/patterns/verbosity_disk.py -vv` |
| `verbosity_health.py` | Health check dashboard | `uv run python demos/cells/patterns/verbosity_health.py -vv` |

Each verbosity demo supports:
- `-q` : One-line summary
- (default) : Standard output
- `-v` : Styled output
- `-vv` : Interactive TUI

## Teaching Platform

`bench.py` is the primary entry point for learning cells. It provides:
- 2D slide navigation (←→ topics, ↑↓ zoom levels)
- Interactive widget demos
- Source code exploration
- Help overlay (press `?`)
- Search/jump (press `/`)

```bash
uv run python demos/cells/bench.py
```
