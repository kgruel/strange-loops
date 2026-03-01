# painted.views — Data Rendering

Lenses (stateless) and components (frozen state + pure render). Import everything from here.

## Lenses

Stateless functions: `fn(data, zoom, width) → Block`.

```python
from painted.views import shape_lens, tree_lens, chart_lens, flame_lens, sparkline
```

- **`shape_lens`** — auto-dispatch by data shape. This is the default in `show()`. Dict → key-value, list → items, numeric → chart, nested → tree.
- **`tree_lens`** — hierarchical data with expand/collapse.
- **`chart_lens`** — numeric data as horizontal bar charts.
- **`flame_lens`** — proportional visualization (flame graph style).
- **`sparkline`** / **`sparkline_with_range`** — inline mini-charts from numeric sequences.
- **`NodeRenderer`** — callback protocol for custom tree node rendering.

## Components

Frozen state + pure render function. Pattern: `State + render_fn(state, ...) → Block`.

```python
from painted.views import SpinnerState, spinner, DOTS
from painted.views import ProgressState, progress_bar
from painted.views import ListState, list_view
from painted.views import TableState, Column, table
from painted.views import TextInputState, text_input
from painted.views import DataExplorerState, data_explorer
```

- **`spinner(state) → Block`** — animated spinner. Frames: `DOTS`, `LINE`, `BRAILLE`.
- **`progress_bar(state) → Block`** — horizontal progress bar.
- **`list_view(state, items, render_item) → Block`** — scrollable list with selection.
- **`table(state, rows, columns) → Block`** — scrollable table with headers.
- **`text_input(state) → Block`** — single-line input with cursor.
- **`data_explorer(state) → Block`** — interactive data browser.

State is created via constructor, updated via `dataclasses.replace()`. All state types are frozen.

## Aesthetic

Contextual defaults via ContextVar — set globally or scoped via context manager.

```python
from painted.views import Palette, use_palette, current_palette, DEFAULT_PALETTE, NORD_PALETTE, MONO_PALETTE
from painted.views import IconSet, use_icons, current_icons, ASCII_ICONS
```

- **`Palette`** — 5 semantic Style roles: `success`, `warning`, `error`, `accent`, `muted`.
- **`IconSet`** — named glyph slots: spinner, progress, tree, sparkline.
- `use_palette()` / `use_icons()` — setter (no arg = get current) or context manager (scoped override).

## Visual effects

```python
from painted.views import render_big, BigTextFormat, BIG_GLYPHS
```

`render_big(text, style)` — large block-character text.

## Profile bridge

```python
from painted.views import profile, parse_collapsed, ProfileResult
```

Flamegraph-compatible profiling utilities.
