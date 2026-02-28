# Docs Site Expansion Plan

Research and recommendations for expanding painted's single landing page into a full documentation site.

---

## 1. Current State Summary

### Landing Page (`site/index.html`)

A single static HTML page telling the adoption ladder story: `show()` -> `print_block` -> compose -> CLI harness -> full TUI. Five sections alternate code-left/GIF-right with visual rhythm. Install section and minimal footer (GitHub, PyPI).

**Technical stack:** Raw HTML + CSS, no build step. Prism.js CDN for syntax highlighting. CSS custom properties with Catppuccin Latte (light) / Mocha (dark) via `prefers-color-scheme`. Responsive at 768px breakpoint. GitHub Pages serves `site/` directly.

**Assets:** One GIF exists (`site/img/hero.gif`, 333KB). Four other sections reference GIFs that do not exist in `site/img/` (styled, compose, zoom, tui) -- they show alt text fallbacks. The `tapes/` directory has 10 recorded GIFs, but only `hero.gif` was copied to `site/img/`.

### Design Tokens

The CSS uses 30+ custom properties organized by role (page-bg, surface, text, text-muted, code-bg, accent, etc.) plus 12 Prism token overrides. Both light and dark themes are fully specified. The token system is clean and extensible.

### GitHub Pages

`site/.nojekyll` exists. The directory is ready for GitHub Pages deployment from `main` branch `/site` path.

---

## 2. Content Inventory

### 2.1 Landing Page Sections

| Section | Status | GIF in `site/img/` | GIF in `tapes/` |
|---------|--------|---------------------|------------------|
| Hero (`show()`) | Complete | `hero.gif` (333KB) | `hero.gif` (333KB) |
| Print styled output | Code complete, no GIF | Missing `styled.gif` | Not recorded separately |
| Compose | Code complete, no GIF | Missing `compose.gif` | Not recorded separately |
| CLI harness | Code complete, no GIF | Missing `zoom.gif` | `fidelity.gif` (1.3MB) exists, could serve |
| Full TUI | Code complete, no GIF | Missing `tui.gif` | Not recorded separately |
| Install | Complete | N/A | N/A |
| Footer | Complete, links to GitHub + PyPI | N/A | N/A |

**Existing tapes (10 GIFs, total ~7MB):** paint-it, ladder, three-ways, hero, show, components, health, fidelity, live, profiler. These are narrative demos, not the tight companion GIFs the landing page needs. The companion GIF plan (`2026-02-26-companion-gifs-plan.md`) specifies 5 purpose-built VHS tapes but they have not been recorded yet (except hero).

### 2.2 Documentation Files

#### Architecture & Reference (in `docs/`)

| File | Content | State | Reusable for site? |
|------|---------|-------|--------------------|
| `ARCHITECTURE.md` | Stack visualization, data flow diagrams, component pattern, layer pattern | Complete | High -- foundation for Architecture page |
| `PRIMITIVES.md` | Quick reference for all primitives with code examples | Complete | High -- foundation for API Reference |
| `DATA_PATTERNS.md` | Frozen state + pure functions, three conceptual layers, state ownership | Complete | High -- foundation for Patterns/Cookbook |
| `DEMO_PATTERNS.md` | Tour completeness analysis, demo organization, TUI app pattern | Complete | Medium -- the TUI app pattern section is valuable |
| `ZOOM_PATTERNS.md` | Zoom propagation research: global vs independent, state management | Complete | Medium -- could become an advanced guide |
| `MODE_RESOLUTION.md` | AUTO mode collapse rules, capability filtering | Complete | Medium -- reference for CLI harness docs |
| `VIEWPORT_DESIGN.md` | Scroll state management design, Viewport type | Complete (design) | Low -- implementation doc, not user-facing |
| `MOUSE.md` | Terminal mouse protocol research, SGR parsing, framework comparisons | Complete | Low -- internal research, not user-facing |

#### Guides (in `docs/guides/`)

| File | Content | State | Reusable for site? |
|------|---------|-------|--------------------|
| `01-primitives-and-blocks.md` | Narrative guide: Style, Cell, Span, Line, Block with docgen-synced code | Complete | High -- directly usable as a site page |
| `02-composition-layout.md` | Narrative guide: joins, padding, borders, truncation, vslice | Complete | High -- directly usable |
| `04-cli-harness-fidelity.md` | Narrative guide: Zoom, OutputMode, Format, CliContext, run_cli | Complete | High -- directly usable |
| `05-tui-core-surface-layers.md` | Narrative guide: Surface, Layer, process_key, render_layers | Complete | High -- directly usable |

Note: Guide 03 is missing (gap between composition and CLI harness -- likely components/views).

#### Narrative Debug (in `docs/narrative-debug/`)

| File | Content | Value |
|------|---------|-------|
| `transcript.md` | Simulated community reactions to painted's API | High -- reveals what users find confusing (Lens naming, incremental adoption, `print_block` pipe behavior) and what excites them (one-dep, cell buffers, frozen state, composition model). Key quotes for a comparison page. |
| `process.md` | How to run narrative debug sessions | Low -- internal process doc |
| `personas.json` | Four persona definitions | Low -- internal tooling |

#### Research (in `docs/research/`)

| File | Content | Value |
|------|---------|-------|
| `2026-02-25-charm-v2-deep-dive.md` | Detailed comparison with Bubble Tea v2, Lip Gloss v2, Ultraviolet | High -- source material for a comparison page. Documents architectural parallels and divergences. |

#### Plans (in `docs/plans/`, 21 files)

Design/implementation plans for features. Not directly user-facing but useful as source material for "how it works" content. Notable:

- `2026-02-25-fidelity-implementation.md` (36KB) -- detailed fidelity system spec
- `2026-02-25-show-plan.md` -- show() design and implementation
- `2026-02-26-landing-page-design.md` -- current site design rationale
- `2026-02-26-companion-gifs-plan.md` -- VHS tape specs for missing GIFs

### 2.3 Demos

| Category | Files | Runnable | Value for docs site |
|----------|-------|----------|---------------------|
| `primitives/` | cell.py, span_line.py, compose.py, show.py | CLI (print and exit) | Code snippets directly usable in guides |
| `apps/` | minimal.py, widgets.py, layers.py, lenses.py, mouse.py, big_text.py, theme_carnival.py | TUI (interactive) | Source for cookbook recipes |
| `patterns/` | rendering.py, fidelity.py, live.py, testing.py, profiler.py | CLI with flags | Source for patterns page, real-world examples |
| `tour.py` | Interactive teaching platform | TUI | Reference implementation for advanced patterns |

### 2.4 Docgen Pipeline

`tools/docgen.py` exists and syncs code snippets from source into guide markdown files via `<!-- docgen:begin -->` / `<!-- docgen:end -->` markers. The guides in `docs/guides/` already use this. The extracted snippets are cached in `docs/.extract/snippets.v1.json`.

This is significant: the docs-to-code sync mechanism already exists. Any site page using the guide format gets free code freshness.

### 2.5 README

165 lines. Covers: hero example, adoption ladder (4 entry points with code), install, API tables (primitives, composition, display, views, TUI, aesthetic). Has TODO comments for 4 missing companion GIFs. The API tables are a compact reference but not a substitute for proper API docs.

### 2.6 CLAUDE.md

Comprehensive project reference: build/test commands, type tables, rendering pipeline, invariants, CLI harness specification, package structure, source layout. Serves as the de facto API reference for agents. Not a substitute for user-facing docs but contains all the information needed to generate them.

---

## 3. Gap Analysis

### What exists and is sufficient

- **Conceptual architecture** -- `ARCHITECTURE.md` covers the stack, data flow, component pattern, layer pattern. Solid.
- **Primitive reference** -- `PRIMITIVES.md` covers all types with code examples. Good.
- **Data patterns** -- `DATA_PATTERNS.md` explains the frozen state + pure functions philosophy. Excellent.
- **Design rationale** -- Spread across plans and research docs. Abundant.

### What exists but needs transformation

- **Guides** -- Four narrative guides exist but are markdown files with docgen markers. They need HTML wrapping to become site pages. Content is ready; delivery mechanism needs work.
- **API tables** -- README and CLAUDE.md have them, but they are not browsable or linkable as individual pages. Need to be expanded into proper API reference pages.
- **Demo code** -- Runnable examples exist but are not presented as copiable recipes. Need to be extracted and annotated for a cookbook.

### What does not exist

| Gap | Priority | Why it matters |
|-----|----------|----------------|
| **Getting Started / Quickstart** | P0 | The landing page shows examples but doesn't walk someone through their first `pip install` to working code. The README's adoption ladder is close but not a step-by-step guide. |
| **Cookbook / Recipes** | P0 | Common tasks ("build a status card", "add a progress bar", "handle keyboard input") have no dedicated page. The demos have the code but not the narrative framing. |
| **API Reference (browsable)** | P1 | CLAUDE.md has the information but it is not a navigable, searchable API docs page. Users need per-type pages with constructors, methods, and examples. |
| **Comparison page** | P1 | The narrative debug transcript and Charm v2 deep dive contain excellent positioning material (vs Textual/Rich, vs Bubble Tea/Lip Gloss, vs ratatui). Not synthesized into a user-facing page. |
| **Migration guide** | P2 | For users coming from Textual, Rich, or Bubble Tea. The transcript shows these users exist and have specific questions ("is Block like Widget?", "where's the DOM?"). |
| **Contributor guide** | P2 | Architecture docs exist but there is no "how to contribute" page. The dev harness (`./dev check`) is documented in CLAUDE.md but not exposed to potential contributors. |
| **Changelog** | P2 | No CHANGELOG.md or releases page. |
| **Site navigation** | P0 | The site has no nav bar, no sidebar, no page linking. Adding a second page requires navigation infrastructure. |

---

## 4. Recommended Site Map

```
painted.dev (or GitHub Pages URL)
|
+-- / (index.html)                    -- Landing page (exists, keep as-is)
|
+-- /docs/                            -- Documentation hub
|   +-- /docs/quickstart              -- Getting started guide
|   +-- /docs/primitives              -- Guide 01: Style, Cell, Span, Line, Block
|   +-- /docs/composition             -- Guide 02: join, pad, border, truncate
|   +-- /docs/cli-harness             -- Guide 04: Zoom, OutputMode, run_cli
|   +-- /docs/tui                     -- Guide 05: Surface, Layer, Focus
|   +-- /docs/components              -- Guide 03 (new): widgets overview
|
+-- /cookbook/                         -- Recipes
|   +-- /cookbook/status-card          -- Build a bordered status card
|   +-- /cookbook/progress-bar         -- Add a progress indicator
|   +-- /cookbook/keyboard-input       -- Handle keyboard in a TUI
|   +-- /cookbook/zoom-levels          -- Write a zoom-aware render function
|   +-- /cookbook/cli-to-tui           -- Upgrade a CLI to interactive TUI
|
+-- /api/                             -- API Reference
|   +-- /api/style                    -- Style, Cell, EMPTY_CELL
|   +-- /api/span                     -- Span, Line
|   +-- /api/block                    -- Block, Wrap
|   +-- /api/compose                  -- join_*, pad, border, truncate, Align
|   +-- /api/fidelity                 -- Zoom, OutputMode, Format, CliContext, run_cli
|   +-- /api/views                    -- shape_lens, tree_lens, chart_lens, flame_lens
|   +-- /api/components               -- spinner, progress_bar, list_view, text_input, table
|   +-- /api/tui                      -- Surface, Buffer, BufferView, Layer, Focus, Search
|   +-- /api/palette                  -- Palette, IconSet
|
+-- /compare                         -- How painted compares to alternatives
+-- /architecture                     -- For contributors: stack, data flow, invariants
```

### Navigation Structure

- **Top nav bar** with: Home, Docs, Cookbook, API, Compare
- **Docs sidebar** (on docs pages): ordered list of guides
- **API sidebar** (on API pages): alphabetical or grouped by subpackage
- **Breadcrumbs** on inner pages

---

## 5. Per-Page Specifications

### 5.1 Quickstart (`/docs/quickstart`)

**Contains:** Install, verify, first styled output, first composition, first CLI harness invocation. Five steps, each with code you can copy-paste and run.

**Source material:** README adoption ladder examples, `demos/primitives/cell.py`, `demos/primitives/compose.py`, `demos/primitives/show.py`.

**Effort:** Small -- content exists, needs sequencing and HTML wrapping.

### 5.2 Guide Pages (`/docs/primitives`, `/docs/composition`, `/docs/cli-harness`, `/docs/tui`)

**Contains:** Existing guide content from `docs/guides/01-05`, converted to HTML with the site's design tokens and Prism highlighting.

**Source material:** `docs/guides/*.md` -- already docgen-synced with source code.

**Effort:** Small per page -- content is written, needs HTML template and navigation.

### 5.3 Components Guide (`/docs/components`) -- NEW

**Contains:** Overview of the component pattern (frozen state + render function). One section per widget: spinner, progress_bar, list_view, text_input, table. Code examples from `demos/apps/widgets.py`.

**Source material:** `CLAUDE.md` component tables, `docs/DEMO_PATTERNS.md` component pattern, `demos/apps/widgets.py`, `src/painted/components/*.py`.

**Effort:** Medium -- needs to be written. Structure exists but narrative does not.

### 5.4 Cookbook Recipes (`/cookbook/*`)

**Contains:** Problem-focused pages. Each: problem statement, solution code, explanation of why it works, variations.

**Source material:**
- Status card: `README.md` compose section, `tapes/scripts/compose.py`
- Progress bar: `demos/apps/widgets.py` progress section
- Keyboard input: `demos/apps/minimal.py`, `docs/DEMO_PATTERNS.md` TUI app pattern
- Zoom levels: `docs/ZOOM_PATTERNS.md`, `demos/patterns/rendering.py`
- CLI to TUI: `demos/patterns/fidelity.py`, `docs/FIDELITY.md`

**Effort:** Medium per recipe -- code exists in demos, needs extraction and annotation.

### 5.5 API Reference (`/api/*`)

**Contains:** Per-module pages with: type signatures, constructor parameters, method tables, short examples. Generated from docgen snippets where possible.

**Source material:** `docs/.extract/snippets.v1.json` (generated by `tools/docgen.py`), `CLAUDE.md` type tables, `docs/PRIMITIVES.md`.

**Effort:** Medium-High -- the docgen pipeline can extract signatures, but the HTML template and per-type examples need to be written. Could be partially automated.

### 5.6 Comparison Page (`/compare`)

**Contains:** Positioned comparison against Textual/Rich, Bubble Tea/Lip Gloss, ratatui. Not "we're better" -- "here's the difference in mental model."

**Source material:**
- `docs/narrative-debug/transcript.md` -- real reactions from simulated users with Textual, Bubble Tea, ncurses, and argparse backgrounds. Quotes like "no widget tree, no DOM, no layout engine" and "it's value composition not tree composition."
- `docs/research/2026-02-25-charm-v2-deep-dive.md` -- detailed architectural comparison with Charm v2.
- Specific comparison axes: composition model (functions vs widget tree), state model (frozen vs reactive), rendering (cell buffers vs strings), adoption gradient (one library vs two packages).

**Effort:** Medium -- source material is rich, needs synthesis and careful framing.

### 5.7 Architecture Page (`/architecture`)

**Contains:** The stack diagram, data flow (render path + input path), component pattern, layer pattern, design principles. Contributor-oriented.

**Source material:** `docs/ARCHITECTURE.md` -- nearly complete. Add build/test commands from `CLAUDE.md`.

**Effort:** Small -- content exists, needs HTML wrapping and contributor setup section.

---

## 6. Design System Recommendations

### 6.1 Catppuccin Tokens -- Keep and Extend

The current token system is well-structured. Keep Catppuccin Latte/Mocha as the base. Extend with:

- **`--sidebar-bg`** -- slightly different from `--surface` for navigation areas
- **`--nav-border`** -- for top navigation separator
- **`--active-link`** -- for current page indicator in sidebar
- **`--breadcrumb-text`** -- for breadcrumb navigation

The design doc explicitly calls out "one swap point" -- all identity in CSS custom properties. This principle should be maintained as the site grows.

### 6.2 Multi-Page Layout

Add a shared layout shell:

```
+--------------------------------------------------+
| painted    Docs  Cookbook  API  Compare    GitHub  |  <- top nav
+----------+---------------------------------------+
|          |                                        |
| Sidebar  |  Content area (max-width: 720px)       |
| (docs/   |                                        |
|  api     |                                        |
|  pages)  |                                        |
|          |                                        |
+----------+---------------------------------------+
```

- **Top nav:** Always visible. Logo + section links + GitHub link.
- **Sidebar:** Present on docs, cookbook, and API pages. Absent on landing page and comparison page.
- **Content area:** Where the page content renders. Same max-width as current landing page sections.
- **Mobile:** Sidebar collapses to hamburger menu. Top nav simplifies.

### 6.3 Dark/Light Theme

Current approach (`prefers-color-scheme`) is correct. Consider adding:
- A manual toggle (stored in `localStorage`) so users can override system preference.
- This is a common expectation for docs sites. Implementation: ~20 lines of JS.

### 6.4 Code Highlighting

Current Prism.js setup with custom CSS token overrides is the right approach. It adapts to dark/light automatically. For multi-page use:

- Keep Prism.js CDN (no build step).
- Add a "copy to clipboard" button on code blocks (small JS addition, ~15 lines).
- Consider adding line numbers for longer examples (Prism plugin).

### 6.5 Terminal GIF/Screenshot Embedding at Scale

With 5 landing page GIFs and potentially 10+ more for guides and cookbook:

- **GIF file size:** Target under 500KB each. The existing `hero.gif` (333KB) is a good benchmark. The narrative tapes are larger (components.gif is 1.2MB) -- these should be re-recorded at tighter dimensions if used.
- **Loading strategy:** Use `loading="lazy"` on all GIFs below the fold.
- **Alt text:** Already in place on the landing page. Maintain this standard.
- **Consider:** Converting GIFs to WebM/MP4 with `<video>` tags for smaller file sizes. A 1MB GIF often compresses to 100KB as WebM. This is a nice-to-have, not a blocker.

### 6.6 Mobile/Responsive

The current single breakpoint at 768px is sufficient. For multi-page layout, add a second breakpoint at 1024px for sidebar collapse:

- `< 768px`: Single column, hamburger nav
- `768px - 1024px`: Top nav visible, sidebar collapsed (toggle)
- `> 1024px`: Full layout with persistent sidebar

---

## 7. Build Tooling Recommendations

### Option A: Stay Raw HTML (Recommended for MVP)

**Rationale:** Matches painted's "one dependency" philosophy. The landing page proves the approach works. For 5-10 pages, hand-written HTML with shared CSS and a `<template>` include pattern (via a small build script) is manageable.

**How it works:**
1. Create a shared `_layout.html` with nav, sidebar structure, footer.
2. Write a 50-line Python script (`tools/build_site.py`) that:
   - Reads `site/pages/*.html` (content fragments)
   - Injects them into the layout template
   - Outputs to `site/` as flat HTML files
   - Converts markdown from `docs/guides/*.md` to HTML (using Python's `markdown` stdlib or a single-file parser)
3. Docgen continues to update markdown. Build script converts to HTML.

**Pros:** Zero external dependencies. Trivial to understand. Matches project ethos.
**Cons:** Manual page creation. No automatic table of contents. No search.

### Option B: Lightweight SSG (Recommended for v1)

If the page count exceeds ~15, a minimal static site generator becomes worthwhile. Candidates:

| Tool | Language | Build step | Why consider |
|------|----------|------------|--------------|
| **mkdocs-material** | Python | `mkdocs build` | Python ecosystem standard. Markdown source. Search built-in. Dark/light toggle. Widely used for Python lib docs. |
| **Astro** | JS | `npm build` | Island architecture. Can mix HTML and markdown. Fast. Modern. |
| **11ty** | JS | `npm build` | Minimal, data-driven, great for docs. |
| **Custom Python script** | Python | `python tools/build_site.py` | Zero deps outside stdlib. Full control. |

**Recommendation:** Start with Option A (raw HTML + small build script) for the MVP. If the site grows past 15 pages, evaluate mkdocs-material -- it is the Python ecosystem standard and requires only `pip install mkdocs-material`. The existing markdown guides and docgen pipeline integrate naturally.

**Key constraint to preserve:** The landing page (`index.html`) should remain hand-crafted HTML. It is the design showpiece. An SSG can handle docs/cookbook/API pages while the landing page stays bespoke.

### Docgen Integration

The existing `tools/docgen.py` already syncs code into markdown. The build pipeline should be:

```
source code
    |
    v
tools/docgen.py --> docs/guides/*.md (markdown with fresh code)
    |
    v
tools/build_site.py --> site/docs/*.html (HTML pages)
    |
    v
site/ --> GitHub Pages
```

This ensures code examples on the site are always in sync with the source.

---

## 8. Prioritized Roadmap

### Phase 0: Quick Wins (1-2 hours)

These require no structural changes to the site:

1. **Copy remaining tapes to `site/img/`** -- `fidelity.gif` can serve as `zoom.gif` (or record the companion tapes per the existing plan). `show.gif`, `health.gif` provide additional visual material.

2. **Add navigation links to landing page footer** -- Link to GitHub docs, README, and (when they exist) the docs pages. Costs 5 lines of HTML.

3. **Add "copy to clipboard" to code blocks** -- ~15 lines of JS. Improves usability immediately.

4. **Add manual dark/light toggle** -- ~20 lines of JS + a button in the nav. Common expectation.

### Phase 1: MVP Docs Site (1-2 days)

Goal: A user who finds painted can go from "what is this?" to "I'm using it" in one visit.

1. **Build the layout shell** -- Top nav, sidebar infrastructure, shared CSS. Create `tools/build_site.py` or a shared HTML template approach.

2. **Quickstart page** -- `/docs/quickstart`. Install, first Block, first composition, first `print_block`. Five copy-paste steps.

3. **Convert existing guides to site pages** -- `/docs/primitives`, `/docs/composition`, `/docs/cli-harness`, `/docs/tui`. Content is written; this is HTML wrapping + navigation.

4. **Record missing companion GIFs** -- Execute the companion GIFs plan (`2026-02-26-companion-gifs-plan.md`). The tapes are designed. This unblocks the landing page's visual completeness.

### Phase 2: v1 Docs Site (3-5 days)

Goal: A user can find answers to common questions without reading source code.

5. **Cookbook recipes** -- Start with the highest-value three:
   - Status card (demonstrates composition)
   - CLI to TUI upgrade (demonstrates the adoption ladder)
   - Zoom-aware rendering (demonstrates the lens/fidelity system)

6. **Comparison page** -- Synthesize the narrative debug transcript and Charm v2 deep dive into a user-facing "How painted compares" page. Position against Textual/Rich and Bubble Tea. Focus on mental model differences, not feature checklists.

7. **Components guide** -- Fill the gap between composition and CLI harness. Cover the five widgets with state + render examples.

8. **API reference (initial)** -- Start with the most-used types: `Style`, `Block`, `run_cli`, `Surface`. Expand from there. Use docgen snippets for signatures.

### Phase 3: Nice-to-Have (ongoing)

9. **Full API reference** -- All public types, all methods. Consider automating from docgen.

10. **Migration guides** -- "Coming from Textual", "Coming from Bubble Tea". The transcript has the specific questions these users ask.

11. **Search** -- If using mkdocs-material, this comes free. If raw HTML, add a simple client-side search (Pagefind or Lunr.js).

12. **Architecture page** -- For contributors. Convert `ARCHITECTURE.md` + build/test instructions.

13. **Changelog** -- As releases happen.

14. **Interactive examples** -- Embed terminal recordings or WASM-based Python execution. High effort, high wow factor. Deferred until the library stabilizes.

---

## 9. Content Automation vs Hand-Written

| Content type | Automate | Hand-write | Rationale |
|--------------|----------|------------|-----------|
| API signatures | Yes (docgen) | -- | Already synced from source |
| API examples | -- | Yes | Examples need narrative context |
| Guide code blocks | Yes (docgen) | -- | Already synced |
| Guide prose | -- | Yes | Narrative requires authorial voice |
| Cookbook recipes | -- | Yes | Problem framing is the value |
| Comparison page | -- | Yes | Positioning requires judgment |
| Quickstart | -- | Yes | Sequencing and tone matter |
| Navigation/sidebar | Yes (build script) | -- | Generated from page list |
| GIF embedding | Yes (build script) | -- | Standard img tags from a manifest |

---

## 10. Key Findings from Narrative Debug

The simulated user session (`docs/narrative-debug/transcript.md`) surfaced specific user questions that should inform docs priorities:

1. **"Can I start with `print_block` and not touch the rest?"** (ghost_pipe) -- The quickstart must answer this in the first 30 seconds. The adoption ladder is painted's strongest positioning.

2. **"What is Lens?"** (noodle, repeatedly) -- The term confused the Textual user. Docs should explain "Lens" before it appears in API tables. Consider whether "view function" or "render strategy" is clearer terminology in user-facing docs.

3. **"Is Block like Widget?"** (noodle) -- The Textual mental model collision is real. The comparison page should address this head-on: "No widget tree. Blocks are values, not objects with lifecycle."

4. **"Does `print_block` strip ANSI in pipes?"** (ghost_pipe) -- Practical users care about pipe safety. The quickstart should demonstrate: `python myapp.py | cat` produces clean output.

5. **"Same data, different zoom levels"** (synthwave) -- The cartographic zoom concept excited the Bubble Tea user. This is a unique selling point worth a dedicated cookbook recipe or guide section.

These findings directly inform the ordering of Phase 1 and Phase 2 work.
