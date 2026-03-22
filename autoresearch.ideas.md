# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%
- **loops**: 69.7% (1352 miss) — best efficiency 2.64 (41.7% below baseline)

## Remaining loops app (1352 miss)

### Blocked (695 miss TUI apps)
- `tui/autoresearch_app.py` + `tui/store_app.py` — needs async TUI event loop

### Remaining testable (657 miss)
- `main.py`: ~500 miss (70.9%) — large functions need real vertex/store
  - `cmd_init`, `cmd_emit`, `_run_read`, `_run_fold`, `_run_sync` etc.
  - Could test with real tmp vertex + SQLite store (complex setup)
  - `_try_fast_read` (L3436): needs a valid vertex + read args
- `commands/fetch.py`: 105 miss — subprocess/network calls
- `commands/identity.py`: ~6 miss — L34, L75, L78 (walkup observer resolution)
- `commands/pop.py`: 18 miss — needs real pop store
- `lenses/fold.py`: 9 miss — deep item rendering paths
- `lenses/store.py`: 5 miss — needs real SQLite store with data
- `commands/vertices.py`: 2 miss — L106 (duplicate combine), L118 (unreachable suffix filter)

### Path forward
1. Integration tests with real vertex + store:
   - Create tmp SQLite stores with atoms facts
   - Test _run_read, fold, stream with those stores
   - Would cover large swaths of main.py
2. `_try_fast_read` with argv like ["read", "proj", "--plain"]
   when LOOPS_HOME has a valid vertex

## Architecture insights
- Pure helpers tested: _parse_emit_parts, _add_produced, _run_whoami, 
  _find_source_vertex, _register_with_aggregator, _execute_boundary_run,
  _resolve_named_store, _dispatch_verb_first, _apply_vertex_scope, main()
- Mock pattern works: `mock.patch("loops.main._run_close", return_value=0)`
- LOOPS_HOME env var is the key isolation mechanism

## Flaky test note
- `test_mixed_boundary_with_conditions_met` in engine — timing-dependent, pre-existing
  Only shows up when multiple pytest processes run concurrently
