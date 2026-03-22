# Autoresearch Ideas: engine Coverage Efficiency

## Current state: 89.2% line, 81.6% branch — 205 miss

## Progress: 83.4% → 89.2% (+136 lines covered, efficiency 6.97 → 5.51)

## Remaining by file

### vertex_reader.py (~117 miss)
- vertex_fold combine/overlay paths (23 miss)
- _collect_topology_info (15 miss) — needs discover/combine .vertex files
- vertex_fact_by_id combine path (15 miss)
- _specs_match (10 miss) — spec comparison for merge validation
- _collect_source_specs (8 miss) — merge source specs
- _combined_read (8 miss) — combine read paths
- Various combine/discover functions (~38 miss total)
- These all need setup with multiple .vertex files + stores — moderate cost

### vertex.py (~57 miss)
- evaluate_boundaries (16 miss) — complex state machine
- _evaluate_vertex_only_boundaries (24 miss) — vertex-level boundary eval
- replay fast path edges (L617-633)
- These need careful state setup with stored ticks + facts

### compiler.py (~16 miss)
- collect_search_fields template source (14 miss) — needs template + from_file
- compile_sources simple path (L450)
- materialize_vertex parse_pipelines (L940)

### Other files (~15 miss)
- sqlite_store.py: 8 miss — _detect_fact_build __func__ path
- executor.py: 2 miss — sync_fact/fact tick appends
- builder/cadence/loop/program: 5 miss — mostly dead code/unreachable

## Test SDK
`libs/engine/tests/vertex_test_sdk.py` — fluent builder for runtime Vertex objects.

## Compression opportunities (step-down candidates)
- test_vertex.py boundary tests: heavy Loop() construction repetition
- test_compiler.py KDL parsing patterns  
- test_vertex_reader.py vertex file + seed patterns

## Strategy
- combine/discover paths in vertex_reader: test with real multi-vertex setups
- vertex evaluate_boundaries: use SDK with boundary configurations
- Or: shift to step-down (compression) to improve efficiency before pushing deeper
