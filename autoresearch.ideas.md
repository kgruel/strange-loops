# Autoresearch Ideas

## Progress Summary
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%
- **loops**: 79.0% (3764 covered, 914 miss) — best efficiency 2.49 (exp 44)
- 69 experiments, 67 keeps!

## Remaining loops app (914 miss)

### Blocked TUI (695 miss)
- `tui/autoresearch_app.py` + `tui/store_app.py` — async TUI, not testable

### Main.py remaining (~200 miss after TUI)
- `cmd_emit` (54 miss, 16%) — complex vertex resolution + lazy painted proxies
- `_run_fold` L2155-2181 — async fetch_stream + autoresearch TUI handler body
- `_run_sync_aggregate` L818-819, 837-838 — log_error callback + run boundary in aggregate
- `_run_store` L2384, 2391-2397 — dispatch via vertex-first ("myproject store")
- `commands/fetch.py` L2013-2015 — query shift when first arg isn't a vertex

### Targets by bang-for-buck
1. **`cmd_emit` lazy proxy** (L1570-1590) — _BlockProxy/__getattr__ fires on first error in emit
   - Trigger: emit with invalid/failing data that shows error block
2. **`_run_store` L2391-2393** — vertex name resolution (e.g., `main(["myv", "store"])`)
   - Use vertex named NOT in `_COMMANDS` (not "test", "compile", etc.)
3. **`_run_sync_aggregate` L818-819** — source that produces error facts
   - Complex: requires a source script that exits with code 1 (error)
4. **`commands/pop.py`** (18 miss) — population commands (add, rm, export error paths)
5. **`lenses/fold.py`** (9 miss) — deep rendering paths  

### Architecture insight: _COMMANDS excludes
- `_DEV_COMMANDS = {"test", "compile", "validate", "store"}` — go through direct dispatch
- `_SETUP_COMMANDS = {"init", "whoami", "ls", "add", "rm", "export"}` — also direct
- For vertex-first dispatch, vertex name must NOT be in _COMMANDS
- So `main(["myv", "store"])` where "myv" resolves → _dispatch_observer("myv", vpath, ["store"]) → _run_store([], vertex_path=vpath) → L2384!

### Quick wins remaining in fetch.py
- L2013-2015: `query = first` when first arg isn't a vertex in _run_stream
  - Use `main(["read", "--facts", "--since", "1h"])` → route to stream via facts+since
  - But this needs local vertex to be resolved  
