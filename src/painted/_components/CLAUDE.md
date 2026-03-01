# painted._components — Internal Implementation

**Import from `painted.views`, not here.** This is the internal implementation of stateful view components.

## Pattern

Each component follows the same structure:
1. Frozen `State` dataclass — created via constructor, updated via `dataclasses.replace()`
2. Pure render function — `fn(state, ...) → Block`

## File Map

| File | State | Render | Purpose |
|------|-------|--------|---------|
| `spinner.py` | `SpinnerState` | `spinner()` | Animated spinner (DOTS, LINE, BRAILLE frames) |
| `progress.py` | `ProgressState` | `progress_bar()` | Horizontal progress bar |
| `list_view.py` | `ListState` | `list_view()` | Scrollable list with selection |
| `text_input.py` | `TextInputState` | `text_input()` | Single-line input with cursor |
| `table.py` | `TableState` | `table()` | Scrollable table with Column headers |
| `sparkline.py` | — | `sparkline()` | Inline mini-chart (stateless) |
| `data_explorer.py` | `DataExplorerState` | `data_explorer()` | Interactive data browser |

## Public API

All exports are re-exported through `painted.views`. Consumers should never import from `painted._components` directly — the underscore prefix signals this is internal.
