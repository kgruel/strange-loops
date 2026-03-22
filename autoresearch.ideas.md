# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%

## Current: loops app (67.4%, 1456 miss)

### Remaining miss by file (excluding TUI apps)
- `main.py`: ~568 miss (67.4%) — CLI dispatch, most paths need real vertex/store
- `commands/fetch.py`: ~105 miss — subprocess/network mocking needed
- `commands/vertices.py`: ~32 miss — vertex discovery needs real files
- `commands/pop.py`: ~18 miss — some testable helper paths
- `commands/identity.py`: ~17 miss — some testable helper paths
- `lenses/fold.py`: 9 miss — very deep rendering paths
- `lenses/store.py`: ~5 miss remaining (the L211-225 path needs real data)
- `tui/autoresearch_app.py`: 442 miss — TUI, not testable
- `tui/store_app.py`: 253 miss — TUI, not testable

### L211-225 in lenses/store.py
- L211: `fill = "  "` (inside a column calculation when spacing needed)
- L222-225: Recent payload gist for DETAILED zoom (needs actual fact records with payloads)
- These need the `_render_summary` path with actual kind data

### Next targets
1. `lenses/store.py` L211-225: DETAILED zoom with populated fact kinds and recent payloads
2. `commands/vertices.py` helper functions (classify/describe/extract)
3. Main.py: `_parse_emit_parts`, `_warn_missing_fold_key` edges

## Flaky test note
- `test_mixed_boundary_with_conditions_met` in engine — timing-dependent, pre-existing
- Test timing has ±0.5s variance — min-of-2 is sufficient, 3 runs adds overhead

## Step-down opportunities
- Test timing noise makes step-down unreliable right now
- The inline import pattern was tried and discarded (timing offset the LOC gains)
