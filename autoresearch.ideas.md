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

## Dead code candidates (confirmed by coverage exhaustion)
- `stream.py L192`: `return payload[key]` in second "last resort" loop — unreachable because the first loop (L165-178) already checks the same `_LABEL_FIELDS` keys; second loop can never find something first loop missed
- `lenses/fold.py L182`: `label = "Skipped"` — `skipped_sections` only populated inside `refs_filter` or `facts_filter` blocks, so the `else: label = "Skipped"` branch requires neither filter but non-empty skipped_sections, which is structurally impossible
- `commands/store.py L91`: `info["payload_keys"] = []` — only hit when `recent[0].payload` is not a dict; `Fact.payload` is always a dict in practice
- `commands/vertices.py L118`: `continue` — inside `sorted(base_dir.glob("**/*.vertex"))` loop, suffix check `!= ".vertex"` is always False since glob only returns .vertex files

## Remaining TUI misses (64 lines)
- `tui/autoresearch_app.py` 23 miss — most are render branches for empty/edge states and _on_start async path
- `tui/store_app.py` 41 miss — similar pattern; many are _load_store async path lines

## emit.py (39 miss) — hardest cluster
- Population template paths (multi-template, from-file) require complex vertex setup
- Store resolution error paths (no writable vertex in dry-run vs non-dry-run)
- Entity ref resolution paths need cross-vertex topology with refs in payloads

## resolve.py (14 miss) — topology cache paths
- L191: stale store path (topology cache entry has path that no longer exists)
- L253-254: emit_topology exception catch (best-effort cache refresh)
- L284-285: _resolve_entity_refs LoopsError on writable vertex
- L297: topology cache hit (fast path in _topology_kind_keys_and_stores)

## Additional dead code candidates (confirmed unreachable)
- `commands/fetch.py L82`: `continue` in fetch_fold — `vertex_fold` already pre-filters by kind, so the defensive filter loop never skips sections
- `commands/fetch.py L246-247`: `v = {"items": [...]}` dict path in fetch_ticks — fold_collect stores payload as `{"items": [list]}` at top level, so `v` is always a list (L248-249), never a dict with nested "items"
- `commands/fetch.py L325`: `facts = []` in fetch_tick_facts — tick.since is always set by vertex_ticks for any real boundary
- `commands/fetch.py L402`: duplicate fact ID dedup — facts have unique IDs within a vertex; cross-tick deduplication never fires in practice
- `lenses/fold.py L266, L352`: "no connected items" after refs filter — section-level pre-filter in fold_view ensures at least 1 connected item before calling _render_grouped/_render_flat, making the inner filter check always find items

## Practical coverage ceiling
Accounting for all confirmed dead code:
- ~17 dead lines: stream.py L192, store.py L91, vertices.py L118, fold.py L182/266/352, fetch.py L82/246/247/325/402, tui L567/L109 (_on_start async)
- Plus ~112 async/TUI dispatch lines in main.py (L383-409, L642-657) and devtools.py async stream (L200-215)
- Realistic ceiling: ~4750-4760 covered lines out of 4769 (≈99.7% minus confirmed dead code)
