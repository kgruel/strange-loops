# Autoresearch Ideas

## Current State (experiment #191)
- **loops**: 96.9% (4713/4770 covered, 57 miss)
- Efficiency: 9.06 (baseline=4.53) — timing variance causing high values
- Key files: main.py 99%, devtools.py 99%, TUI files 100%, resolve.py 97%

## Remaining 57 miss lines

### Confirmed dead code (never reachable):
- `fetch.py L82, L246-247, L325, L402` (5 lines) — defensive checks, structurally impossible
- `fold.py L182, L266, L352` (3 lines) — impossible filter combinations
- `stream.py L192` (1 line) — redundant search loop after first loop covers same keys
- `store.py L91` (1 line) — `Fact.payload` always a dict in practice
- `vertices.py L118` (1 line) — glob only returns .vertex so suffix check always False
- `resolve.py L526-528` (3 lines) — config_parent can only exist if _resolve_vertex_for_dispatch already found it
- `main.py L1342` (1 line) — _try_fast_read fallback: _resolve_vertex_for_dispatch + _resolve_named_vertex always agree
- `devtools.py L84` (1 line) — run_cli never returns non-zero for validate unless argparse fails

### Hard to reach (complex setup):
- `emit.py L140-144` (dead: writable vertex found but _resolve_vertex_store_path returns None — can't happen since writable means has store)
- `emit.py L149` (except LoopsError in dry_run — already covered in committed tests)
- `emit.py L209-217` (multi-template emit without qualifier — needs multiple template sources)
- `emit.py L223-230` (template with no from_ — needs specific template config)
- `emit.py L236, L240-247, L251-255, L258-266, L268-272, L275-285` (population path errors)
- `emit.py L304-316` (population seeding during emit — needs list+template+emit combo)
- `emit.py L330-331` (boundary run during emit — needs tick.run set)
- `emit.py L346-348` (exception in program.vertex.receive — unusual runtime error)
- `emit.py L548-549` (validate_emit error in _run_close — needs observer restrictions)
- `pop.py L155, L222, L289` (legacy no-header path, multi-template template assignment)
- `resolve.py L191` (stale store path in topology cache)
- `resolve.py L253-254` (topology emit exception — best-effort catch)
- `resolve.py L339, L343` (key_field is None after kind in topo — requires malformed topo cache)

### Still reachable:
- `emit.py L330-331`: tick.run fires boundary run during emit. Need a vertex with `run { ... }` boundary clause AND fact that triggers the boundary count. Likely ~15 LOC test.

## Efficiency improvement strategy
- The timing variance (3.13-5.33s) is the main obstacle to efficiency gains
- With test_loc=8676, need ~2.8s timing to hit efficiency=6.5
- Step-down: try to identify and remove duplicate integration tests
  - test_integration.py has ~1950 LOC — check if any classes are redundant
  - test_main_helpers.py has ~600 LOC — check for duplication with test_integration.py

## Step-down opportunities
1. `TestEmitMissLinesFix` in test_integration.py (2 tests) — these cover lines already covered
2. `TestMainPyMissLines` in test_integration.py (2 tests) — may be redundant with other tests
3. Merge small classes in test_integration.py into larger ones (reduce class overhead)
4. The `test_run_test_live_plain_limit_break` test is slow (runs printf subprocess) — 
   could be replaced with a mock that doesn't run a subprocess

## Emit.py L330-331 (tick.run boundary fires subprocess)
Setup needed:
- Vertex with loop that has boundary.run clause
- Emit enough facts to trigger the boundary count
- `_execute_boundary_run` is called with the run command
- This IS testable via cmd_emit with appropriate vertex config
The run clause would be: `boundary { count 2 run "echo done" }`
Need engine.builder to support `run` in boundary config.
