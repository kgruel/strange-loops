# LOG

Session history for fidelis.

---

## 2026-02-22 — Extraction and cleanup

Extracted `libs/cells/` from the loops monorepo into standalone fidelis repo.

**What happened:**
- Created `/Users/kaygee/Code/fidelis/` with `git init`
- Copied src, tests, demos, docs from `libs/cells/` and `demos/cells/`
- Renamed all `cells` → `fidelis` (package, imports, docs, demos)
- Set up pyproject.toml with full PyPI metadata (MIT, hatchling, py>=3.11)
- 349 tests passing on initial commit

**Monorepo side:**
- Removed `libs/cells/` and `demos/cells/` from loops
- Updated app pyproject.toml files to path dep `../../../fidelis`
- Fixed path resolution (uv resolves relative to member location, not workspace root)
- 732 monorepo tests passing (atoms 295 + engine 357 + loops 80)

**Post-extraction cleanup:**
- Renamed `bench.py` → `tour.py`
- Updated all stale `demos/cells/` and `demos/fidelis/` paths to `demos/`
- Fixed `slide_loader.py` broken import (`from demos.bench` → `from demos.tour`)
- Removed deprecated Fidelity API (Fidelity enum, HarnessContext, detect_fidelity,
  add_fidelity_args, run_with_fidelity, fidelity_to_zoom) — clean break at 0.1.0
- Updated DEMO_PATTERNS.md, README.md, FIDELITY.md for tour rename
- 347 tests passing after cleanup (4 deprecated tests removed)

**Pushed to:** `git@git.gruel.network:kaygee/fidelis.git` (8 commits on main)

---

## 2026-02-22 — Release readiness review + hardening

Full project audit with 6 parallel exploration agents. Then began hardening.

**Merged:**
- Block true immutability (351 tests)
- Wide-char consistency (363 tests)
- KeyboardInput tests + CSI modifier fix (~400 tests)
- InPlaceRenderer cleanup (422 tests)

**422 tests passing on main.**

---

## 2026-02-23 — API cleanup + architecture review + cursor primitive

**Merged api-cleanup**, architecture review (views as Layer 3), cursor primitive.
Design conversations settled view layer vocabulary and cursor as compositional
primitive.

**439 tests passing on main.**

---

## 2026-02-23 — View layer design + module reorg + doc extraction

Settled view layer primitives. Created `fidelis.views` flat namespace. Deleted
`fidelis.widgets/`, `fidelis.lens/`, `fidelis.effects/`. Landed doc extraction
pipeline. Sparkline deduped.

**439 tests passing on main.**

---

## 2026-02-23 — Theming research + loops migration + fidelity reframe

Theme analysis complete. `cells` → `fidelis` loops migration in review.
Critical design reframe: "theming" is the wrong question — the real question
is fidelity-aware style resolution.

**439 tests passing on main.**

---

## 2026-02-24 — Fidelity design council session

5-agent design council (muser, siftd, web-researcher, ux-reactor, cold-reactor).
Produced full design doc + 6 perspective docs. Codex independent review caught
MONO_PALETTE/Format.PLAIN conflict.

Design doc: `docs/plans/2026-02-24-fidelity-design.md`

**439 tests passing on main.**

---

## 2026-02-25 — Fidelity implementation + council skill + capability design

**Merged fidelity-impl** (subtask, 8 commits):
- `Palette` (5 Style-valued semantic roles) + `IconSet` (glyph vocabulary)
- Both delivered via ContextVar + kwarg escape hatch
- `_setup_defaults` bridge in `run_cli` (sets `ASCII_ICONS` for `Format.PLAIN`)
- Deleted `themes/` (323 LOC) and `component_theme.py` (135 LOC)
- Updated all views, demos, docs, CLAUDE.md
- 33 new tests (palette, icon_set, view integration, fidelity defaults)
- 439 → 472 tests

**Design council skill** written at `~/.claude/skills/superpowers/design-council/`:
- Reusable 5-role persistent swarm orchestration
- Templates for constraints doc, design doc, perspective docs
- Based on retrospective of fidelity council session
- Key decisions: swarm not dispatch, siftd uses siftd tool, lightweight Phase 0

**Terminal capabilities survey** (background research agent):
- Classified every detectable terminal capability by reliability tier
- Key finding: source tracking > confidence scores
- Key finding: progressive detection (env-var first, queries second) fits
  fidelis's OutputMode axis naturally
- Research doc: `docs/plans/2026-02-25-terminal-capabilities-survey.md`

**Capability signal design conversation:**
- Developed capability vs choice distinction (discovered vs decided)
- Progressive detection model: render with defaults, upgrade on probe return,
  Surface diff-render makes upgrades cheap
- Constraints doc written: `docs/plans/2026-02-25-council-capability-constraints.md`
- Council session planned for next session (skill needs reload to activate)

**472 tests passing on main.**

## 2026-02-25 — Capability signal council + color downconversion

**Design council session** (5-agent persistent swarm):
- Question: how should capability information flow through the rendering pipeline?
- Outcome: the question dissolved. Capabilities resolve at Writer boundary, not in pipeline.
- Design doc: `docs/plans/2026-02-25-capability-signal-design.md`
- Cold reactor perspective: `docs/plans/2026-02-25-council-cold-reactor-perspective.md`
- Principle established: "Capabilities resolve at boundaries, not in pipelines"
- Key finding: no view in fidelis constructs fg/bg colors — all color originates from Palette or caller kwargs

**Color downconversion** implemented in Writer:
- Wired up `detect_color_depth()` (was dead code) to `_color_codes()`
- Added color arithmetic: hex→256→16 automatic downconversion (~70 LOC)
- All output paths covered: `write_frame()`, `print_block()`, `InPlaceRenderer`
- NORD_PALETTE now works correctly on 16-color terminals
- 25 new tests

**497 tests passing on main.**

## 2026-02-25 — Tour slide system rebuild

Migrated tour from 34 inline slides in `tour.py` to 17 markdown files loaded
by a rebuilt `slide_loader.py`. Detail/source sub-slides collapse into zoom
levels on each topic file.

**What changed:**
- `demos/slide_loader.py` — rebuilt with zoom parsing (`[zoom:N]` markers),
  auto-navigation from `group`+`order` frontmatter, `[align:center/left]`
  support with one-shot override semantics, validation (contiguous zoom,
  unique group/order, known groups), recursive directory loading
- `demos/tour.py` — new `Slide` type with `common` + `zooms` dict replacing
  flat `sections`. Removed `ZoomText`, `ZoomCode`, `styled()`, `KEYWORD`,
  `EMPH`, and `_build_slides_inline()` (~1300 lines). Section union simplified
  to `Text | Code | Spacer | Demo`
- `demos/slides/` — 17 markdown files across 5 subdirectories:
  `standalone/` (intro, fin), `primitives/` (cell, style, span, line),
  `composition/` (block, compose, buffer), `application/` (app, focus, search),
  `components/` (overview, progress, list, text_input, table)
- `tests/test_slide_loader.py` — 47 tests covering frontmatter, body parsing,
  zoom markers, styled text, validation, navigation, file loading, integration

**Design decisions:**
- Alignment: frontmatter `align: center` as slide default + `[align:left]`
  bracket override (single-section scope, then reverts). Chosen over
  Remark-style wrapping and HTML comment directives (deferred).
- Navigation computed from group+order sorting, not manually wired.
- Conversion logic lives in `tour.py` (not `slide_loader.py`) to avoid
  Python module identity issues with `match` statement type dispatch.

**544 tests passing on main.**

## 2026-02-25 — Charm v2 deep dive + infrastructure features

**Charm v2 research** (subtask `charm-v2-research`):
- Deep dive into Bubble Tea v2, Lip Gloss v2, Ultraviolet (all released 2026-02-24)
- Cloned all three repos to `~/Code/forks/` for source verification
- All 7 key claims verified against primary sources
- Key finding: fidelis and Charm v2 converged independently on pure render, cell
  buffers, and capability resolution at boundaries
- Research doc: `docs/research/2026-02-25-charm-v2-deep-dive.md`

**Hit testing for mouse picking** (subtask `hit-testing`):
- `Block.id: str | None` — optional semantic identifier, immutable
- `Buffer._ids` — lazy provenance grid (zero overhead when unused)
- `Buffer.hit(x, y)` / `BufferView.hit(x, y)` / `Surface.hit(x, y)`
- Composition propagates ids: join gap=None, pad inherits uniform id,
  border can override with its own id, truncate/vslice preserve
- Inspired by Lip Gloss v2 compositor but adapted to fidelis patterns

**Surface test harness** (subtask `test-harness`):
- `TestSurface` — wraps any Surface subclass for deterministic non-TTY testing
- Fixed width/height, predetermined input queue (keys + mouse events)
- `CapturedFrame` (frozen): buffer snapshot + writes diff + `.lines`/`.text`
- `Writer` accepts forced `color_depth` kwarg (bypasses isatty check)
- Inspired by Bubble Tea's WithWindowSize/WithColorProfile/WithInput

**Scroll optimization** (subtask `scroll-optimization`):
- Line-hash-based vertical scroll detection in `Surface._flush()`
- Emits DECSTBM + SU/SD instead of full repaint for scrolling content
- 25-40x byte reduction, ~50x CPU reduction per scroll frame (measured)
- Opt-in: `Surface(scroll_optimization=True)` or `FIDELIS_SCROLL_OPTIM=1`
- Constraints: alt-screen only, single region, |n| ≤ 3, min 6 lines, 80% match
- `Writer.write_ops()` handles mixed `ScrollOp | CellWrite` streams
- Inspired by Ultraviolet's hardscroll algorithm (simplified)

**Declarative terminal state** — design conversation, deferred:
- Charm's biggest v2 move: `View()` returns struct with mode declarations
- fidelis doesn't need it today (Surface is sole authority, layers are modal)
- Becomes necessary when concurrent windows need different terminal modes
- Pattern documented: composition units declare modes, Surface reconciles per frame
- Design thread: `docs/plans/2026-02-25-declarative-terminal-state.md`
- Building blocks in place: hit testing, scroll regions

**561 tests passing on main.**
