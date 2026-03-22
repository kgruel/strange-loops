# Autoresearch Ideas

## Progress Summary (100 experiments!)
- **atoms**: 98.1% | **engine**: 92.5% | **store**: 99.6% | **lang**: 98.4%
- **loops**: 80.5% (3819 covered, 859 miss) — 100 experiments, 94 keeps
- Best efficiency: 2.49 (exp 44). Current: 4.42 (2.4% below baseline 4.53)

## Remaining loops (859 miss)

### Blocked TUI (695 miss)
- `tui/autoresearch_app.py` + `tui/store_app.py` — async TUI

### Non-TUI remaining (~164 miss)
- main.py: ~112 miss
  - `cmd_emit` (41 miss): L1570-1590 (lazy proxies = likely dead), L1756-1777 (population templates), L1687-1696 (store resolution errors)
  - `_run_fold` (18 miss): L2155-2182 (async + autoresearch TUI handler body)
  - `_run_store` (13 miss): L2414-2429 (async + TUI)
  - `_run_close` (12 miss): L2595-2599 (kind-shift), L2720 (error output)
  - `_resolve_entity_refs` (3 miss): complex cross-reference resolution
- commands/pop.py (18 miss): add/rm/export error paths

### Promising targets
1. `_run_close` L2595-2599 (kind-shift when first arg isn't vertex):
   - `close thread task1` where "thread" doesn't resolve as vertex → kind shift
   - But wait — my TestCloseCommand::test_close_without_vertex already does this!
   - Need to check if those lines are actually still miss
2. commands/identity.py (6 miss): L34, L75, L78, L114 
   - walkup observer resolution paths
3. commands/vertices.py (2 miss): L106 (duplicate), L118 (unreachable?)
4. lenses/fold.py (9 miss): deep rendering paths

### Quick wins that should add lines
1. `_run_fold_fast` L2357-2359: exception in `call_lens` — need a lens that throws
   - Create a broken lens file and use --lens pointing to it
2. `_run_store` L2397 — LOOPS_HOME/.vertex fallback path
   - The .vertex file has suffix="" which breaks resolve_store_path — need fix or special handling

### Pattern: module-level imports to reduce LOC
- The main test file has some import patterns that could still be pulled up
- But timing variance makes step-downs unreliable; focus on step-ups

### Observation
- 94 out of 100 experiments kept (94% success rate!) 
- We've reduced miss from 1878 → 859 (54.3% reduction!)
- main.py went from 71% → 93.2% coverage
