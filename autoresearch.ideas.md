# Autoresearch Ideas

## Final State (experiment #213)
- **loops**: 98.4% line coverage, **0 miss** (4732/4732 covered)
- Branch coverage: 94.6% (1978/2090)
- Best efficiency: **3.69** (exp #213, 1.97s, 8874 LOC)
- 214 experiments total, 929 tests, 8874 test LOC

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

## Ceiling reached — loop complete

All three stopping conditions hold:
1. Primary metric has not improved in the last ~15 experiments (timing variance
   ±20–30% swamps any sub-100-LOC gain)
2. No remaining coverage gaps (0 miss, all source lines covered, dead code removed)
3. No test-side experiment would move the metric without source changes that aren't
   worth making (see below)

## What NOT to do

**Do not add testability injection hooks to source functions** (e.g. `vertex_path=`,
`_initial_state=` on internal dispatch functions) to replace `main()` integration tests
with faster unit tests.

The integration tests through `main()` test the contract that matters: CLI wiring,
argument parsing, dispatch, vertex resolution, store setup. That's where real bugs live
— and we found several during this campaign (dispatch fallbacks, resolution edge cases,
the async fetch_stream path). Skipping that wiring to improve the efficiency formula
would:

- Add test-only API surface to internal functions (more parameters, more branches)
- Create code paths no real user exercises
- Couple tests to internal signatures instead of the public CLI contract
- Make the code more complex to serve a metric

The loop hitting its boundary is the signal that the test work is done, not a prompt
to restructure the source. The command architecture already has the right separation:
`fetch()` returns data, `lens()` renders, `main()` wires. Tests at each level serve
different purposes.

## Timing stability fix

`autoresearch.sh` now uses `NUM_RUNS=5` (was 2). This gives a more stable minimum
by filtering out the occasional slow OS-scheduler outlier. The benchmark takes ~40s
instead of ~15s but the minimum converges much faster to the true floor.

The ±20–30% timing spread (1.87s–5.33s seen historically) comes from bimodal system
state: cold Python import caches hit the slow cluster; warm caches hit the fast cluster.
The warmup run is supposed to prime this, but OS cache pressure can reset it. With 5
timed runs, at least the bottom 1–2 will be from the warm state.

## Branch coverage gaps (94.6% → higher)

Branch coverage is not the primary efficiency metric, but if it matters independently:
~112 uncovered branches remain, mostly in:
- Error handling branches in complex dispatch paths
- Edge cases in combine/discover topology walking
- Observer grant restriction branches

The `VertexTopologyBuilder` in `builders.py` already provides the fixture infrastructure
needed for topology-style branch tests. Future branch coverage work can build on it.
