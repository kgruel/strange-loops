# HANDOFF

Session continuity for fidelis. See `CLAUDE.md` for API reference.

## What Is This

Cell-buffer terminal UI framework. Extracted from the loops monorepo
(`libs/cells/`) as a standalone package. Answers: **where is state displayed?**

**One dependency:** `wcwidth` (wide character width calculation).

## Current State

Clean. v0.1.0, 347 tests passing, pushed to `git@git.gruel.network:kaygee/fidelis.git`.

Post-extraction cleanup complete:
- All `cells` → `fidelis` renaming done (imports, docs, demos)
- Deprecated Fidelity API removed (Zoom/CliContext is the only API)
- `bench.py` renamed to `tour.py`
- Stale monorepo paths fixed throughout

## Relationship to Loops

fidelis is a path dependency from the loops monorepo:
- `apps/loops/pyproject.toml` → `fidelis = { path = "../../../fidelis" }`
- `apps/hlab/pyproject.toml` → `fidelis = { path = "../../../fidelis" }`
- loops imports `from fidelis import ...` (29 occurrences across 13 files)

## Structure

```
src/fidelis/           # 9,900 LOC
  Primitives:          Cell, Style, Span, Line, Block
  Composition:         join, pad, border, truncate, Align, Viewport
  Output:              Writer, print_block, InPlaceRenderer
  CLI Harness:         Zoom, OutputMode, Format, CliContext, run_cli
  TUI:                 Surface, Layer, Focus, Search, Buffer, KeyboardInput
  Lenses:              shape_lens, tree_lens, chart_lens
  Widgets:             spinner, progress_bar, list_view, text_input, table, sparkline, data_explorer
  Mouse:               MouseEvent, MouseButton, MouseAction
  Effects:             render_big
  Themes:              ComponentTheme, Icons

tests/                 # 347 tests, 14 files
demos/                 # 20 Python files + 4 markdown docs
  tour.py              # Interactive teaching platform (2D slide navigation)
  primitives/          # CLI demos (print and exit)
  apps/                # TUI demos (interactive)
  patterns/            # Real-world fidelity patterns
docs/                  # 7 design docs + plans/
```

## Next Steps

1. **Tour expansion** — tour.py covers primitives and basic components but is
   missing: lenses, mouse input, fidelity CLI harness, viewport/scroll,
   big_text/effects, layers/modal stack, themes, sparkline, data_explorer.
   Design doc needed before implementation.

## Open Threads

- **Theme system** — `themes/` subpackage exists with basic structure but no
  runtime theme registry yet. `component_theme.py` handles component-level
  theming. Full theme system deferred until patterns emerge.

- **Test gaps** — KeyboardInput has only 6 tests. Timer, Region, ComponentTheme
  untested. Low priority but noted.

- **PyPI publish** — Package metadata is ready. No CI/CD yet. Publish when
  the API stabilizes.
