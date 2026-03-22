# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%

## Current: loops app (69.2%, 1371 miss)

### Remaining testable main.py functions
- `_find_source_vertex` L168: store-directive path (already covered with store directive test)
- Small exception paths throughout main.py
- Look for more pure functions that take dict/path args

### Other remaining
- `commands/identity.py`: 15 miss — some from find_workspace_root returns None path
- `commands/pop.py`: 18 miss — needs real store with pop history
- `lenses/fold.py`: 9 miss — very deep rendering paths
- main.py large functions (cmd_emit 62 miss, etc.) — need full CLI setup

### Blocked (695 miss TUI apps)
- `tui/autoresearch_app.py` + `tui/store_app.py` — TUI event loop required

## Architecture insights from this session
- Pure helper functions in main.py are gold: exception paths, path resolution,
  _dispatch errors, _add_produced — all testable with just mock/tmp_path
- `subprocess.Popen` can be mocked to test error paths
- LOOPS_HOME env var is the key to isolating helper tests
- Combine vertex paths work with relative `./subdir/name.vertex` format

## Flaky test note
- `test_mixed_boundary_with_conditions_met` in engine — timing/state issue in full suite
  Passes in isolation and in per-package runs. The checks.sh runs each package separately
  so this only shows up intermittently.
