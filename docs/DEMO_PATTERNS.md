# Demo Patterns

Findings and recommendations for the fidelis demo structure.

## 1. bench.py Completeness Analysis

### Current State

bench.py is a ~2880-line interactive teaching platform implementing:
- 2D slide navigation (left/right = topics, up/down = zoom levels)
- Layer stack (nav, help, search, demo focus)
- Interactive widget demos (spinner, progress, list, text input, table, focus navigation, search)
- Zoom levels per slide (0=summary, 1=detail, 2=source)
- Minimap sidebar
- Quiet mode for inline printing

### What's Present

| Feature | Status |
|---------|--------|
| Slide navigation | Complete |
| Zoom levels | Complete |
| Help overlay | Complete |
| Search overlay | Complete |
| Focus capture for widgets | Complete |
| CLI primitives coverage | Complete (Cell, Style, Span, Line, Block, Buffer, compose) |
| TUI primitives coverage | Complete (Surface, Layer, Focus, Search) |
| Widget demos | Complete (all 5 components) |
| Quiet mode | Complete |
| Fidelity flags | Complete |

### What's Missing

**Not actually missing — bench.py is functionally complete.** The gaps are pedagogical rather than structural:

1. **Mouse input**: No slides covering `fidelis.mouse`. The framework supports mouse but bench.py doesn't demonstrate it. Consider adding a "mouse" slide pointing to `demo_mouse.py`.

2. **Lens primitives**: No coverage of `fidelis.lens` (shape_lens, tree_lens, chart_lens). These render arbitrary Python data at different zoom levels. Could add a "lens" slide between "buffer" and "app".

3. **Effects**: No coverage of `fidelis.effects` (render_big). Low priority — visual flourish rather than core concept.

4. **Theme constants**: No explicit slide for the theme system. The styles are used but not explained.

### Completion Recommendations

To make bench.py a "complete" demo:

1. **Add mouse slide** after "components" — link to interactive demo
2. **Add lens slide** after "block" — show shape_lens at zoom 0/1/2
3. **Consider removing tour.py** — duplicates bench.py's purpose

bench.py already demonstrates the canonical TUI app pattern thoroughly. The missing pieces are additive, not structural.

---

## 2. Demo Directory Organization

### Current Structure (20 files)

```
demos/fidelis/
├── demo_01_cell.py       # CLI primitive
├── demo_02_buffer.py     # CLI primitive
├── demo_03_buffer_view.py # CLI primitive
├── demo_04_block.py      # CLI primitive
├── demo_05_compose.py    # CLI primitive
├── demo_06_span_line.py  # CLI primitive
├── demo_07_app.py        # TUI minimal
├── demo_08_components.py # TUI widgets
├── demo_09_layer.py      # TUI layer stack
├── demo_10_lens.py       # Data rendering
├── demo_big_text.py      # Effects
├── demo_lenses.py        # Interactive lens demo
├── demo_mouse.py         # Mouse input
├── demo_fidelity.py     # CLI→TUI spectrum
├── demo_fidelity_disk.py    # Variant
├── demo_fidelity_health.py  # Variant
├── demo_utils.py         # Helper
├── slide_loader.py       # Helper
├── bench.py              # Teaching platform
└── tour.py               # Alternative teaching platform
```

### Issues

1. **Mixed naming conventions**
   - Numbered: `demo_01_*` through `demo_10_*` (learning path)
   - Feature-named: `demo_mouse.py`, `demo_lenses.py`, `demo_big_text.py`
   - Variants: `demo_fidelity*.py` (3 files, one pattern)

2. **Unclear categories**
   - CLI-only demos mixed with TUI demos
   - Teaching tools (bench, tour) mixed with examples
   - Helpers (demo_utils, slide_loader) in same directory

3. **Redundancy**
   - `tour.py` duplicates bench.py's purpose
   - `demo_10_lens.py` and `demo_lenses.py` overlap

### Recommended Structure

```
demos/fidelis/
├── README.md                    # Demo index with descriptions
│
├── primitives/                  # CLI-level (run and exit)
│   ├── 01_cell_style.py        # Cell, Style
│   ├── 02_span_line.py         # Span, Line
│   ├── 03_block.py             # Block
│   ├── 04_buffer.py            # Buffer, BufferView
│   └── 05_compose.py           # join, pad, border
│
├── apps/                        # TUI applications (interactive)
│   ├── minimal.py              # Simplest Surface subclass
│   ├── layers.py               # Layer stack pattern
│   ├── widgets.py              # Component showcase
│   ├── mouse.py                # Mouse input
│   └── lenses.py               # Data visualization
│
├── patterns/                    # Real-world patterns
│   ├── fidelity.py            # CLI→TUI spectrum
│   ├── fidelity_disk.py       # Variant: disk monitor
│   └── fidelity_health.py     # Variant: health checker
│
└── bench.py                     # Teaching platform (keep at top level)
```

### Migration Strategy

1. **Keep bench.py at top level** — it's the primary entry point
2. **Delete tour.py** — superseded by bench.py
3. **Rename numbered demos** — use descriptive names
4. **Group by complexity** — primitives (CLI) vs apps (TUI) vs patterns (real-world)
5. **Add README.md** — index with run commands and descriptions

### Naming Convention

| Category | Pattern | Example |
|----------|---------|---------|
| Primitives | `{concept}.py` | `block.py` |
| Apps | `{feature}.py` | `layers.py` |
| Patterns | `{pattern}_{variant}.py` | `fidelity_disk.py` |

No numbered prefixes — use README for learning path ordering.

---

## 3. TUI App Pattern

### The Canonical Structure

Based on bench.py, demo_09_layer.py, and demo_lenses.py, the pattern for TUI apps using fidelis submodules:

```python
#!/usr/bin/env python3
"""One-line description.

Detailed usage and controls.

Run: uv run python demos/fidelis/{name}.py
"""

import asyncio
from dataclasses import dataclass, replace

# CLI core — always available
from fidelis import Block, Style, join_vertical, pad, border, ROUNDED

# TUI primitives — for interactive apps
from fidelis.tui import (
    Surface,              # Base class
    Layer, Stay, Pop, Push, Quit,  # Modal stack
    process_key, render_layers,     # Layer helpers
    Focus,                # Focus state
    Search,               # Search state
)

# Widgets — optional, when needed
from fidelis.widgets import spinner, progress_bar, list_view

# Optional imports based on features
# from fidelis.lens import shape_lens, tree_lens
# from fidelis.mouse import MouseEvent, MouseButton
# from fidelis.effects import render_big


# ─── State ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AppState:
    """All application state. Immutable."""

    # Core state
    value: int = 0

    # Layer stack (required for layer pattern)
    layers: tuple[Layer, ...] = ()

    # Terminal dimensions (for layers)
    width: int = 80
    height: int = 24


# ─── Layer Accessors ─────────────────────────────────────────────────

def get_layers(state: AppState) -> tuple[Layer, ...]:
    return state.layers

def set_layers(state: AppState, layers: tuple[Layer, ...]) -> AppState:
    return replace(state, layers=layers)


# ─── Layers ──────────────────────────────────────────────────────────

def handle_base(key: str, layer_state: None, app_state: AppState):
    """Base layer input handler."""
    if key == "q":
        return None, app_state, Quit()
    # ... handle other keys
    return None, app_state, Stay()

def render_base(layer_state: None, app_state: AppState, view):
    """Base layer renderer."""
    # Paint blocks into view
    title = Block.text("Title", Style(bold=True))
    title.paint(view, 2, 1)

def make_base_layer() -> Layer[None]:
    return Layer(name="base", state=None, handle=handle_base, render=render_base)


# ─── App ─────────────────────────────────────────────────────────────

class MyApp(Surface):
    """Application class."""

    def __init__(self):
        super().__init__(fps_cap=30)  # or enable_mouse=True
        self._state = AppState(layers=(make_base_layer(),))

    def layout(self, width: int, height: int) -> None:
        self._state = replace(self._state, width=width, height=height)

    def update(self) -> None:
        """Advance animations. Call mark_dirty() if state changed."""
        pass

    def render(self) -> None:
        self._buf.fill(0, 0, self._state.width, self._state.height, " ", Style())
        render_layers(self._state, self._buf, get_layers)

    def on_key(self, key: str) -> None:
        self._state, should_quit, _ = process_key(
            key, self._state, get_layers, set_layers
        )
        if should_quit:
            self.quit()


# ─── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(MyApp().run())
```

### Key Invariants

1. **State is frozen** — all dataclasses use `frozen=True`
2. **Layer stack lives in app state** — not managed by Surface
3. **Accessors are functions** — `get_layers`, `set_layers` passed to process_key
4. **Layer handlers return tuple** — `(new_layer_state, new_app_state, action)`
5. **Actions are values** — Stay(), Pop(result), Push(layer), Quit()
6. **render_layers handles stack** — bottom-to-top, all layers render
7. **mark_dirty() for animation** — call from update() when state changes

### Import Tiers

```python
# Tier 1: CLI scripts (no async, print and exit)
from fidelis import Block, Style, Span, Line, print_block

# Tier 2: Interactive TUI (async, input loop)
from fidelis.tui import Surface, Layer, Focus, Search

# Tier 3: Optional extensions
from fidelis.widgets import spinner, list_view, progress_bar
from fidelis.lens import shape_lens, tree_lens
from fidelis.mouse import MouseEvent, MouseButton
from fidelis.effects import render_big
```

### Simpler Pattern (No Layers)

For simple apps without modals:

```python
class SimpleApp(Surface):
    def __init__(self):
        super().__init__()
        self.x = 0
        self.y = 0

    def layout(self, width, height):
        self.width = width
        self.height = height

    def render(self):
        self._buf.fill(0, 0, self.width, self.height, " ", Style())
        Block.text("Hello", Style(bold=True)).paint(self._buf, self.x, self.y)

    def on_key(self, key):
        if key == "q":
            self.quit()
        elif key == "right":
            self.x += 1
```

Use the simpler pattern for:
- Demos of specific features
- Single-purpose tools
- Prototypes

Use the layer pattern for:
- Help overlays
- Settings modals
- Confirmation dialogs
- Search/jump interfaces

---

## Summary

| Question | Answer |
|----------|--------|
| Is bench.py complete? | Yes, functionally complete. Could add mouse/lens/effects slides. |
| How to restructure demos? | Group by CLI/TUI/patterns. Remove tour.py. Add README index. |
| What's the TUI app pattern? | Frozen state + layer stack + process_key + render_layers |
