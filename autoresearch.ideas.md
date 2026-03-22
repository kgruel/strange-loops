# Autoresearch Ideas

## Progress Summary
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%
- **loops**: 79.8% (3792 covered, 886 miss) — 88 experiments, 84 keeps
- Session 3 best efficiency: 2.49 (exp 44), current 4.21

## Remaining loops (886 miss non-TUI)

### Blocked TUI (695 miss)
- Not testable without async TUI harness

### main.py remaining ~140 miss
- `cmd_emit` (41 miss):
  - L1570-1590: Lazy proxy loading — likely dead code (Block always loaded before show)
  - L1756-1777: Population template error paths (complex, needs .list file)
  - L1687-1696: store_path None + exception in _resolve_writable (harder paths)
- `_run_fold` L2155-2182: async fetch_stream + autoresearch TUI — not testable
- `_run_store` L2414-2429: async + TUI paths — not testable
- `_run_close` L2620-2721: requires actually doing a close (non-dry-run) 
  - L2620: fallback key check for collect-fold items
  - L2657: artifact kind filtering
  - L2720: error output on store exception
- `_topology_kind_keys_and_stores` L1260-1271: needs parse error + topology caching
  - L1260-1261: bad vertex file → return {}, []
  - L1265-1271: fast path with existing store + _topology facts

### Accessible new targets
1. `_topology_kind_keys_and_stores` L1260-1261 (exception path) — pass bad vertex file
2. `_topology_kind_keys_and_stores` L1265-1271 (fast path with topology) — via emit_topology  
3. `_run_close` non-dry-run (L2620, 2657) — full commit of close command
4. `_run_test` async stream paths (L710-725) — hard, needs async test
5. `commands/pop.py` (18 miss) — add/rm/export error paths

### Architecture: _topology_kind_keys_and_stores L1265
Called via `_resolve_entity_refs` in `cmd_emit` when payload has "kind/value" references.
OR called via `_ensure_topology()` closure in `_resolve_entity_refs`.
To test: emit with payload containing "thread/my-task" style cross-reference.

### _run_close non-dry-run
- Requires vertex with fold_by loop + fact with matching name + close without --dry-run
- L2657: artifact kinds filtering (needs facts of kinds: decision, task, thread, change)
