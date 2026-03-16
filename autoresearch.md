# Autoresearch: Test Coverage Efficiency

## Current policy

Primary metric is now:
- **cov_per_test_loc** = (covered lines + covered branches) / test lines
- higher is better

Secondary metrics tracked for guardrails:
- **ms_per_cov** = pytest milliseconds / (covered lines + covered branches)
- **test_loc** = total Python test lines under `libs/*/tests` and `apps/*/tests`
- **test_loc_per_cov** = test lines / covered items
- **total_cov** = covered lines + covered branches
- **branch_pct** = branch coverage percentage

## Why the pivot

The earlier loop correctly optimized speed + coverage, but it did not measure whether the suite was becoming simpler or more bloated. The LoC-aware phase improved discipline, but `ms_per_cov` still over-penalized some structurally better changes because runtime noise often dominated small coverage wins. We now optimize directly for structural efficiency: broad tests and reusable helpers should buy more coverage with less test-code growth.

## Current best known coverage before this pivot refresh
- branch coverage: **73.3%**
- total covered items: **9352**
- primary metric range on good runs: roughly **0.8–1.1 ms/cov**

## Decision policy
- Keep/discard is now based on **primary metric improvement in `cov_per_test_loc`**.
- Secondary metrics are monitored, not primary gates.
- Prefer changes that improve `cov_per_test_loc` while preserving or increasing `total_cov`.
- Treat large `test_loc` growth for tiny coverage wins as a warning sign.
- Treat `ms_per_cov` as a guardrail only; only reject a structural improvement if runtime degrades catastrophically or coverage meaningfully drops.
