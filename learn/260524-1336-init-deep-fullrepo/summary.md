# Learn Summary — strange-loops

**Date:** 2026-05-24 13:36 | **Mode:** init | **Scope:** everything | **Depth:** deep
**Validation:** 100% | **Fix iterations:** 0 | **Learn score:** 100 (Excellent)

## Baseline → final state

- **Before:** `docs/` held 12 hand-written deep-dive docs (VERTEX, TEMPORAL, PERSISTENCE, SDK, IDENTITY, SCOPE-LATTICE, CADENCE, LENSES, NAMED_SESSIONS, CLI-CHEATSHEET, SDK-EMIT-PLAN, orchestration-agent-seed) + autoresearch/ campaign data + scratch/. No standard auto-doc set.
- **After:** 9 new standard docs added alongside the deep-dives. **No existing doc was overwritten.** README.md left untouched (see Decisions).

## Docs created (9)

| File | Lines | What it is |
|------|-------|-----------|
| `project-overview-pdr.md` | 119 | Orientation + design rationale; three shapes / four properties / one pattern |
| `system-architecture.md` | 198 | Cross-cutting map with 5 Mermaid diagrams; links into deep-dives rather than duplicating |
| `codebase-summary.md` | 187 | File-level inventory of all 8 packages + dependency tables |
| `code-standards.md` | 125 | Conventions, library boundaries, CI gate; defers to CLAUDE.md for working practice |
| `api-reference.md` | 370 | CLI command catalog (Part 1) + Python public API of all 5 libs (Part 2) |
| `testing-guide.md` | 295 | How to run tests, pytest/asyncio config, golden snapshots, fixtures |
| `configuration-guide.md` | 605 | The `.vertex`/`.loop` KDL config model; every example cited from a real file |
| `deployment-guide.md` | 64 | Honest short PyPI release/distribution doc |
| `changelog.md` | 102 | Generated from last 80 commits, grouped by conventional prefix |

## Key decisions (advisor-confirmed)

- **README.md left untouched** — its explicit "this is AI slop / not in a state to share" caveat is a deliberate user framing; grooming it to a polished standard README would contradict it.
- **Existing deep-dives cross-referenced, not duplicated** — `system-architecture.md` is a map that links into VERTEX/TEMPORAL/PERSISTENCE/IDENTITY/LENSES; `code-standards.md` defers to CLAUDE.md.
- **Deep set trimmed** — skipped `design-guidelines.md` (no UI/frontend) and `project-roadmap.md` (no source material in repo — roadmap lives in vertex state, not files). Reframed `deployment-guide.md` as a short honest PyPI release doc (it's a library/CLI, not a service).

## Validation trajectory

Single pass at 100%: 9/9 docs present, all within size limits (largest 605 < 800),
96/96 relative links resolve, sampled code references verified against source.
Each delegated doc was self-verified by its generating agent against actual source
(`__init__.py` `__all__`/lazy-import lists, real signatures).

## Findings surfaced during generation (pre-existing repo issues, NOT doc bugs)

1. **No `LICENSE` file at repo root** — `pyproject.toml` declares MIT and the hatch
   build config `[tool.hatch.build].only-include` lists `LICENSE`, but the file is
   absent. The next `uv build` / release will reference a missing file. Flagged in
   `deployment-guide.md`.
2. **`tests/test_architecture.py` has 2 pre-existing failures** (5/7 pass) — its
   `EXCEPTIONS` sets still reference `libs/painted/src/painted/...`, stale since
   painted became an external PyPI dependency. Stale-path assertions, not real
   boundary violations. Documented with the fix note in `testing-guide.md`.
3. **Stale CLAUDE.md API claim** — engine CLAUDE.md asserts `VertexProgram.collect()`
   /`.run()`; actual source exposes `receive()`, `sync()`, `async sync_async()`.
   `api-reference.md` documents the real methods.
4. **Semi-public surface notes** — `Projection` and `StoreReader` are used but not
   in the promised package `__all__`; documented as internal/semi-public.

## Recommended next steps

- Add a root `LICENSE` file (MIT) to match `pyproject.toml` before next release.
- Fix the two stale painted-path assertions in `tests/test_architecture.py`.
- Reconcile engine `CLAUDE.md` `VertexProgram` method names with source.
- Future runs: `/autoresearch:learn --mode update` to refresh as code changes;
  `--mode check` for a read-only health report.
