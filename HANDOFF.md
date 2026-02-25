# HANDOFF

Session continuity for fidelis. See `CLAUDE.md` for API reference.

## What Is This

Cell-buffer terminal UI framework. Extracted from the loops monorepo
(`libs/cells/`) as a standalone package. Answers: **where is state displayed?**

**One dependency:** `wcwidth` (wide character width calculation).

## Current State

v0.1.0, 544 tests passing, pushed to `git@git.gruel.network:kaygee/fidelis.git`.

Fidelity-aware style resolution **implemented and merged**: `Palette`
(5 semantic Style roles) + `IconSet` (glyph vocabulary), both ambient via
ContextVar. `themes/` and `ComponentTheme` deleted.

**Capability signal question resolved** via design council: the question
dissolved. Capabilities resolve at boundaries (Writer), not in pipelines
(views). Color downconversion implemented in `Writer._color_codes()`. Design
doc at `docs/plans/2026-02-25-capability-signal-design.md`.

## Relationship to Loops

fidelis is a path dependency from the loops monorepo:
- `apps/loops/pyproject.toml` → `fidelis = { path = "../../../fidelis" }`
- `apps/hlab/pyproject.toml` → `fidelis = { path = "../../../fidelis" }`
- **Full `cells` → `fidelis` migration** completed (subtask `cells-to-fidelis`,
  in review). 153 import sites across 73 files. `libs/cells/` deleted. 80 loops
  tests passing. Needs review + merge.

## Structure

```
src/fidelis/           # ~10,000 LOC
  Primitives:          Cell, Style, Span, Line, Block, Cursor, Viewport, Focus
  Composition:         join, pad, border, truncate, Align, vslice
  Views:               fidelis.views (flat namespace)
    Stateless:         shape_lens, tree_lens, chart_lens, sparkline, spinner,
                       progress_bar, render_big
    Stateful:          list_view, table, text_input, data_explorer
  Output:              Writer, print_block, InPlaceRenderer
  CLI Harness:         Zoom, OutputMode, Format, CliContext, run_cli
  TUI:                 Surface, Layer, Search, Buffer, KeyboardInput
  Mouse:               MouseEvent, MouseButton, MouseAction
  Aesthetic:           Palette (ContextVar), IconSet (ContextVar)

tools/                 # Doc extraction
  docgen.py            # AST-based snippet extraction + markdown sync
docs/
  guides/              # Narrative docs with docgen sync blocks
  plans/               # Design docs (including fidelity council output)
  .extract/            # Generated snippet store (snippets.v1.json)
tests/                 # 544 tests
demos/                 # Python files + tour.py + slides/
  slides/              # 17 markdown files (tour content)
  slide_loader.py      # Markdown parser with zoom levels + auto-nav
```

## Completed (This + Prior Sessions)

- **Block true immutability** — tuples, `__setattr__` rejection, architecture
  invariant tests (AST + runtime).
- **Wide-char consistency** — `_text_width.py`, 15 `len()` fixes, AST guardrail.
- **API cleanup** — removed FocusRing, internalized legacy modules, pruned exports.
- **Cursor primitive** — `Cursor` (frozen, clamp/wrap) as Layer 1 atom.
  ListState and TableState composed as `cursor: Cursor` + `viewport: Viewport`.
- **View layer design** — stateless vs stateful as primary axis. Design doc at
  `docs/plans/2026-02-23-view-layer-primitives.md`.
- **Module reorganization** — created `fidelis.views` (flat namespace), deleted
  `fidelis.widgets`, `fidelis.lens`, `fidelis.effects`. Clean break at 0.1.0.
- **Sparkline dedup** — shared `_sparkline_core.py` helper used by both
  `sparkline()` (tail sampling) and `chart_lens(zoom=1)` (uniform sampling).
- **Doc extraction pipeline** — `tools/docgen.py` (AST + sentinel extraction,
  markdown sync blocks, `--check`/`--update` modes). Initial 4 narrative guides
  at `docs/guides/`. Snippets store at `docs/.extract/snippets.v1.json`.
- **Fidelity-aware style resolution** — designed via 5-agent council session,
  implemented via subtask. `Palette` (5 Style-valued semantic roles) + `IconSet`
  (glyph vocabulary), both ContextVar + kwarg. `themes/` and `ComponentTheme`
  deleted. `_setup_defaults` bridge in `run_cli`. 33 new tests.
- **Design council skill** — reusable skill at
  `~/.claude/skills/superpowers/design-council/`. 5-role persistent swarm
  (muser, siftd, web-researcher, ux-reactor, cold-reactor). Templates for
  constraints, design doc, and perspective docs.
- **Capability signal dissolution** — council concluded the question dissolves.
  Color downconversion in `Writer._color_codes()` (~70 LOC). No new types,
  no pipeline changes. Principle: "Capabilities resolve at boundaries."
- **Tour slide rebuild** — migrated 34 inline slides to 17 markdown files
  in `demos/slides/`. Slide loader (`demos/slide_loader.py`) handles zoom
  levels, auto-navigation from group+order, alignment via frontmatter
  defaults + bracket overrides. Removed ~1300 lines of inline definitions
  from `tour.py`. 47 new tests.

## Capability Signal Design (Resolved)

Design council concluded the question **dissolves**: capabilities resolve at
the Writer boundary, not in the rendering pipeline. No new types, no new
ContextVars, no Lens signature change, no view modifications.

- Design doc: `docs/plans/2026-02-25-capability-signal-design.md`
- Constraints doc: `docs/plans/2026-02-25-council-capability-constraints.md`
- Principle: "Capabilities resolve at boundaries, not in pipelines"

**What was implemented:** Color downconversion in `Writer._color_codes()` —
wired up `detect_color_depth()` (was dead code) with ~70 LOC of color
arithmetic. Hex/256-color values auto-downgrade to match terminal capability.

## Subtask Status

| Task | Status | Notes |
|------|--------|-------|
| `fidelity-impl` | **Merged** | 8 commits, 472 tests, +1976/-730 lines |
| `cells-to-fidelis` | In review | Full loops migration, needs review + merge |
| `codex-design-review` | Complete (closed) | Found MONO/PLAIN conflict, resolved |

## Open Threads

- **Auto light/dark detection** — deferred. Pattern when needed: detect in
  `_setup_defaults()`, set ambient Palette. Palette preset problem, not
  architectural. Mode 2031 (color-palette-update-notifications) is the future
  trigger mechanism.
- **PyPI publish** — Package metadata ready. No CI/CD yet.
- **Guide content** — 4 guides landed with draft-quality narrative. Need
  fleshing out once designs stabilize.
- **Tour docgen integration** — slide markdown files support `<!-- docgen:begin/end -->`
  markers but none are populated yet. Run `docgen --update --roots demos/slides` to
  sync source excerpts into zoom-level code blocks.
- **Stale plan file** — `docs/plans/2026-02-22-project-cleanup.md` is
  untracked and fully executed. Can be deleted or committed as historical.
