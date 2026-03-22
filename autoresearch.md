# Autoresearch: Test Coverage Methodology

## Metric
**Primary**: `efficiency` (lower is better) = `test_LOC × test_time_s / covered_lines`

Rewards concise, fast tests that cover more source lines. Encourages shared fixtures,
integration tests, and clean test structure over bloated one-offs.

**Secondary** (for monitoring):
- `covered_lines` — absolute count of covered source lines (drives keep/discard rule)
- `coverage_pct` — percentage of target lines covered
- `miss` — number of uncovered source lines
- `test_loc` — lines of test code
- `test_time_s` — seconds to run tests

## Keep/Discard: Stairstep Rule

The decision checks **Δcovered first**, then efficiency:

```
if covered_lines > previous_covered:
    keep    # coverage gained — always accept
elif efficiency improved:
    keep    # tests got tighter without losing coverage
else:
    discard # nothing improved
```

No zones, no thresholds, no composite formulas.

### Why this works

Coverage gains and efficiency gains are different activities with a natural rhythm:

1. **Step up** — Add tests covering new lines. Efficiency gets worse (more LOC for
   hard-to-reach edges). Keep anyway: coverage ratcheted up.
2. **Step down** — Compress, extract fixtures, share helpers, merge tests. Coverage stays
   the same. Efficiency improves.
3. **Repeat** — Coverage never goes back. Efficiency oscillates but trends down.

The efficiency metric still serves its purpose: it pushes toward shared fixtures,
integration-style tests, and clean structure. But it can never veto real coverage gains.

### Edge cases

- **Padding** (useless LOC, no new coverage): covered unchanged, efficiency worse → discard ✓
- **Expensive edge coverage** (20 LOC for 2 lines): covered increased → keep ✓
- **Pure compression** (same coverage, fewer LOC): covered unchanged, efficiency better → keep ✓
- **Delete tests**: covered decreased → never keep (implicit: always track previous best covered)

## Measurement

Coverage is measured from the **full test suite** to avoid writing redundant tests for
lines already covered by integration/CLI tests. All test files across the monorepo count
toward LOC and timing.

```
coverage: full suite across all packages with --cov for each source root
timing:   full suite run duration
LOC:      non-empty, non-comment lines in all test files
```

## Monorepo layout

This is a uv workspace with multiple packages:

```
libs/atoms/     → src/atoms/      tests at libs/atoms/tests/
libs/engine/    → src/engine/     tests at libs/engine/tests/
libs/lang/      → src/lang/       tests at libs/lang/tests/
libs/store/     → src/store/      tests at libs/store/tests/
libs/painted/   → (submodule, excluded from coverage target)
apps/loops/     → src/loops/      tests at apps/loops/tests/
apps/tasks/     → src/tasks/      tests at apps/tasks/tests/
apps/hlab/      → (no tests currently)
```

Coverage targets: atoms, engine, lang, store, loops, tasks.
Test files: everything under `libs/*/tests/` and `apps/*/tests/`.

## Applying to a focused target

To narrow scope to one package, edit `INCLUDE_PACKAGES` and `TEST_DIRS` in
`autoresearch.sh`. The methodology stays the same.
