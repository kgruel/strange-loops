# Streamline `.loop → .vertex → hlab renderer` pipeline (plan)

This is the write-up produced for the `review/loop-to-renderer` task. It focuses on reducing per-command boilerplate when migrating hlab commands to the DSL, without over-abstracting domain logic.

## What’s repetitive today (observed)

Only `status` uses the DSL right now (`apps/hlab/src/hlab/commands/status.py`). Alerts and media-audit are still direct Python (`apps/hlab/src/hlab/commands/alerts.py`, `apps/hlab/src/hlab/commands/media_audit.py`). The boilerplate that shows up once you migrate a command to the DSL is concentrated in:

1. **Vertex + source loading**
   - `parse_vertex_file(path)`
   - `compile_sources(ast, base_dir)` (templates + per-instance loop specs)
   - `compile_vertex_recursive(ast)`
   - `compiled.specs.update(template_specs)` (manual merge)
   - `materialize_vertex(compiled, fold_overrides=...)`
2. **Runner ceremony**
   - `runner = Runner(vertex)`
   - `runner.add(source)` for each source
   - `async for tick in runner.run(): ...`
3. **Tick materialization**
   - fold state is dict-y (good for routing/serialization)
   - lenses often want domain dataclasses (`FiringAlert`, `AuditResult`, …), so commands end up doing dict→dataclass conversions

`status.py` additionally duplicates its “load” logic as `load()` and `load_with_expected()` (same compile path, just returns expected template kinds for spinners/TUI).

## Recommendation: generalize *loading + running*, keep *domain materialization* explicit by default

### 1) Add a shared “DSL program loader” helper (small, boring, testable)

Goal: eliminate the copy/paste “compile + merge template specs + materialize” block for most commands by centralizing it.

**Where:** prefer `libs/dsl` (not `apps/hlab`) so the helper is reusable by:
- `hlab` commands
- `dsl` CLI (`libs/dsl/src/dsl/cli.py`) which currently doesn’t understand template sources the way `compile_sources()` does
- experiments (`experiments/homelab/viz.py` already has a similar helper, but for the older `sources:`-as-glob style)

**Proposed API shape (minimal):**

- `dsl.program.load_vertex_program(vertex_path: Path, *, fold_overrides: dict[str, FoldOverride] | None = None) -> VertexProgram`
  - parses + validates
  - compiles vertex tree (`compile_vertex_recursive`)
  - compiles sources (`compile_sources`) and merges template specs into `compiled.specs`
  - materializes runtime `Vertex`
  - returns a small record type:
    - `vertex: Vertex`
    - `sources: list[Source]`
    - `expected_ticks: list[str]` (default: sorted `compiled.specs.keys()` after merge)
    - optionally `template_specs` (only if callers need to know “which specs came from templates”)

- `dsl.program.run(vertex: Vertex, sources: list[Source], *, grant: Grant | None = None) -> AsyncIterator[Tick]`
  - creates `Runner`, registers sources, yields ticks

**What stays command-specific:**
- which vertex file to load
- any fold overrides (logic belongs in domain `folds.py`)
- how ticks are grouped/combined (per-command)

### 2) Fold→lens gap: avoid “magic” conversions; standardize *where* conversion lives

There are three legitimate patterns; we should codify them and pick one as default:

1. **Render directly from dict payloads** (current `status` approach)
2. **Explicit materialization in the command** (recommended default)
3. **Mechanical dataclass construction helper** (only when fold output is already a 1:1 DTO dict)

Defaulting to explicit conversion keeps domain logic visible and avoids schema drift hidden behind a generic mapper.

### 3) Radarr: split transport from parsing; make parsing reusable by DSL + client

`apps/hlab/src/hlab/radarr.py` mixes transport (`httpx`) with parsing/normalization. If the DSL becomes the transport (shell `curl`/`wget` emitting JSON/ndjson), some parsing still needs to exist in Python — so avoid duplication by extracting pure parsing functions, e.g.:

- `parse_movie(raw: dict) -> Movie`
- `parse_movies(raw_list: list[dict]) -> list[Movie]`
- `parse_quality_def(raw: dict) -> QualityDefinition` (contains fallback logic)

Then `RadarrClient` calls these parsing functions, and DSL-based commands can reuse them during fold overrides or post-tick materialization.

## Concrete next implementation steps (for later)

1. Add `dsl.program` helper (`VertexProgram` + `load_vertex_program(...)` + `run(...)`).
2. Refactor `commands/status.py` + `tui.py` to use it (collapse `load()`/`load_with_expected()`).
3. Document a migration recipe for new commands (DTO dict + explicit materialization default).
4. Extract Radarr parsing into standalone functions and wire `RadarrClient` through them.

## Open questions

- What is the default definition of `expected_ticks` (all compiled loop specs vs a subset for UI spinners)?
- Do we want a convention that fold overrides should not return dataclasses (to keep tick payloads forwardable/JSON-ish)?
- Should the abstraction boundary live in `libs/dsl` (reusable) or `apps/hlab` (hlab-only)?

