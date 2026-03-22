# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% (done — remaining 8 lines are coverage quirks)
- **engine**: 92.5% (132 miss — mostly combine/discover in vertex_reader)
- **store**: 99.6% (1 miss — effectively done)
- **lang**: 98.4% (done — remaining 6 lines are dead/unreachable code)

## Current: loops app (63.6%, 1598 miss)

### Remaining testable targets by bang-for-buck
- `lenses/fold.py`: 87 miss — rendering paths (MINIMAL zoom, refs filter, facts filter, grouped rendering, skipped sections footer). High LOC cost per line but pure logic.
- `main.py`: 573 miss — CLI dispatch. Many paths need real vertex files + stores. Could test individual helper functions.
- `commands/fetch.py`: 105 miss — fetch pipeline. Needs network/subprocess mocking.
- `commands/vertices.py`: 32 miss — vertex listing command. Needs real .vertex files.
- `commands/pop.py`: 18 miss, `commands/identity.py`: 17 miss — smaller command modules.
- `lenses/sync.py`: 12 miss, `lenses/store.py`: 13 miss — small gaps.
- `palette.py`: 9 miss — color palette theming.

### Not cost-effective
- `tui/autoresearch_app.py`: 442 miss (0%) — TUI app, requires terminal/async event loop
- `tui/store_app.py`: 253 miss (21.4%) — TUI app, same issue
- These 695 miss are ~43% of all remaining miss but essentially untestable without TUI harness

### Step-down opportunities
- `_text()` helper duplicated in 4 test files — could be shared via conftest
- Test time climbing (3.39s) — check for slow test patterns

## Structural notes
- Flaky engine test: `test_mixed_boundary_with_conditions_met` — timing-dependent
- `_node_map` in lang/loader.py is dead code (defined L78-83, never called) — could be deleted
