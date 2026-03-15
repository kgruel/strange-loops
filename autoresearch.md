# Autoresearch: optimize the `loops emit` path

## Objective
Reduce the in-process cost of emitting a single fact into a vertex store.

The emit path is the primary write interface for agent swarms — every fact
an agent produces flows through it. The goal is both speed and architectural
clarity: the previous vertex hotpath autoresearch proved that optimization
experiments are diagnostic — they reveal which phases are distinct and where
the real cost lives.

## Measured Baseline

### Full end-to-end breakdown (project store, ~300 facts)

```
uv + Python startup:   27ms   (can't optimize — external)
Module imports:         24ms   (from loops.main import app)
CLI dispatch:           14ms   (argparse + routing)
cmd_emit lazy imports:  82ms   (atoms, lang, engine, painted — first-call cost)
Vertex resolution:       0ms   (finding .vertex file)
Load + replay:          13ms   (compile + replay 300 facts)
Receive + close:         0ms   (single fact + SQLite close)
─────────────────────────────
Total:                ~160ms   (subprocess measurement: ~277ms with overhead)
```

### In-process vertex work (what this benchmark measures)

| Phase | Time | % |
|-------|------|---|
| Compile (parse + compile + materialize) | 0.4ms | 5% |
| **Replay (300 facts)** | **7.4ms** | **90%** |
| Receive | 0.1ms | 2% |
| Close | 0.2ms | 3% |
| **Total** | **8.2ms** | |

**Replay is 90% of in-process emit cost.**

### What's NOT in scope for this experiment

The 82ms lazy import cost (atoms, lang, engine, painted on first call) is
a significant chunk of end-to-end time, but it's a one-time refactoring
problem (defer painted for emit, since emit doesn't need terminal rendering
for the success path). Not suited to autoresearch's iterative loop — it's
a single structural change. Filed separately.

## Metrics
- **Primary**: `emit_total_ms` (ms, lower is better) — full in-process emit cycle
  (compile + replay + receive + close)
- **Secondary**: `compile_ms`, `replay_ms`, `receive_ms`, `close_ms`

## How to Run
`./autoresearch.sh` — prints `METRIC name=number` lines.

The benchmark (`benchmarks/benchmark_emit_path.py`) creates a realistic
vertex store (~300 facts across 6 kinds matching a real project store),
then measures repeated full emit cycles via `load_vertex_program()`.

## Files in Scope

The emit path crosses lib boundaries — this is a monorepo-level experiment:

- `libs/engine/src/engine/program.py` — `load_vertex_program()`: orchestrates
  parse → compile → collect_sources → validate_dag → materialize → replay.
  For emit, source collection and DAG validation may be unnecessary work.
- `libs/engine/src/engine/vertex.py` — `receive()`, `replay()`:
  the runtime hot path. Replay is the measured bottleneck.
- `libs/engine/src/engine/compiler.py` — `compile_vertex_recursive()`,
  `materialize_vertex()`, `collect_all_sources()`: compilation and materialization.
- `libs/engine/src/engine/store.py` — `SqliteStore`: append, since, between, close.
  Store I/O is on the critical path for replay reads and fact writes.
- `libs/lang/src/lang/` — vertex file parsing. KDL parse cost per invocation.
- `benchmarks/benchmark_emit_path.py` — the benchmark itself.

## Off Limits
- Changing emit semantics (facts must still route through the vertex runtime)
- Breaking the public `loops emit` CLI interface
- Modifying test fixtures or test behavior
- New runtime dependencies
- Changes outside the emit/vertex path (no CLI restructuring)

## Constraints
- `uv run --package engine pytest libs/engine/tests` must pass
- `uv run --package loops pytest apps/loops/tests` must pass
- Emitted facts must be stored and retrievable after the emit completes
- Boundary firing must still work (emit session.end must produce a tick)
- Prefer structural simplifications over micro-optimizations

## What's Been Tried
Nothing yet — this is a fresh experiment on the emit path.

## Architectural Context

### The emit call chain
```
load_vertex_program()           libs/engine/program.py
    → parse_vertex_file()         libs/lang/
    → compile_vertex_recursive()  libs/engine/compiler.py
    → collect_all_sources()       libs/engine/compiler.py  ← unnecessary for emit?
    → validate_dependency_graph() libs/engine/compiler.py  ← unnecessary for emit?
    → materialize_vertex()        libs/engine/compiler.py
    → vertex.replay()             libs/engine/vertex.py    ← 90% of cost
→ vertex.receive(fact)            libs/engine/vertex.py
→ store.close()                   libs/engine/store.py
```

### What the vertex hotpath research proved
The previous autoresearch on `libs/engine/vertex.py` (50 experiments, 14%
improvement) found that:
- **Specializing common cases** beats caching or micro-optimization
- **Removing hot-path branching** matters more than reducing computation
- The vertex has three distinct internal phases (gate/fold/boundary) that
  were tangled — making them explicit was the real win

The same principle likely applies here: the emit path has phases that could
be specialized for the common case (single fact, no sources needed, no DAG
validation needed).

### Why this matters for agent swarms
In the task orchestration system, workers emit facts via CLI. Each `loops
emit` invocation pays the full compile → replay → receive cost. At 50
parallel workers each emitting ~30-50 facts per task, the cumulative replay
cost across a session adds up.

### The topology question
The autoresearch should discover whether the evidence supports:
- **Faster replay** — micro-optimize the O(n) scan (limited upside)
- **Less replay** — incremental replay from last boundary, not from fact 0
  (requires reading the last tick and skipping already-folded facts)
- **Skip unnecessary compilation work** — source collection and DAG
  validation are for `run`, not `emit`
- **Something else** the experiments reveal

The store already supports `since(cursor)` — replay currently calls
`since(0)` unconditionally. Whether a partial replay is correct depends on
whether fold state can be reconstructed from a tick snapshot. That's the
architectural question the experiments should probe.
