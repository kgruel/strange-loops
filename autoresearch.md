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

---

## Recognizing the Ceiling

Some miss lines cannot be covered without changing the source itself. Recognizing this
early prevents grinding 50+ experiments against a wall with negligible return.

### Dead code

If remaining miss lines are defensive checks, impossible branches, or structurally
unreachable paths (the type system or data model makes them impossible to trigger):

1. **Confirm once** — read the source, understand why the path can't fire.
2. **Log it** — add to `autoresearch.ideas.md` under a `## Confirmed dead code` heading
   with the file, line numbers, and a one-line reason.
3. **Stop pursuing it** — do not write tests that mock internals just to make a line
   execute. That produces brittle tests with no real signal.

If the dead code is genuinely unreachable (not just hard to reach), the right fix is a
source cleanup — deleting the branch — not a test. Log it as a source task and move on.

### Source-level blockers

If the next meaningful gain requires a structural source change — adding a testability
hook, splitting a function, refactoring across multiple modules — log it in
`autoresearch.ideas.md` with:

- what change is needed
- which files are affected
- roughly how many lines it would unlock

Then move on to the next target. Source changes are legitimate and sometimes the right
call, but they require a deliberate decision, not another iteration of the same loop.

### When to stop the loop entirely

Stop and write a final summary when **all three** conditions hold:

1. The primary metric has not improved in the last ~15 experiments.
2. All remaining gaps are either confirmed dead code or source-level blockers already
   logged in `autoresearch.ideas.md`.
3. No new experiment idea would move the metric without first making a source change.

At that point, continuing is waste. Write a clear stopping summary — what was achieved,
what's left and why, what source changes would unlock the next tier — and halt. The
`autoresearch.ideas.md` file becomes the handoff to whoever addresses the blockers.
