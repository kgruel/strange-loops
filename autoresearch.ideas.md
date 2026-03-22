# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%

## Current: loops app (68.4%, 1410 miss)

### Remaining testable main.py helpers
- `_resolve_combine_vertex_paths` L764: relative path resolution in combine
- `_resolve_vertex_store_path` L1443-1447: combine path resolution
- `_apply_vertex_scope` L3207+: reading scoped vertex text
- `_parse_emit_parts` — pure string parsing, zero dependencies

### After main.py helpers
- `commands/identity.py`: 13 miss — find_workspace_root fallback paths
- `commands/pop.py`: 18 miss — needs real store with pop history  
- `lenses/fold.py`: 9 miss — very deep rendering paths
- main.py large functions (cmd_emit 62 miss, etc.) — need full CLI setup

### Blocked (695 miss TUI apps)
- `tui/autoresearch_app.py` + `tui/store_app.py` — needs TUI event loop

## Flaky test note
- `test_mixed_boundary_with_conditions_met` in engine — timing-dependent, pre-existing
- Test timing ~1.7-2.1s now; efficiency ~3.1 (31% below baseline 4.53)

## Architecture insight
The main.py pure helpers are very testable since they don't need real vertex/store:
- Exception paths (L1189-1190, L1954-1955, L1457-1458, etc.)
- Path resolution with mocked LOOPS_HOME
- Error/dispatch paths that just return an int
