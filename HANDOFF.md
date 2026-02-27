# HANDOFF

Session continuity for painted. See `CLAUDE.md` for API reference.

## What Is This

Cell-buffer terminal UI framework. Extracted from the loops monorepo
(`libs/cells/`) as a standalone package. Answers: **where is state displayed?**

**One dependency:** `wcwidth` (wide character width calculation).

## Current State

v0.1.0, 617 tests passing, pushed to `git@git.gruel.network:kaygee/painted.git`.

Discord narrative debugging infrastructure implemented and validated. Two sessions
completed (simulated + real Discord). Writer output path fully optimized.

## Relationship to Loops

painted is a path dependency from the loops monorepo:
- `apps/loops/pyproject.toml` → `painted = { path = "../../../painted" }`
- `apps/hlab/pyproject.toml` → `painted = { path = "../../../painted" }`
- **Full `cells` → `painted` migration** completed (subtask `cells-to-painted`,
  in review). 153 import sites across 73 files. `libs/cells/` deleted. 80 loops
  tests passing. Needs review + merge.

## Structure

```
src/painted/           # ~10,000 LOC
  Primitives:          Cell, Style, Span, Line, Block, Cursor, Viewport, Focus
  Composition:         join, pad, border, truncate, Align, vslice (+ hit-testing ids)
  Views:               painted.views (flat namespace)
    Stateless:         shape_lens, tree_lens, chart_lens, sparkline, spinner,
                       progress_bar, render_big
    Stateful:          list_view, table, text_input, data_explorer
  Output:              Writer, print_block, InPlaceRenderer
  CLI Harness:         Zoom, OutputMode, Format, CliContext, run_cli
  TUI:                 Surface, Layer, Search, Buffer, KeyboardInput, TestSurface
  Mouse:               MouseEvent, MouseButton, MouseAction
  Aesthetic:           Palette (ContextVar), IconSet (ContextVar)

tools/                 # Dev tools
  docgen.py            # AST-based snippet extraction + markdown sync
  discord_chat.py      # Discord webhook post + bot read for narrative debugging
docs/
  guides/              # Narrative docs with docgen sync blocks
  plans/               # Design docs (including fidelity council output)
  .extract/            # Generated snippet store (snippets.v1.json)
tests/                 # 599 tests
demos/                 # Python files + tour.py + slides/
  slides/              # 21 markdown files (tour content, docgen-synced)
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
- **Module reorganization** — created `painted.views` (flat namespace), deleted
  `painted.widgets`, `painted.lens`, `painted.effects`. Clean break at 0.1.0.
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
- **Charm v2 deep dive** — researched Bubble Tea/Lip Gloss/Ultraviolet v2
  architecture. All sources verified. Research doc at
  `docs/research/2026-02-25-charm-v2-deep-dive.md`.
- **Hit testing for mouse picking** — `Block.id`, `Buffer.hit(x, y)`,
  `Surface.hit(x, y)`. Lazy provenance grid (zero cost when unused).
  Composition propagates ids through join/pad/border/truncate/vslice.
- **Surface test harness** — `TestSurface` for deterministic non-TTY testing.
  Fixed dimensions, input queue, frame capture (`CapturedFrame`). Writer
  accepts forced `color_depth`.
- **Scroll optimization** — `Surface._try_flush_scroll_optimized()` detects
  vertical content shifts via line hashing, emits DECSTBM + SU/SD instead of
  full repaint. 25-40x byte reduction per scroll. Opt-in via
  `scroll_optimization=True` or `FIDELIS_SCROLL_OPTIM=1`.
- **Tour content expansion** — 4 new slides covering rendering pipeline,
  layer stack API, lenses, and CLI harness. Fills the major content gaps.
- **Tour docgen integration** — `<!-- docgen:begin/end -->` sync blocks
  populated across 11 existing slides. Source excerpts now stay in sync
  with code via `docgen --check --roots demos/slides`.
- **Writer cursor coalescing** — `write_ops()` tracks cursor position and
  skips redundant `move_cursor` calls for adjacent cells. Wide-char aware.
  Composes with scroll optimization. 10 new tests.
- **Discord narrative debugging** — `tools/discord_chat.py` (stdlib-only,
  webhook POST + bot GET), 4 persona agent definitions in `.claude/agents/`,
  personas config, auto `.env` loading. Validated with real Discord session.
  6 new tests.
- **show() zero-config display** — `show(data)` entry point for progressive
  display. Defaults to `Zoom.DETAILED` (key-value tables, vertical lists,
  expanded trees, bar charts). `show()` with no args prints a blank line.
  Scalars bypass lens, Blocks pass through, dicts/lists use shape_lens.
  Auto-detects format from TTY. Dict at SUMMARY zoom shows compact
  `key: value` pairs (not just keys).
- **CliRunner error handling** — graceful error handling at the runner
  boundary. fetch() failures → styled error Block (Palette.error) + exit 1.
  render() failures → plain error Block + exit 2. JSON → `{"error": "..."}`.
  Streaming path covered. Surface intentionally not wrapped (render bugs
  should crash visibly).
- **Lens type dissolution** — Deleted the vestigial `Lens` dataclass and
  `SHAPE_LENS`/`TREE_LENS`/`CHART_LENS` constants. Lens functions are bare
  callables: `(data, zoom, width) -> Block`. `shape_lens` now auto-dispatches
  by data shape: numeric sequences → `chart_lens`, labeled numeric dicts →
  `chart_lens`, hierarchical dicts → `tree_lens`. `max_zoom` moved to
  widget-level (demo app). 5 new auto-dispatch tests.
- **`print_block` TTY auto-detect** — `use_ansi` default changed from
  `True` to `None` (auto-detect via `stream.isatty()`). All internal
  call sites pass explicit values, so no behavior change for `show()`
  or `run_cli()`. Standalone `print_block(block)` now does the right
  thing when piped. 617 total tests.
- **VHS demo recordings** — charmbracelet/vhs tape infrastructure for
  terminal GIF recordings. Wrapper script (`demos/painted-demo`), purpose-built
  demo scripts (`tapes/scripts/`), narrative tapes with `# comment` technique
  for in-terminal explainers. Four tapes: paint-it (print→show transformation),
  ladder (composition escalation), zero-to-interactive (fidelity spectrum),
  health (full -q → standard → -v → --live → -i progression with InPlaceRenderer).
  `fidelity_health.py` modernized: `render_standard()` returns Block directly
  (removed `_text_block` helper), added `fetch_stream` for `--live` mode.
  Stale `cells` docstring fixed in `fidelity.py`.
- **Landing page** — Single static HTML page (`site/index.html` + `site/style.css`)
  for GitHub Pages. Adaptive dark/light theme via CSS custom properties
  (Catppuccin Latte/Mocha tokens, designed to be swapped for custom design
  tokens before release). Alternating code+GIF layout telling the adoption
  ladder story (hero → print_block → compose → CLI harness → full TUI).
  Prism.js CDN for Python/Bash syntax highlighting with custom token colors
  using CSS variables. Zero build step. `.nojekyll` for GitHub Pages.
  Design docs: `docs/plans/2026-02-26-landing-page-design.md`,
  `docs/plans/2026-02-26-companion-gifs-design.md`.

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
| `cells-to-painted` | In review | Full loops migration, needs review + merge |
| `codex-design-review` | Complete (closed) | Found MONO/PLAIN conflict, resolved |
| `charm-v2-research` | **Merged** | 455-line research doc, all sources verified |
| `hit-testing` | **Merged** | Block.id + Buffer provenance + Surface.hit() |
| `test-harness` | **Merged** | TestSurface + CapturedFrame + Writer color_depth override |
| `scroll-optimization` | **Merged** | DECSTBM scroll + line hashing + detection |
| `tour-content-gaps` | **Merged** | 4 new slides: pipeline, layers, lenses, CLI harness |
| `tour-docgen` | **Merged** | Docgen sync blocks in 11 tour slides |
| `error-handling` | **Merged** | CliRunner fetch/render error handling |

## Narrative Debugging (Two Sessions Completed)

Agent-swarm narrative debugging: 4 persona agents with separate contexts
react to painted content. Two sessions completed.

**Session 1** (simulated, SendMessage relay): Dropped README, found doc gaps.
**Session 2** (real Discord): Conversation starter → CLAUDE.md drop → run_cli
signature → shape_lens. Full async flow via `tools/discord_chat.py`.

**Combined findings — README/value prop:**
- Adoption ladder IS the differentiator: `print_block()` → compose → `run_cli()` → Surface
  (3/4 agents independently: "that should be at the top of the README")
- `show(data)` across pipe/static/live/interactive is the undocumented value prop
  (mrbits: "if this delivers that, document it front and center")
- Bubble Tea requires framework commitment at step 1; painted's ramp is unique
  (synthwave: "real differentiator")
- ghost_pipe validated progressive adoption: "swap print() for print_block()
  one at a time" resolved their 30-subcommand blocker

**Combined findings — API clarity:**
- shape_lens = convenience/exploration tool, not production renderer (ghost_pipe named it)
- Custom Lens/render function completely replaces shape_lens (opt-in, not opt-out)
- Format axis orthogonality landed cleanly (JSON skips render entirely)
- Lens described as "viewport" in API table — wrong (session 1, still unfixed)
- `print_block` TTY auto-detect gap (session 1, still unfixed)

**Process learnings:**
- Persistent agents >>> fresh agents per round (memory, momentum, conversation)
- Sonnet sufficient for personas (validated session 2)
- Bash-only tools + channel-only content prevents hallucinated source analysis
- ghost_pipe lurking correctly = real signal (broke silence twice, both sharp)
- Discord channel IS the transcript (no manual serialization)

Process reference: `docs/narrative-debug/process.md`
Session 1 transcript: `docs/narrative-debug/transcript.md`
Session 2 transcript: Discord channel #terminal-crafters

## Open Threads

- **Review narrative debugging findings** — two sessions of findings to
  synthesize. Adoption ladder, show(data) value prop, shape_lens positioning,
  Lens naming, print_block TTY gap. Next session: review both sessions'
  feedback and improve the process going forward.
- **README rewrite** — informed by narrative debugging findings. Adoption
  ladder as lede, show(data) value prop, progressive enhancement framing.
- **`print_block` TTY auto-detect** — DONE. `use_ansi=None` default.
- **Declarative terminal state** — deferred. When painted needs concurrent
  windows (not just modal layers), composition units will need to declare
  terminal mode requirements (mouse, cursor, graphics). Reconciliation
  algebra at Surface. Design thread: `docs/plans/2026-02-25-declarative-terminal-state.md`.
  Building blocks in place: hit testing, scroll regions.
- **Auto light/dark detection** — deferred. Pattern when needed: detect in
  `_setup_defaults()`, set ambient Palette. Palette preset problem, not
  architectural. Mode 2031 (color-palette-update-notifications) is the future
  trigger mechanism.
- **PyPI publish** — Package metadata ready. No CI/CD yet.
- **Guide content** — 4 guides landed with draft-quality narrative. Need
  fleshing out once designs stabilize.
- **Primitives demo ladder** — complete. Four demos, each at its API layer:
  `cell.py` (Style + print_block) → `span_line.py` (Span/Line/to_block) →
  `compose.py` (join/border/pad/truncate/Wrap/Align) → `show.py` (auto-dispatch).
  Old stepping stones deleted (`block.py`, `buffer.py`, `buffer_view.py`).
  Rules in `demos/CLAUDE.md`.
- **VHS companion GIFs** — in progress on `feature/companion-gifs` branch
  (worktree at `.worktrees/companion-gifs`). Scripts written, hero.tape and
  styled.tape recorded. Remaining: compose.tape, zoom.tape, tui.tape, final review.
  Plan: `docs/plans/2026-02-26-companion-gifs-plan.md`.
- **VHS demo iteration** — infrastructure works, four tapes record. Next
  session should start with reviewing the GIFs and iterating on content,
  pacing, and narrative. Key VHS limitations to ground requests:
  - `Hide`/`Show` only suppresses frame capture, not terminal state.
    Commands typed during `Hide` remain in scrollback. Must `clear`
    before `Show` to get a clean canvas.
  - `LoopOffset N%` starts the GIF loop at that point in the recording.
    Use `0%` for demos that should start from the beginning.
  - InPlaceRenderer (`--live`) redraws in-place by moving cursor up.
    Previous terminal output gets overwritten. Must `clear` between
    sections when mixing static and live output.
  - VHS uses a pty — `show()` always detects TTY within the recording.
    Pipe detection only works when the command actually pipes (`| cat`).
  - `uv run` shows build messages on first invocation. Hidden warm-up
    run needed in preamble to cache deps.
  - No native "edit a file" capability. Narrative technique: hidden `cp`
    of pre-staged file variants + visible `cat` for the reveal.
  - Alias/function definitions in preamble (hidden) give clean short
    commands. `health -q` reads better than `painted-demo health -q`.
  - Terminal size is in pixels. Font size determines actual columns/rows.
    900x600 at FontSize 16 ≈ 80-90 columns, 30-35 rows.
  - GIF file sizes: simple demos ~250-350K, complex (TUI + animation)
    ~500K-1M.
  - Tapes are at `tapes/*.tape`, scripts at `tapes/scripts/`, GIFs at
    `tapes/*.gif`. Design doc: `docs/plans/2026-02-26-vhs-demos-design.md`.
- **README rewrite** — informed by narrative debugging findings. Adoption
  ladder as lede, show(data) value prop, progressive enhancement framing.
  VHS GIFs ready to embed once polished.
- **Stale plan file** — `docs/plans/2026-02-22-project-cleanup.md` is
  untracked and fully executed. Can be deleted or committed as historical.
