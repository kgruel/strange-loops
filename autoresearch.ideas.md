# Autoresearch Ideas: engine Coverage Efficiency

## Current state: 92.5% line, 86.2% branch — 133 miss
## Progress: 83.4% → 92.5% (+208 lines covered across 2 sessions)

## Engine nearing completion (133 miss)
- vertex_reader.py: 95 miss — all combine/discover paths, need multi-vertex setups
- compiler.py: 15 miss — template source search fields, compile_sources path
- vertex.py: 14 miss — deep boundary edges, parse pipeline replay
- sqlite_store.py: 2 miss — except clause (unreachable without ImportError mock)
- Small: builder(2), cadence(2), executor(2), loop(1) — mostly dead code

## Next package candidates
1. **lang** — KDL loader + validator. Likely high uncovered branches.
2. **store** — Store operations (slice, merge, search, transport).
3. **loops** (CLI app) — emit, fold, stream commands. Higher LOC cost.

## Benchmark noise problem
- test_time_s varies 2-7s for identical code due to system load
- Efficiency metric dominated by runtime variance, not test quality
- Warmup+min2 helps but doesn't eliminate spikes
- Consider switching to `test_LOC / covered_lines` (structural only) for step-down decisions

## Dead code in engine
- loop.py L83: `receive_mut` path — replay cursor calls fold_one_mut directly
- sqlite_store.py L126-127: except clause — requires ImportError from atoms
- builder.py L276,287: rarely-used builder methods
- cadence.py L101,111: edge cadence modes

## Compression opportunities (deferred)
- test_vertex_replay_coverage.py: inject_fact helper already saves ~10 LOC per test
- test_vertex.py boundary tests still have manual Loop() construction
- test_compiler.py has repeated KDL parsing patterns
