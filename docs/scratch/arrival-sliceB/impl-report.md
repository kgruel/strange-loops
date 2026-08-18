# Cut B — PROJECTIONS: implementation report

Branch `slice/arrival-projections-s1`, worktree
`/Users/kaygee/Code/loops-wt/arrival-projections`, based on
`feat/arrival-libs` @ `39ea67f5`. Seven commits, one per seam.

Contract: `docs/scratch/arrival-sliceB/design-proposal.md`
(decision:design/arrival-sliceB-projections).

---

## Environment — read this before comparing counts

Two things about this worktree that a reader comparing against the main
checkout must know.

**1. `uv run --package X` re-syncs the venv to X's dependency closure.** The
first run of `uv run --package engine pytest libs/engine/tests` in a fresh
worktree produced **3 failed, 1644 passed, 1 skipped, 32 errors** — every
error a `ModuleNotFoundError: No module named 'sign'` out of
`libs/engine/tests/conftest.py::Custodian`. `sign` is not an engine
dependency; the arrival suites need it for real Ed25519. The main checkout's
venv happens to hold the whole workspace, which is why the same command
passes there.

Fix, applied once and NOT a code change: `uv sync --all-packages` in the
worktree, and every suite command below carries `--no-sync` so the next
`--package` run cannot undo it.

**2. One pre-existing engine failure, surfaced by a fresh hypothesis corpus.**
`test_properties_replay.py::TestFoldDeterminismProperties::
test_fold_state_deterministic_given_append_sequence` fails at the unmodified
base commit with `engine.declaration.UnadoptedLineage`. Hypothesis generated
a fact whose `kind` is `_decl.genesis`, emitted through `store.append`
rather than the absorb ceremony, so the store ends up with a genesis row and
no `own_lineage` marker. The main checkout's `.hypothesis` corpus has not
found this example; the worktree's fresh one did, and the saved example now
makes it deterministic here.

It reproduces with zero edits applied, it is unrelated to projections, and
it looks like a test-strategy gap (emitting a raw `_decl.genesis` fact is
out-of-contract usage) rather than a product defect — but I did not
investigate far enough to claim that, and I did not fix it. **Every engine
count below therefore reads `N passed, 1 failed`, and that 1 is this test.**
A second failure would be mine.

### Baselines at `39ea67f5` (after `uv sync --all-packages`)

| Suite | Result |
|---|---|
| `libs/engine/tests` | 1678 passed, 1 skipped, 1 failed (above) |
| `libs/store/tests` | 131 passed |
| `tests/architecture` | 98 passed |
| `libs/sdk/tests` | 313 passed |
| `apps/loops/tests` | 2525 passed, 1 xfailed |

Rule 17's known local-only failure (`finding:rule17-scans-untracked-docs`)
did **not** fire at baseline.

---

*(Per-seam sections follow.)*
