# Autoresearch Ideas: engine Coverage Efficiency

## Current state: 91.6% line, 85.0% branch — 152 miss
## Progress: 83.4% → 91.6% (+189 lines covered)

## Remaining by file

### vertex_reader.py (108 miss — 71% of remaining)
- vertex_fold combine/overlay paths (23 miss) — needs combine vertex + store
- _collect_topology_info (15 miss) — multi-vertex topology info
- vertex_fact_by_id combine path (15 miss) — combined fact lookup
- _specs_match: DONE ✓
- _collect_source_specs (8 miss) — merge source specs from children
- _combined_read (8 miss) — combine read path
- _combined_search (6 miss) — combine search path
- _resolve_discover_stores (5 miss) — glob resolution for discover
- _raw_to_fold_state (5 miss) — edges in fold normalization
- Various small: _combined_summary(4), _merge_from(3), _loops_home(2), etc.
- **All combine/discover paths need multi-vertex file + store setups**

### compiler.py (15 miss)
- collect_search_fields template source (14 miss, L824-837) — needs template + params
- compile_sources relative path (L450) — needs .loop file

### vertex.py (14 miss)
- L434: receive child route miss
- L648: parse pipeline None in replay
- L688-692: ticks_since for period start (5 lines)
- L728: period_start > since_ts
- L765-770: mixed boundary conditions in evaluate_boundaries

### sqlite_store.py (8 miss)
- L44: _mapping_proxy_default TypeError
- L121-127: _detect_fact_build __func__ edge case

### Small files (7 miss)
- builder.py (2), cadence.py (2), executor.py (2), loop.py (1)

## Active approaches
- inject_fact helper — reduces boilerplate for store-based tests
- VertexTestBuilder SDK — fluent builder for Vertex+Store+Loop combos

## Diminishing returns
Most remaining lines need multi-vertex file setups (combine/discover in vertex_reader)
or template source configurations (compiler). ROI is ~10+ LOC per covered line.

Consider moving to the next package (lang, store, or loops) for fresh gains.
