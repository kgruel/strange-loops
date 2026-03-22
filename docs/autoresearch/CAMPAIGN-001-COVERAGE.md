# Campaign 001: Test Coverage (2026-03)

First autoresearch campaign. Target: loops app test coverage efficiency.

## Results

| Metric | Start | End | Change |
|--------|-------|-----|--------|
| Coverage | ~85% | 98.4% (0 miss) | +13.4 pp |
| Efficiency | ~8+ | 3.43 | -57% |
| Test LOC | ~4500 | 8874 | +97% |
| Test time | ~3s | 1.83s (best) | -39% |
| Experiments | 0 | 218 | — |

## Timeline

- **#1-#39**: atoms, engine, lang packages (warm-up, methodology refinement)
- **#40-#186**: loops app step-ups (85% -> 96.9%)
- **#187-#199**: loops app step-downs (efficiency compression)
- **#200-#206**: dead code removal from source (human intervention)
- **#207-#214**: final compression pass (-301 LOC)
- **#215-#218**: ceiling — timing variance binding, loop halted

## Key interventions (human + loops-claude)

1. **Timing metric fix (#192)**: Separated timing from coverage instrumentation.
   Coverage adds ~1.7x overhead. The loop was optimizing against inflated numbers
   for the entire campaign. Efficiency rebased from 9.06 -> 4.93 immediately.

2. **Dead code removal (#200-#206)**: 13 source lines removed across 9 files.
   Loop can't touch source — needed human to trace invariants and remove
   unreachable branches. Each removal has a documented invariant argument.

3. **Test quality review (#218)**: Found 5 tautological assertions (`or True`
   pattern), 4 weak `isinstance(rc, int)` checks, 1 fragile env var pattern.
   The loop games its own metric when it can't determine the real assertion.

## What the loop built

- `apps/loops/tests/builders.py` — `FoldStateBuilder`, `VertexTopologyBuilder`,
  `StorePopulator` (reusable test infrastructure)
- `apps/loops/tests/conftest.py` — composable fixtures (`loops_home` -> `loops_env`
  -> `simple_vertex`/`project_vertex`)
- 940+ tests covering every reachable line in the loops app

## What the loop couldn't do

- Self-diagnose measurement errors (timing bug was consistent across runs)
- Accurately assess its own state at high coverage (claimed 35 dead code, actual ~13)
- Write real assertions when it couldn't predict output (fell back to `or True`)
- Touch source code (dead code removal, testability changes)

## Lessons for next campaign

1. Let the loop run autonomously for 80-95%
2. Human review at ~95% to fix measurement issues and remove source dead code
3. Let the loop push through 95-98%+ with corrected metric
4. Human review of final test quality — fix assertion gaming
5. `autoresearch.md` and `autoresearch.sh` at repo root are reusable as-is

## Files

- `autoresearch.jsonl` — raw experiment data (218 entries)
- `autoresearch_journey.svg` — visualization of the full campaign
- `autoresearch.ideas.md` — the loop's running notes (final state + dead code log)
- `make_chart.py` — chart generator (reads jsonl, writes svg)
