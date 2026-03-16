# Autoresearch Ideas: Test Coverage Efficiency

## Done recently
- `commands/vertices.py` direct helper + discovery tests
- `commands/store.py` direct path/fetcher tests
- `gist.py` direct lens tests
- `identity.py` observer resolution tests
- `fetch.py` key drill-down and query-path tests
- `_helpers.py` near-complete helper coverage
- `pop.py` / `pop_store.py` helper and bootstrap/template-filter tests

## Current optimization heuristic
Prefer tests that increase structural coverage density:
- broad integration tests that cover many paths per added line
- direct helper tests for pure command/data logic
- reusable fixtures/builders over repeated hand-written setup
- seam-based tests that replace many repetitive assertions with a few broad, meaningful scenarios

## Remaining worthwhile targets
- Full template population CLI edge cases, but only if coverage gain per added line looks strong
- Painted/mock seam for `main.py` rendering paths, if stable and not brittle
- Small remaining fetch/pop edges only when they unlock broad paths

## Probably not worth it
- `tui/store_app.py`
- tiny isolated edge cases in engine internals
- micro-optimizing benchmark-facing runtime at the expense of cleaner tests
