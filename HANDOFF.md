# Handoff: Render Layer CLI Framework

## Summary

Cell-buffer terminal rendering engine (`render/`) — Python equivalent of Ratatui (buffer+diff) + Lip Gloss (styled composition) + Bubbles (interactive components). First real app (streaming log viewer) running against live infrastructure. Performance: 7.3ms avg frame at 2800+ items.

**Three-level composition vocabulary:**
- **Span** — styled text run (atom)
- **Line** — sequence of spans (inline composition, the workhorse)
- **Block** — 2D cell grid (spatial composition: borders, padding, joins)

The paint boundary (Line.paint / Block.paint → BufferView) is where Cells get created — exactly once, in their final location. Apps compose descriptions above this boundary, never below.

The framework layer (`framework/`) provides event-sourcing, projections, and reactive signals for complex dashboards. Conceptually independent, but currently two cross-imports exist (see P1 below).

## Milestone Status

| Milestone | Status | Notes |
|-----------|--------|-------|
| R1: Buffer + Diff + Writer | **Done** | Cell, Style, Buffer, BufferView, diff, Writer, Mode 2026 |
| R2: Styling + Composition | **Done** | Block (2D grid), join, pad, border, truncate, Wrap modes |
| R2.5: Description Layer | **Done** | Span + Line (frozen dataclasses) — inline text, paint boundary |
| R3: Components | **Done** | Frozen state + transitions + render: Spinner, Progress, List, TextInput, Table |
| R4: App integration | **Done** | RenderApp, FocusRing, Region, update/render/on_key lifecycle |
| R4.5: Real app | **Done** | Logs viewer (apps/logs.py) — SSH streaming, filtering, level toggles |
| R4.6: Performance | **Done** | Profiling infra (FrameTimer), visible-window rendering, drain-all-keys |
| R4.7: Logs → Span/Line | **Done** | All rendering via Line/Span, no Block in the render path |
| R5: Theming + API | **Done** | render/theme.py, Line.plain(), components accept Line items |
| R6: Demo + Cleanup | **Done** | Project cleanup (archives removed), progressive demo walkthrough |
| M0-M3: Framework | **Done** | EventStore, Projections, BaseApp, debug panel, idle-gated rendering |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Apps (apps/)                                            │
│  Real tools: SSH streaming, filtering, keyboard nav      │
│  extend RenderApp, own their state + async I/O           │
├─────────────────────────────────────────────────────────┤
│  Theme (render/theme.py)                                 │
│  Named style constants. Apps import, never inline Style. │
├─────────────────────────────────────────────────────────┤
│  Description Layer — Span/Line (render/span.py)          │
│  Lightweight: (str, Style) pairs. Line.plain() for text. │
│  Line.paint() is the cell-creation boundary.             │
├─────────────────────────────────────────────────────────┤
│  Block Layer — Block (render/block.py)                   │
│  Retained 2D cell grid: borders, padding, multi-line.    │
│  Escape hatch for spatial composition (joins, chrome).   │
├─────────────────────────────────────────────────────────┤
│  Buffer Layer (render/buffer.py, writer.py)              │
│  Cell grid, diff, ANSI output. The frame buffer.         │
├─────────────────────────────────────────────────────────┤
│  Framework (framework/) — optional                       │
│  EventStore, Projections, Signals — for complex dashboards│
└─────────────────────────────────────────────────────────┘
```

**Actual dependency structure:**
- `apps/` → `render/` only (logs.py, demo.py)
- `examples/` → `framework/` only (Rich-based, separate product line)
- `render/app.py` → `framework.keyboard` (single import, the coupling point)
- `framework/debug.py` → `render` (Block, Style, compose functions)
- `framework/keyboard.py` has zero internal dependencies (pure stdlib)

**When to use what:**
- **Line** (90% of cases): log rows, status bars, table cells, list items. Left-to-right styled text. No Cells until paint.
- **Block** (escape hatch): bordered panels, side-by-side panes, multi-line widgets that need spatial composition.

## Performance

**After Span/Line refactor (2800+ items):**

| Metric | StyledBlock path | Line path |
|--------|-----------------|-----------|
| Avg frame time | 12.7ms | 7.3ms |
| Avg build+paint | ~5ms (build+list+paint) | 2.9ms (m.build) |

Elimination of intermediate allocations: no Block per row, no join_horizontal, no list_view wrapper. Lines paint directly into BufferView.

**Profiling infrastructure** (`render/timer.py`):
- `FrameTimer` — per-phase `perf_counter` timing with context manager API
- Live debug overlay — toggle with `d` key, shows last/avg/max per phase
- `--profile PATH` — dumps all frames as JSONL for post-hoc analysis

## Component APIs

Components accept `Line` for item content:

```python
# list_view — items are Lines
items = [Line.plain(name) for name in names]
block = list_view(state, items, height, selected_style=Style(bg=237))

# table — cells and headers are Lines
columns = [Column(header=Line.plain("Name"), width=12)]
rows = [[Line.plain("Alice")], [Line.plain("Bob")]]
block = table(state, columns, rows, height)

# Styled items
line = Line((Span(source, Style(fg="cyan")), Span(msg, Style(dim=True))))
```

Selection highlighting: Line's base `style` merges onto each Span at paint time. `Line(item.spans, style=highlight)` highlights without rebuilding spans.

## Known Contracts

### Subprocess stdin isolation
Any RenderApp that spawns subprocesses MUST use `stdin=asyncio.subprocess.DEVNULL`. The app owns the terminal in alt-screen/cbreak mode.

### Keyboard API
`KeyboardInput.get_key()` returns named strings or single characters. Escape sequences are parsed atomically (5ms timeout) and fully drained — unrecognized sequences are consumed without leaving garbage in the input buffer. Multi-byte UTF-8 characters are assembled from continuation bytes.

Named keys: `"up"`, `"down"`, `"left"`, `"right"`, `"home"`, `"end"`, `"escape"`, `"enter"`, `"backspace"`, `"tab"`, `"shift_tab"`, `"delete"`, `"insert"`, `"page_up"`, `"page_down"`, `"f1"`-`"f4"`.

Handles: CSI sequences (ESC [), SS3 sequences (ESC O), parameterized sequences (ESC [3~, etc.).

### RenderApp main loop
- Drains ALL available keys per frame
- Adaptive sleep: 1ms when keys/dirty, 33ms (1/fps) when idle
- update() for async state, render() for painting, on_key() for input

### Two rendering modes

The demo surfaces a pattern worth naming:

- **Compose mode** (stages 1-5): Build Blocks with `join_*`, `pad`, `border`, return a Block. Static layout, declarative. The framework paints it.
- **Canvas mode** (finale): Create a `Buffer(w, h)`, paint elements at computed `(x, y)` positions, convert to Block. Absolute positioning, animation-friendly. `update()` drives time-varying state, `render()` computes positions/styles from that state.

Both modes return a Block from the render function — the app lifecycle doesn't change. Canvas mode is the escape hatch when compose's left-to-right/top-to-bottom isn't enough (animation, overlapping elements, physics).

### Paint boundary
`Line.paint(view, x, y)` and `Block.paint(view, x, y)` are where Cells get created. Style merge: `Line.style.merge(span.style)` — span fields override base when non-None/non-False.

### Theme
`render/theme.py` — module-level `Style` constants. Apps import named styles, never construct `Style(...)` inline (except `Style()` for null/default and dynamic per-source colors).

## Current State

| Component | Purpose |
|-----------|---------|
| `apps/demo.py` | **Progressive demo** — 7-stage walkthrough, animated finale, touches all layers |
| `apps/logs.py` | **First real app** — streaming SSH log viewer, Line-based rendering |
| `render/span.py` | **Span + Line**: description layer, `Line.plain()`, paint boundary |
| `render/theme.py` | **Theme**: named style constants for the render layer |
| `render/app.py` | RenderApp: adaptive sleep, drain-all-keys, update/render/on_key |
| `render/timer.py` | FrameTimer: per-phase profiling, debug overlay, JSONL dump |
| `render/cell.py` | Cell, Style, EMPTY_CELL |
| `render/buffer.py` | Buffer, BufferView, diff |
| `render/writer.py` | ANSI output, Mode 2026, alt screen |
| `render/block.py` | Block (was StyledBlock), Wrap modes |
| `render/compose.py` | join_horizontal, join_vertical, pad, border, truncate, Align |
| `render/borders.py` | BorderChars presets (ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII) |
| `render/components/` | Line-based: list_view, table. Block-based: spinner, progress, text_input |
| `render/focus.py` | FocusRing |
| `render/region.py` | Region → BufferView |
| `framework/keyboard.py` | KeyboardInput: cbreak mode, CSI/SS3 drain, UTF-8 assembly |
| `framework/` | EventStore, Projections, BaseApp, debug panel, simulators |

## Next Steps

### P1 — Architecture

1. **Break render↔framework coupling** — `render/app.py:10` imports `framework.keyboard.KeyboardInput`. `framework/debug.py:10` imports render primitives. `KeyboardInput` is pure terminal I/O (stdlib only) — it belongs in `render/` or a shared `terminal/` leaf module. This makes render self-contained and framework independently packageable.

2. **Decide framework rendering strategy** — `framework/ui.py` returns Rich renderables. `framework/debug.py` returns `render.Block`. `examples/` use Rich. Either: keep framework Rich-based and add a Block→Rich adapter, or fully port framework to the render layer. Currently the migration state is ambiguous.

### P2 — Polish

3. **Cache `filtered_lines()` per frame** — `apps/logs.py` calls `filtered_lines()` multiple times per render (header, main, debug). Cache the result per frame to avoid repeated scans.

4. **Spinner/Progress → Line** — These still return Block. Evaluate whether they should return Line (spinner is 1 char, progress is a single row).

## Run

```bash
# Demo walkthrough (start here)
uv run python -m apps.demo              # ←/→ pages, interactive stages, animated finale

# Real apps
uv run python -m apps.logs infra --host 192.168.1.30 -i ~/.ssh/homelab_deploy
uv run python -m apps.logs infra --host 192.168.1.30 -s traefik --level error,warn
uv run python -m apps.logs infra --host 192.168.1.30 --profile /tmp/frames.jsonl  # d=overlay

# Render layer demos (developer verification, predate the walkthrough)
uv run -m render.demo_app             # Interactive: list + input + spinner
uv run -m render.demo_components      # Component assertions + composed layout
uv run -m render.demo_compose         # Composition operations

# Framework examples (Rich-based, predates render layer)
uv run examples/process_manager.py    # Press D for debug pane
uv run examples/dashboard.py          # Multi-source event aggregation
```

## See Also

- `IDEAS.md` — CLI harness concept, ev dissolution reasoning
- `CLAUDE.md` — project conventions and branching workflow
- `docs/composition-journey.md` — full research journey: profiling → Layer 3 design decisions
- `docs/composition-research.md` — Ratatui, Lip Gloss, Rich/Textual comparison
- `docs/render-layer.md` — render layer reference (primitives, data flow, contracts)
