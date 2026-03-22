# Autoresearch Ideas

## Final State (experiment #206)
- **loops**: 98.4% line coverage, **0 miss** (4732/4732 covered)
- Branch coverage: 94.6% (1978/2090)
- Efficiency: ~3.64 at best timing (1.88s); 4.73 at last run (2.44s timing variance)
- 206 experiments total, 945 tests, 9175 test LOC

## Dead code removed this session (#202–#206)

Six confirmed-dead paths removed from source — each traced to an invariant in the
type system, engine, or data model:

| File | Lines | Invariant |
|------|-------|-----------|
| `fetch.py` | L82 | `vertex_fold(kind=x)` returns single-kind state → kind-filter guard always False |
| `stream.py` | L192 | Last-resort loop checks strict subset of first loop's fields → unreachable return |
| `fetch.py` | L324 | Engine always sets `tick.since` to first-fact timestamp → `else: facts = []` never fires |
| `devtools.py` | L84 | `run_cli` always returns 0 in `_run_validate` → `if rc != 0` never fires |
| `main.py` | L1342 | `_resolve_named_vertex` checks same config path as `_resolve_vertex_for_dispatch` → fallback unreachable |
| `emit.py` | L140–144 | `_resolve_writable_vertex` non-None ↔ vertex has store → `_resolve_vertex_store_path` always non-None |

## If line coverage needs to go higher

Not possible without source changes. At 0 miss, all source lines are covered.

## Branch coverage gaps (94.6% → 100% would need ~112 branches)

Branch coverage doesn't affect the primary efficiency metric (which uses covered_lines).
If branch % matters independently, the uncovered branches are mostly:
- Error handling branches in complex dispatch paths
- Edge cases in combine/discover topology walking
- Observer grant restriction branches

These would require the same kinds of topology tests built in this session, just more
combinations of vertex configurations.

## Step-down opportunity

At 9175 test LOC, there may be 100–200 LOC of consolidation left:
- Some tests added to cover lines that were later source-cleaned (slightly redundant)
- `TestEmitMissLinesFix.test_emit_to_store_less_vertex_returns_error` was written for
  L140/144 (now removed); now tests the `writable_path is None` branch (still useful
  but could be merged with another emit error test)
- VertexTopologyBuilder in builders.py enables topology fixture reuse — future tests
  using it should stay small

Step-down is only worth it if timing is stable at 2.0s or less. At 1.88s best timing,
efficiency is already 3.64–3.65. The 3.57 prior best is essentially equivalent given
the ±15% timing variance of the test suite.

## Ceiling reached — loop complete

All three stopping conditions hold:
1. Primary metric cannot improve further (0 miss → covered_lines is at maximum)
2. No remaining gaps (all lines covered, dead code removed)
3. Next efficiency gains require either source changes or LOC reduction of 700+ lines
