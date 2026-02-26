# View layer primitive vocabulary (Layer 3)

Date: 2026-02-23

## Goal

Answer: **what are the atomic views at Layer 3, and how should they be organized?**

Layer 3 is the “view” layer: functions that turn *data + constraints* into a `Block`, plus (for interactive views) the small state primitives that make that rendering meaningful (`*State` and its transition methods).

## The organizing axis (decision already made)

The primary mental model is **stateless vs stateful**, defined by the test:

> Does the developer make decisions that modify state in response to events?

- **Stateless views**: no event wiring; pure “inputs → `Block`”.
- **Stateful views**: developer wires events (keys, mouse, app actions) into state transitions; the view composes state primitives (`Cursor`, `Viewport`, etc.) and renders current state as a `Block`.

Clarification: “stateful” is about *interaction wiring*, not about whether the renderer accepts a `*State` argument. Many stateless views accept a `*State` (e.g. `SpinnerState`, `ProgressState`) but remain stateless in the Layer 3 sense.

Spinner is in the stateless bucket: it is a time-driven “animated indicator”, not interactive.

## 1) Inventory: validate stateless/stateful cut against current code

All existing view functions fit the cut cleanly once “stateful” is interpreted as “developer wires events → state transitions”.

### Stateless views (pure renderers)

| View | Current public module | Implementation | Notes |
|---|---|---|---|
| `shape_lens`, `SHAPE_LENS`, `Lens`, `NodeRenderer` | `painted.views` | `src/painted/_lens.py` | Zoomed “data → Block” renderer; pure. |
| `tree_lens`, `TREE_LENS` | `painted.views` | `src/painted/_lens.py` | Zoomed; optional `node_renderer` hook remains pure. |
| `chart_lens`, `CHART_LENS` | `painted.views` | `src/painted/_lens.py` | Zoomed; duplicates sparkline logic today (§3). |
| `render_big`, `BIG_GLYPHS`, `BigTextFormat` | `painted.views` | `src/painted/big_text.py` | Pure “text → Block”. |
| `sparkline`, `sparkline_with_range` | `painted.views` | `src/painted/_components/sparkline.py` | Pure “values → Block”; already uses contextvar theme by default. |
| `progress_bar` (+ `ProgressState`) | `painted.views` | `src/painted/_components/progress.py` | Pure render; “state” is just a value container. |
| `spinner` (+ `SpinnerState`, frames) | `painted.views` | `src/painted/_components/spinner.py` | Pure render; animation is driven by `SpinnerState.tick()` (time-based). |

### Stateful views (interactive components; caller wires events)

| View | Current public module | Implementation | Notes |
|---|---|---|---|
| `list_view` (+ `ListState`) | `painted.views` | `src/painted/_components/list_view.py` | Composes `Cursor + Viewport`. Caller maps keys to `move_up/down`, etc. |
| `table` (+ `TableState`, `Column`) | `painted.views` | `src/painted/_components/table.py` | Same pattern, row selection + scrolling. |
| `text_input` (+ `TextInputState`) | `painted.views` | `src/painted/_components/text_input.py` | Caller maps keys → insert/delete/move; state tracks cursor + scroll. |
| `data_explorer` (+ `DataExplorerState`, `DataNode`, `flatten`) | `painted.views` | `src/painted/_components/data_explorer.py` | Caller maps keys → navigation + expand/collapse; composes `Cursor + Viewport`. |

Flag: the “historical accident” was real: `painted.widgets` contained both stateless and stateful views, while `painted.lens` and `painted.effects` were also view layer packages.

## 2) Module structure recommendation

### Decision

Create a **single flat public namespace**: `painted.views`.

- The stateless/stateful split remains the **primary mental model** taught in documentation, but it is not a package boundary.
- With ~11 view functions, a single import path is simpler and more discoverable than subpackages.

### Public API shape (flat)

Recommended canonical imports:

```python
from painted.views import (
    # Stateless
    shape_lens,
    tree_lens,
    chart_lens,
    sparkline,
    sparkline_with_range,
    spinner,
    progress_bar,
    render_big,
    # Stateful
    ListState,
    list_view,
    Column,
    TableState,
    table,
    TextInputState,
    text_input,
    DataExplorerState,
    data_explorer,
)
```

What `painted.views` should export:

- All view functions listed above.
- The associated `*State` types and small types that are tightly coupled to those views (`Column`, `SpinnerFrames`, etc.).
- The lens support types/constants exported from `painted.views` (`Lens`, `NodeRenderer`, `*_LENS` constants) so “zoomable data views” remain first-class.

### Internal source organization (implementation detail)

`painted.views` should be a *package* (`src/painted/views/`) so growth stays easy, but keep the **public** namespace flat:

- `src/painted/views/__init__.py` re-exports the full public surface.
- Implementations may remain in existing internal modules initially, then be moved:
  - stateless: `src/painted/_lens.py`, `src/painted/big_text.py`, `src/painted/_components/sparkline.py`, etc.
  - stateful: `src/painted/_components/list_view.py`, etc.
- If the namespace grows, add private submodules (e.g. `src/painted/views/_stateless.py`) while still re-exporting from `painted.views` to avoid import churn.

## 3) Sparkline vs `chart_lens(zoom=1)` duplication

### Current state

`chart_lens(zoom=1)` implements its own sparkline algorithm in `src/painted/_lens.py` rather than composing `sparkline()` from `src/painted/_components/sparkline.py`.

The two differ in policy:

- `sparkline(values, width)`: tail semantics (truncate to last `width`, then left-pad).
- `chart_lens(values, zoom=1, width)`: overview semantics (uniform sampling across the full series when longer than `width`).

### Recommendation

Keep **both** public entrypoints, but eliminate duplicated math:

- Extract a single internal helper for “values → spark chars” (normalization + bucketing), e.g. `painted.views._sparkline_impl`.
- Parameterize sampling so both policies remain available:
  - `sparkline`: defaults to `sampling="tail"` (current behavior).
  - `chart_lens(zoom=1)`: uses `sampling="sample"` (current behavior).

This reduces maintenance surface while preserving distinct UX intent: “latest trend” vs “whole-series overview”.

## 4) Zoom is an axis, not a category

### Model

Zoom is a capability of *some stateless views* (“zoomable views”). It should not be a top-level package boundary.

### Recommendation

- Keep the established zoomable signature for lenses:
  - `(data, zoom, width, ...) -> Block`
- Do **not** add `zoom` to every view by default.
  - Add zoom only when it has a clear, stable meaning.
  - For interactive/stateful views, zoom is optional and should be introduced only when we have a coherent UX story for “what changes with zoom” (not because lenses have it).

## 5) Block vs paint: where Layer.render fits

### The split

- Layers render by **painting** into a `BufferView` (`Layer.render(..., buffer_view) -> None`).
- Views return immutable `Block`s.

### The bridge

The standard bridge is `Block.paint(buffer_or_view, x, y)` (`src/painted/block.py`).

### Recommendation

- Keep `Block` as the primary Layer 3 interface:
  - composable (join/pad/border/truncate),
  - testable (render output is data),
  - easy for both CLI and TUI use.
- A view may paint into a temporary `Buffer` internally (some already do), but should still return a `Block`.
- Only introduce a “paintable view” protocol if performance forces it; do not bifurcate the view API prematurely.

## 6) Theme as a cross-cutting concern

### Current inconsistency

Today, theming is a mix of:

- explicit `theme=...` parameters (e.g. `tree_lens`, `chart_lens`, `spinner`, `progress_bar`)
- implicit contextvar defaults via `component_theme()` (e.g. `sparkline`)
- hard-coded non-theme defaults (e.g. `progress_bar` uses green/dim when `theme is None`)

### Recommendation: one consistent pattern

Adopt a consistent rule:

1) If a view depends on **icons or semantic component styles**, it accepts `theme: ComponentTheme | None = None` (kw-only).
2) If `theme is None`, the view uses the contextvar default: `t = component_theme()`.
3) Styles and icon defaults come from `t` unless explicitly overridden by style/char kwargs.

This keeps “theme” both:
- easy to pass explicitly (tests/demos),
- and easy to set globally via `use_component_theme()` without threading it everywhere.

Views that don’t use icons/semantic styles (e.g. `render_big(style=...)`, `shape_lens(...)`) do not need to accept `theme`.

## 7) Migration path (clean break)

We are at 0.1.0: make a clean break with no compatibility shims.

### Steps

1) Introduce `painted.views` and make it the sole public “view layer” import path.
2) Delete public packages:
   - `painted.widgets`
   - `painted.lens`
   - `painted.effects`
3) Update all in-repo imports (docs, demos, tests) to `from painted.views import ...`.
4) Update the one external consumer (“loops”: 29 import sites across 13 files) to `from painted.views import ...`.

### What breaks

Only imports break; the underlying functions/types keep their names/signatures unless this doc explicitly calls out a cleanup.

Concrete mapping examples:

```python
# Old
from painted.views import list_view, ListState, chart_lens, render_big

# New
from painted.views import list_view, ListState, chart_lens, render_big
```

## Follow-ups (post-doc, implementation tasks)

1) Implement `painted.views` (flat exports) and delete legacy packages.
2) Normalize theming to use the contextvar default where applicable.
3) Deduplicate sparkline implementation (shared helper).
4) Update loops imports and run its integration tests.
