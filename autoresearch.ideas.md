# Emit Path Optimization — Final State

## Results (51 experiments, 5 sessions)
- Baseline: 7.81ms → Best measured: 1.02ms (87% improvement)
- Typical: 1.1-1.3ms under normal load

## All optimizations (chronological)
1. Mutating replay — bypass deepcopy (7.81→1.47ms, -81%)
2. Direct Fact construction in since()
3. Skip dict copy in Fact.__post_init__
4. Raw replay via since_raw() tuples
5. Optimized tick lookup via last_tick_ts()
6. Skip sources for emit (skip_sources flag)
7. Fix flaky test (1μs float precision tolerance)
8. Stream replay via replay_into()
9. Pre-created JSONDecoder
10. Remove sqlite-ulid — Python uuid4 IDs
11. Skip WAL pragma for existing DBs
12. Skip synchronous pragma for existing DBs
13. Individual execute() vs executescript
14. Flatten single-fn dispatch
15. Skip schema for existing DBs (lazy load)
16. Mutating receive (bypass deepcopy)
17. Cache mut fold fns in Loop
18. Lazy synchronous pragma (after schema load)
19. Skip mkdir for existing DBs
20. raw_decode (2x faster than decode)
21. Lazy _direct_fact_build detection
22. Simplify materialize_vertex (collapse branches)

## Remaining cost (~1.1ms)
- SQLite connect: 0.05ms
- Schema load: 0.25ms (unavoidable first-query cost)
- 300× raw_decode + fold: 0.25ms
- Serialize + INSERT + COMMIT: 0.1ms
- Connection close: 0.25ms

## Architectural changes needed for further improvement
- Connection pooling (eliminate open+close)
- Import deferral (82ms outside benchmark scope)
