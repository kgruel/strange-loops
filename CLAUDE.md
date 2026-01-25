# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install dependencies (uses uv)
uv sync

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_span.py

# Run a specific test
uv run pytest tests/test_span.py::TestSpanWidth::test_ascii
```

## Architecture

`cells` is a cell-buffer terminal UI framework. The rendering model follows a layered architecture:

### Core Primitives (bottom-up)
- **Cell/Style** (`cell.py`) — atomic unit: one character + style (colors, bold, etc.). Immutable.
- **Buffer/BufferView** (`buffer.py`) — 2D grid of Cells. BufferView provides clipped coordinate-translated regions.
- **Block** (`block.py`) — immutable rectangle of Cells with known dimensions. Supports text wrapping modes.
- **Span/Line** (`span.py`) — styled text primitives. Line is a sequence of Spans that can paint to BufferView.

### Composition Layer
- **compose.py** — `join_horizontal`, `join_vertical`, `pad`, `border`, `truncate` for combining Blocks.
- **borders.py** — border character sets (ROUNDED, HEAVY, DOUBLE, etc.).

### Application Layer
- **RenderApp** (`app.py`) — async main loop base class. Handles alternate screen, keyboard input, resize (SIGWINCH), and diff-based rendering.
- **Writer** (`writer.py`) — ANSI escape sequence output and terminal size detection.
- **KeyboardInput** (`keyboard.py`) — non-blocking keyboard reader.
- **FocusRing** (`focus.py`) — component focus management.

### Components (`components/`)
Stateful UI widgets: `spinner`, `progress_bar`, `list_view`, `text_input`, `table`. Each has a State dataclass and a render function that returns a Block.

### Rendering Flow
1. `RenderApp.run()` enters alt screen, creates Buffer
2. On each frame: `update()` → `render()` → `_flush()`
3. `render()` paints Blocks into `self._buf`
4. `_flush()` diffs against previous buffer, writes only changed cells via ANSI escapes

### Key Patterns
- Blocks are immutable; compose them via functions, don't mutate
- BufferView clips writes automatically — paint without bounds checking
- Wide character support via `wcwidth`
