# Slice 2 / WP3 impl report — admission extraction

Branch: `slice2/wp3-admission`, off `0d38c969` (verified `git merge-base HEAD
slice/arrival-backend-contract` = `0d38c969`).

Contract: `docs/scratch/arrival-break/slice2-wp3-brief.md`. Design sections bound:
`slice2-design-proposal.md` §C (all) and §D.3. SD-1 holds — the coordinate machinery
(`_stage_arrival_coordinates` / `_check_arrival_provider_agreement` / `_stamp_arrival_axis`)
is projection and was not touched.

---

## 0. Baseline, captured on clean `0d38c969` before any edit

Package-scoped runs, because a root `uv run pytest` misses each member's own dev group
(`hypothesis`) and a combined engine+store invocation collides on `tests.conftest`:

| Suite | Command | Baseline |
|---|---|---|
| engine | `uv run --package engine pytest libs/engine/tests -q -p no:randomly` | **1989 passed, 1 skipped** |
| store | `uv run --package store pytest libs/store/tests -q -p no:randomly` | **180 passed** |
| architecture | `uv run pytest tests/architecture -q -p no:randomly` | **99 passed** |

Import-cost baseline for the one hot-path module that imports `engine.admission` eagerly
(`libs/sdk/src/sdk/emit.py:12`), `python -X importtime -c "import sdk.emit"`, cumulative
µs over three runs: **133347 / 90690 / 82748**.

---

*(sections below filled as the work lands)*
