# cells — Handoff

## 2026-01-26
Feedback loop: RenderApp renamed to Surface. Added Emit protocol
(`Callable[[str, dict], None]`) with three emission strata — raw input
(key), UI structure (action, resize), domain (subclass-emitted).
`Surface.handle_key()` wraps `process_key()` with action auto-emission.
No cross-lib imports; integration layer wires to Fact.of() + Stream.emit().

Python minimum bumped from 3.10 to 3.11 (aligning with all other libs).
Added `py.typed` marker and `[tool.pytest.ini_options]`.

## Resolved (2026-01-29)
- ~~Mouse/trackpad input~~ — Implemented. SGR mouse protocol, Surface opt-in.
- ~~ShapeLens extensions~~ — Implemented. `tree_lens`, `chart_lens`.
- ~~CLI -> TUI continuum~~ — Implemented. Verbosity spectrum pattern with demos.
## 2026-01-29

### Mouse Support
Full SGR mouse protocol implementation:
- `MouseEvent`, `MouseButton`, `MouseAction` types in `mouse.py`
- SGR parsing integrated into `KeyboardInput` — `get_input()` returns `str | MouseEvent`
- `Writer.enable_mouse()` / `disable_mouse()` for tracking modes
- `Surface(enable_mouse=True)` opt-in with `on_mouse()` callback
- Research documented in `docs/MOUSE.md`
- Demo: `demos/cells/demo_mouse.py` (drawable canvas)

### Lens Extensions
Two new lenses following `shape_lens` pattern:
- `tree_lens(data, zoom, width)` — nested dicts/objects as indented trees with `├─└─│`
- `chart_lens(data, zoom, width)` — numeric data as sparklines (`▁▂▄▆█`) or bar charts
- Zoom controls depth (tree) or detail level (chart)
- Demo: `demos/cells/demo_lenses.py`

### Verbosity Spectrum Pattern
CLI→TUI progression: same data, different render paths based on verbosity:
- `-q` minimal, default standard, `-v` styled, `-vv` interactive TUI
- `experiments/verbosity/` with common utilities
- Demos: `demo_verbosity.py` (build status), `demo_verbosity_health.py` (API health),
  `demo_verbosity_disk.py` (disk usage with file tree browser)

### Big Text Rendering
`render_big(text, style, size=1, format=BigTextFormat.FILLED) -> Block`
- Two sizes: size=1 (3-row), size=2 (5-row)
- Two formats: `FILLED` (solid blocks), `OUTLINE` (box-drawing)
- Glyph coverage: a-z, 0-9, 30+ symbols
- Demo: `demos/cells/demo_big_text.py`

### Code Review
Deep review of all additions completed. High-priority fixes in progress:
1. Mouse scroll button fallback (arbitrary default)
2. Unused TYPE_CHECKING import in big_text.py
3. Missing modifiers in mouse emit

### Architecture Layering
Reorganized into layered submodules:
```
cells                # CLI core: Style, Cell, Span, Line, Block, composition, Writer, theme
cells.tui            # Interactive: Buffer, Surface, Layer, Focus, Search, KeyboardInput
cells.lens           # Data rendering: shape_lens, tree_lens, chart_lens
cells.widgets        # Components: spinner, progress_bar, list_view, text_input, table
cells.mouse          # Optional: MouseEvent, MouseButton, MouseAction
cells.effects        # Visual: render_big
```
Internal implementations use underscore prefix (`_mouse.py`, `_lens.py`).

### Viewport Dataclass
`Viewport(offset, visible, content)` for scroll state management:
- scroll(), page_up/down(), home/end(), scroll_to()
- scroll_into_view(index) — ensures item visible
- with_content(), with_visible() — dimension updates that auto-clamp
- Works with vslice() for rendering visible portion

### Zoom Propagation
Research completed, pattern documented in `experiments/ZOOM_PATTERNS.md`:
- **Global zoom with per-lens overrides** (not pure independent)
- Per-peer defaults separate render function (library) from view config (app)
- Zoom and width orthogonal — truncate, don't auto-reduce
- Added `Lens.default_zoom` as optional metadata hint

### Demo Restructure
Reorganized `demos/cells/` by complexity:
```
demos/cells/
├── bench.py           # Teaching platform (top-level entry)
├── README.md          # Index with descriptions and run commands
├── primitives/        # CLI demos (cell, span, block, buffer, compose)
├── apps/              # TUI demos (minimal, layers, widgets, mouse, lenses)
└── patterns/          # Real-world patterns (verbosity spectrum)
```
Deleted tour.py (superseded by bench.py). Pattern documented in `experiments/DEMO_PATTERNS.md`.

## Resolved (2026-01-29 cont.)
- ~~Arrow keys broken~~ — CSI parsing bug: `_read_csi()` assumed parameter bytes before final byte.
  For simple sequences (ESC [ A), the first byte IS the final byte. Fixed by checking before loop.
- ~~test_lifecycle hanging~~ — Test mocked `get_key` but Surface calls `get_input`. Fixed.
- ~~bench.py escape quits~~ — Changed to go back (reduce zoom, or parent slide) instead of quit.

## Resolved (earlier)
- ~~Code review fixes~~ — Fixed in 5e8558c: mouse scroll returns None for unknown values,
  removed unused TYPE_CHECKING import from big_text.py, added modifiers to mouse emit.

## Open
(none)
