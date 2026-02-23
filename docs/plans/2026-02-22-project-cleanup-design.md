# Project Cleanup Design

Post-extraction hygiene pass. Get fidelis into clean working order as a standalone project.

## Decisions

- Demo docs stay co-located in `demos/` (not moved to `docs/`)
- Deprecated Fidelity API removed — clean break at 0.1.0
- `bench.py` renamed to `tour.py`
- Tour content expansion is a separate future task

## 1. Rename & Fix References

- `demos/bench.py` → `demos/tour.py`
- Fix stale docstring paths in 9 demo files: `demos/cells/...` → `demos/...`
- Update `demos/README.md` to reflect `tour.py` name
- Update `demos/DESIGN.md` references if any mention "bench"
- Delete empty `demos/FIDELITY.md` stub

## 2. Remove Deprecated API

Remove from `src/fidelis/fidelity.py`:
- `Fidelity` enum
- `HarnessContext` dataclass
- `detect_fidelity()`, `add_fidelity_args()`, `run_with_fidelity()`
- `fidelity_to_zoom()` converter

Remove from `src/fidelis/__init__.py` exports if present. Update any internal references.

## 3. CLAUDE.md / Docs Alignment

- Update CLAUDE.md if it references "bench" → "tour"
- Verify docs/ files don't reference stale `cells` naming
- Note tour content gaps for future design task

## 4. Tour Gap Audit

Document what the tour currently covers vs what's missing. Not in scope for implementation — just a note for future work.

**Current tour slides:** intro, cell, style, span, line, buffer, block, compose, app, focus, search, components (progress, list, text, table), fin.

**Missing from tour:** lenses, mouse input, fidelity CLI harness, viewport/scroll, big_text/effects, layers/modal stack, themes, sparkline, data_explorer.

## Implementation Plan

### Phase 1: Quick fixes (parallelizable)

- **1a:** Rename `demos/bench.py` → `demos/tour.py`, update docstring
- **1b:** Fix stale `demos/cells/` paths in 9 demo file docstrings
- **1c:** Delete `demos/FIDELITY.md`
- **1d:** Update `demos/README.md` (bench → tour)
- **1e:** Update `demos/DESIGN.md` if needed

### Phase 2: Deprecated API removal (sequential)

1. Identify all deprecated symbols in `fidelity.py`
2. Check for internal usage (grep for Fidelity, HarnessContext, detect_fidelity, etc.)
3. Remove deprecated code from `fidelity.py`
4. Remove from `__init__.py` exports
5. Update tests if any reference deprecated API

### Phase 3: Docs alignment (parallelizable)

- **3a:** Update CLAUDE.md references (bench → tour, any stale cells refs)
- **3b:** Sweep docs/*.md for stale `cells` references
- **3c:** Update `docs/DEMO_PATTERNS.md` if it references bench

### Phase 4: Verify

1. Run all 349 tests
2. Spot-check a demo runs
3. Commit
