# Autoresearch: speed up representative `loops read` workloads

## Objective
Optimize the hot path behind the `loops` CLI's primary read workflow. The benchmark exercises two representative user-facing operations against a synthetic but realistic local vertex store:

1. `loops read bench --plain` — folded state rendering
2. `loops read bench --facts --kind task --plain` — event stream rendering

The workload is intentionally in-process so experiments can run quickly, but it still covers CLI argument parsing, vertex resolution, store reads, fold/stream fetches, rendering, and plain-text output.

## Metrics
- **Primary**: `total_ms` (ms, lower is better)
- **Secondary**: `fold_ms`, `stream_ms`

## How to Run
`./autoresearch.sh` — prints `METRIC name=number` lines.

## Files in Scope
- `apps/loops/src/loops/main.py` — CLI dispatch and read command wiring
- `apps/loops/src/loops/commands/fetch.py` — fold/stream fetch logic
- `libs/engine/src/engine/vertex_reader.py` — vertex-backed read helpers
- `libs/engine/src/engine/store_reader.py` — SQLite read path
- `autoresearch.sh` — benchmark harness
- `autoresearch.checks.sh` — correctness checks for kept changes
- `autoresearch.md` — experiment log and context
- `autoresearch.ideas.md` — backlog for promising deferred ideas

## Off Limits
- Public behavior changes unrelated to read performance
- New runtime dependencies
- Broad refactors outside the read path

## Constraints
- Keep benchmark workload semantics stable
- No new dependencies
- Kept changes must pass `autoresearch.checks.sh`
- Prefer simpler code when performance is equal

## What's Been Tried
- Initial benchmark selection: mixed `loops read` workload focused on fold + facts paths.
- Big win: collapsed many per-line `Block.text(...)` allocations in `apps/loops/src/loops/lenses/fold.py` into batched `Block.column(...)` construction. This substantially reduced fold rendering overhead in piped/plain mode without changing output structure.
- Follow-up win: applied the same batching approach to `apps/loops/src/loops/lenses/stream.py`, reducing the remaining stream rendering overhead while preserving emitted plain-text layout.
