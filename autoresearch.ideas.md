# Autoresearch Ideas: engine Coverage Efficiency

## Current state: 88.0% line, 79.9% branch — 231 miss

## Remaining by file

### vertex_reader.py (~138 miss)
- vertex_fold (31 miss) — fold state reconstruction from store
- _collect_topology_info (15 miss) — needs combine/discover .vertex files
- _specs_match (10 miss) — spec comparison for merge validation
- _resolve_store (10 miss) — already partially covered
- _collect_source_specs (8 miss) — merge source specs
- _combined_read/search/ticks/summary (19 miss) — combine paths
- _raw_to_fold_state (7 miss) — raw-to-typed fold conversion
- vertex_tick_fold (6 miss) — tick fold state
- _resolve_discover_stores (5 miss) — discover glob resolution
- Smaller functions: _loops_home, _resolve_combine_stores, etc.

### vertex.py (~57 miss)
- replay fast paths: since_raw (L617-633), already partially covered
- evaluate_boundaries (16 miss) — complex state machine
- _evaluate_vertex_only_boundaries (24 miss) — vertex-level boundary eval
- replay vertex period reconciliation (L683-692)

### Other files (~36 miss total)
- compiler.py: 23 miss — map_transform, fold_op edges, compile_source, collect_search_fields, materialize_vertex
- sqlite_store.py: 8 miss — _detect_fact_build __func__ path, _mapping_proxy_default TypeError
- executor.py: 3 miss — sync_fact tick (L234), fact tick (L267)
- builder/cadence/loop/program: 6 miss — mostly dead code or unreachable

## Test SDK
Created `libs/engine/tests/vertex_test_sdk.py` — fluent builder for test vertices.
Supports count_loop, sum_loop, latest_loop, with_store, routes, parse_pipelines.

## Compression opportunities
- test_vertex.py (1037 LOC) has heavy repetition in boundary tests — many create
  Loop() with similar parameters. Could extract shared fixtures.
- test_compiler.py (1829 LOC) has repeated KDL parsing patterns — builder helpers.
- test_vertex_reader.py (944 LOC) repeats _create_vertex_file + _seed_facts pattern.

## Strategy
- vertex_reader: vertex_fold and _specs_match are high-value, testable with tmp files
- vertex.py: evaluate_boundaries needs careful state setup but SDK makes it feasible
- Compression pass: look for LOC reduction in test_vertex.py boundary tests
