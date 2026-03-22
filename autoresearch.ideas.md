# Autoresearch Ideas

## Progress Summary
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%
- **loops**: 75.6% (3615 covered) — best efficiency 2.49 (exp 44)
- 49 consecutive keep experiments out of 50 total (1 discard was noise)

## Remaining loops app (1063 miss)

### Blocked (695 miss TUI apps)
- `tui/autoresearch_app.py` + `tui/store_app.py` — needs async TUI event loop

### Main.py remaining testable (~368 miss after TUI exclusion)
- `cmd_emit` (large complex function) — more paths:
  - Template qualifier (slash-split vertex_ref like "comms/native") L1626-1627
  - Vertex-kind ambiguity resolution path L1635-1665
  - Dry-run path L1730+ (various branches)
  - `_ensure_vertex_store_db` call L1740+
- `_resolve_combine_child` (16 miss, 61%) — vertex/template resolution chain
- `_run_close` (22 miss, 12%) — needs real fact with fold state + close args
- `_try_topology_from_store` (26 miss, 59%) — needs store with _topology facts
  - Could be set up by running `emit_topology` first then calling this
- `_whoami_from_identity_store` (10 miss, 45%) — needs identity store
- `_run_fold_fast` (still ~9 miss) — some paths remaining
- `_run_test` (9 miss) — --input mode (parse pipeline with input file)

### Integration test patterns that work well
- `main(["read", str(vpath), "--static", "--plain", "--kind=KIND"])` → bypasses _try_fast_read
- `main(["sync", "--force", str(vpath)])` → triggers sync + boundary evaluation
- `main(["test", str(loop_file), "--plain"])` → runs .loop sources
- Vertex with `fold_collect` → fold_view gets sections with items
- Vertex with `boundary after=1` + run clause → triggers run during sync

### try_topology_from_store approach
1. Create vertex with store
2. Emit facts to populate store
3. Call `emit_topology(vpath)` to write _topology facts to the store
4. Then call `_try_topology_from_store(store_path)` directly
5. This would cover L1209-1244 (26 lines)

### _run_close approach
- Needs: vertex with `close` kind in a loops block + real fact data
- Call `main(["close", str(vpath), "kind", "name", "message"])`

### Next step-up targets (in order of bang-for-buck)
1. `_try_topology_from_store` via emit_topology + direct test (26 lines)
2. `cmd_emit` template qualifier path (slash-split)
3. `_run_test --input` mode (parse pipeline test)
4. `_run_close` with minimal setup
