# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%

## Current: loops app (64.9%, 1549 miss)

### Remaining miss by file (excluding TUI apps)
- `main.py`: 573 miss (67.1%) — CLI dispatch, many subcommands need vertex/store setup
- `commands/fetch.py`: 105 miss — fetch pipeline with subprocess/network
- `lenses/fold.py`: ~73 miss — deep item rendering (_render_item_line)
- `commands/vertices.py`: 32 miss — needs vertex discovery
- `commands/pop.py`: 18 miss, `commands/identity.py`: 17 miss
- `lenses/sync.py`: 12 miss, `lenses/store.py`: 13 miss

### Excluded (not cost-effective)
- `tui/autoresearch_app.py`: 442 miss (0%) — TUI, needs async event loop
- `tui/store_app.py`: 253 miss (21.4%) — TUI, same

### Fully covered now
- palette.py: 100%
- pop_store.py: 98.5%
- lenses/test.py, lenses/_helpers.py: ~97%+
- lenses/run.py, lenses/ticks.py: ~98%+
- lenses/validate.py, lenses/compile.py, lenses/gist.py: ~95%+

### Path forward
- main.py helper functions could be targeted individually without full CLI setup
- commands/ modules often follow same pattern: parse args → load vertex → run operation
  Could test individual steps
- Step-down phase may help — test_fold_utils.py is large (47 tests, ~230 LOC)

## Flaky test note
- `test_mixed_boundary_with_conditions_met` in engine — timing-dependent, pre-existing
