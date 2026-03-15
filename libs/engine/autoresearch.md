# Autoresearch: optimize engine.Vertex hot path

## Objective
Reduce total runtime of mixed `Vertex` workloads in `libs/engine`, especially the hot paths around `receive()`, replay, and boundary evaluation.

The goal is not just raw speed. We also want changes that move the implementation toward cleaner separation of concerns inside `src/engine/vertex.py`, particularly around routing, replay bookkeeping, and boundary handling.

## Metrics
- **Primary**: vertex_mixed_ms (ms, lower is better)
- **Secondary**: receive_ms, boundary_ms, replay_ms, topology_ms, facts_per_sec

## How to Run
`./autoresearch.sh`

The script emits lines like:

`METRIC vertex_mixed_ms=12.34`
`METRIC receive_ms=4.20`
`METRIC boundary_ms=2.10`
`METRIC replay_ms=5.01`
`METRIC topology_ms=1.03`
`METRIC facts_per_sec=81234`

## Files in Scope
- `src/engine/vertex.py` — main routing/orchestration hot path
- `src/engine/loop.py` — fold/fire semantics for per-loop boundaries
- `src/engine/projection.py` — low-level fold mechanics
- `src/engine/*.py` — new internal helpers if extraction improves structure/perf
- `benchmarks/benchmark_vertex_hotpath.py` — benchmark workload
- `tests/test_vertex.py` — boundary/routing behavior coverage
- `tests/test_evaluate_boundaries.py` — replay/boundary semantics
- `tests/test_vertex_nesting.py` — child forwarding coverage

## Off Limits
- Breaking public API
- New dependencies
- Changes outside `libs/engine` unless required for test/benchmark wiring

## Constraints
- Engine tests must pass
- Preserve behavior for:
  - loop boundaries
  - vertex boundaries
  - replay
  - child forwarding
  - grant/observer gating
- Keep benchmark fast enough for many repeated runs
- Prefer simpler designs when performance is equal

## What's Been Tried
- Initial setup: benchmark should reward improvements in mixed receive, boundary, replay, and topology scenarios.
- Initial hypothesis: `Vertex.receive()` is overloaded and likely the dominant optimization target.
- Expected best directions:
  - split boundary logic from routing
  - reduce repeated branchy checks in live receive path
  - specialize replay behavior
  - cache route/boundary lookups
- Watch for overfitting to synthetic microbenchmarks; keep workload mixed.

## Overall Summary
A 50-run autoresearch session improved the mixed benchmark from **67.692 ms** to **58.394 ms** at best (~13.7% faster).

Best commit:
- `6f942c9` — simplify loop receive dispatch in `Vertex.receive()` by handling the no-loop case first

Most of the real wins came from **specializing common cases** and **removing hot-path branching**, not from adding more caching or from clever micro-optimizations.

The strongest successful themes were:
- **Replay specialization** — avoid paying full live `receive()` costs during replay
- **Fast paths for absent features** — no routes, no parse pipelines, no children, no loop-level boundaries
- **Boundary evaluation specialization** — especially the common vertex-boundary-only case
- **Small control-flow simplifications** — branch shape mattered more than expected

Changes that tended **not** to help:
- extra local aliasing
- more cache layers
- boundary metadata reshaping
- store/tick lookup shortcuts
- child-loop micro-tweaks
- rewrites that looked cleaner but did not clearly remove work

## Recommendation for the Next Session
Do **not** spend another session chasing tiny branch-shape tweaks first. The successful experiments point to a clearer architectural direction:

Treat `Vertex` as three distinct internal phases instead of one heavily branched path:
1. **Live receive path**
   - gating
   - store append
   - route resolution
   - parse application
   - fold into loops
   - child forwarding
   - immediate boundary firing
2. **Replay path**
   - fold reconstruction only
   - no store append
   - no live boundary firing
   - minimum routing/parsing/topology work needed for correctness
3. **Boundary evaluation path**
   - scan period facts
   - vertex-boundary logic
   - loop-boundary logic
   - condition checks
   - tick persistence

Recommended refactor order:
- First, extract private helpers in `src/engine/vertex.py` with no behavior change:
  - `_receive_live_fact(...)`
  - `_replay_fact(...)`
  - `_evaluate_vertex_boundary_only(...)`
  - `_evaluate_mixed_boundaries(...)`
- Then consider moving concerns into focused internal modules:
  - routing / parse application
  - receive policy / gating
  - boundary evaluation
- Re-benchmark after each extraction step; preserve the current performance wins while making the phase split explicit.

If a future session resumes optimization rather than refactoring, start from the current best commit and benchmark first. But the evidence so far suggests that the best next gains are likely to come from **structural separation of phases**, not more isolated micro-opts.
