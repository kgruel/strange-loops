# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% (done — remaining 8 lines are coverage quirks)
- **engine**: 92.5% (132 miss — mostly combine/discover in vertex_reader)
- **store**: 99.6% (1 miss — effectively done)
- **lang**: 98.4% (done — remaining 6 lines are dead/unreachable code)

## Next targets
- **loops app**: ~60% coverage, ~1,878 miss — biggest opportunity for absolute gains
  - Will need to check what tests exist and where gaps are
  - May have CLI integration tests that are expensive (subprocess/io)
  - Could target pure-function modules first for cheap wins

## Potential step-down opportunities
- Engine test suite at ~5s — could compress fixtures, share SDK helpers
- Lang tests very efficient already (0.68s, 1.88 efficiency) — probably not worth compressing

## Structural notes
- Flaky engine test: `test_mixed_boundary_with_conditions_met` — timing-dependent, passes in isolation but occasionally fails in full suite. Not our bug.
- `_node_map` in loader.py is dead code (defined L78-83, never called) — could be deleted
