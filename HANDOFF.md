# HANDOFF

Session continuity for fidelis. See `CLAUDE.md` for API reference.

## What Is This

Cell-buffer terminal UI framework. Extracted from the loops monorepo
(`libs/cells/`) as a standalone package. Answers: **where is state displayed?**

**One dependency:** `wcwidth` (wide character width calculation).

## Current State

v0.1.0, 472 tests passing, pushed to `git@git.gruel.network:kaygee/fidelis.git`.

Fidelity-aware style resolution **implemented and merged**: `Palette`
(5 semantic Style roles) + `IconSet` (glyph vocabulary), both ambient via
ContextVar. `themes/` and `ComponentTheme` deleted. Design council skill
written and ready for use.

**Next design question queued:** terminal capability signal — how capability
information flows through the rendering pipeline. Constraints doc ready at
`docs/plans/2026-02-25-council-capability-constraints.md`. Council session
planned for next reload (design-council skill needs session restart to load).

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
tests/                 # 472 tests
demos/                 # 20 Python files + tour.py
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
- **Terminal capabilities survey** — research doc at
  `docs/plans/2026-02-25-terminal-capabilities-survey.md`. Classified every
  detectable terminal capability by reliability tier.

## Capability Signal Design (Queued for Council)

Constraints doc: `docs/plans/2026-02-25-council-capability-constraints.md`

### Key Concepts Developed

**Capability vs Choice:** Two kinds of context flow to views. Capabilities are
discovered (terminal state). Choices are decided (user/app preferences). Both
are ambient. Both have sensible defaults. The difference is who sets them.

**Progressive detection:** Don't choose between instant env-var detection (Rich)
and query-based detection (libvaxis). Do both in sequence:
1. Frame 0: render with env-var defaults (instant)
2. Frame N: query probes return, upgrade capabilities, re-render (Surface
   diff-renders, so the upgrade is cheap)
3. Ongoing: push-based notifications (mode 2031) trigger re-render

**Provenance over confidence:** Source tracking (`"env_colorterm"` vs `"query"`)
matters more than numeric confidence scores.

### Open Questions for Council

1. Single capability struct vs multiple independent ContextVars?
2. Where does the progressive detection lifecycle live?
3. Does the Lens signature change, or do capabilities go ambient?
4. What do views actually do with capability information? (concrete examples)
5. Does "Choices" as a named concept earn its keep as an architectural boundary?

## Subtask Status

| Task | Status | Notes |
|------|--------|-------|
| `fidelity-impl` | **Merged** | 8 commits, 472 tests, +1976/-730 lines |
| `cells-to-fidelis` | In review | Full loops migration, needs review + merge |
| `codex-design-review` | Complete (closed) | Found MONO/PLAIN conflict, resolved |

## Open Threads

- **Capability signal design** — council session queued, constraints doc ready.
  See section above.
- **Terminal capability flow to views** — genuinely unsolved, never discussed
  in the archive. Will be addressed by the capability council.
- **Color depth tiers** — Lip Gloss `CompleteAdaptiveColor` pattern deferred.
  One palette per aesthetic for now; adaptive palettes if need emerges.
- **Auto light/dark detection** — `color-palette-update-notifications` protocol
  (Ghostty/Kitty). Future hook for `_setup_defaults`.
- **PyPI publish** — Package metadata ready. No CI/CD yet. Publish after
  capability design lands.
- **Guide content** — 4 guides landed with draft-quality narrative. Need
  fleshing out once designs stabilize.
- **Tour expansion** — research complete, parked until designs stabilize.
- **Stale plan file** — `docs/plans/2026-02-22-project-cleanup.md` is
  untracked and fully executed. Can be deleted or committed as historical.
