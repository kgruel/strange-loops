# S3 impl report — reconcile-staleness sensor in orient

Slice S3 of `design:implementation/cli-honesty-wave` (status=ratified).
Driving friction: `friction:reconcile-cadence-has-no-sensor`.
Branch: `worktree-agent-a6a0e25537e663d36` (worktree off `cli-honesty-wave`).

## What changed

`sl orient` now carries a one-line reconcile-cadence sensor between the
`open:` counts and the `moved in last Nd:` block:

- `last reconcile: 3d ago` — fresh, no marker
- `last reconcile: 12d ago — RECONCILE OVERDUE` — age strictly > 10 days
- `no reconcile on record` — no receipt exists; never a fabricated age

Derivation (per the arbiter ruling — not redesigned): the newest
**thread-kind** fact whose fold key (`name`) starts with the anchored
prefix `reconcile-` (hyphen included). A friction/decision named
`reconcile-*` does not count; threads named `reconciliation-notes` or
`pre-reconcile-plan` do not count.

Sensor logic is pure functions in-repo (`_last_reconcile_ts`,
`_reconcile_age_days`, `_render_reconcile_line`), following orient's
existing structure (pure derivation → `OrientSummary` field →
`render_orient` line) and the live-edge staleness sensor's
read-path-derivation design. It composes the existing
`engine.vertex_facts` read API — **no engine change**. The plugin/hook
side needs no change at all: the hook already renders orient's output.

## Files touched

- `apps/loops/src/loops/commands/orient.py` — sensor + summary field + render line
- `apps/loops/tests/test_orient.py` — 4 new tests
- `docs/scratch/cli-honesty-wave/s3-impl-report.md` — this report

## Error-path non-negotiable

Satisfied by the existing view wiring (`cli/views/orient.py`): unresolvable
vertex refs exit 1/2 with the error on `ctx.reporter.err` (stderr), and any
exception in the summary computation propagates to a nonzero exit. This
slice adds no new error paths — the sensor's only "absent data" case renders
the honest `no reconcile on record` line, which is a truthful success, not
an error.

## Test evidence

- `uv run --package loops pytest apps/loops/tests/test_orient.py -q` → 6 passed
  (2 pre-existing + 4 new: fresh, stale >10d, no-record, kind+prefix exactness)
- Full app suite `uv run --package loops pytest apps/loops/tests -q` →
  **2446 passed, 1 xfailed**
- No orient goldens exist (`grep -rl orient apps/loops/tests/golden/` empty),
  so no snapshot churn.

## Live exercise (read-only)

`uv run --package loops loops orient /Users/kaygee/Code/loops/.loops/project.vertex`:

```
== loops orient ==
last seal: session close: kyle/loops-claude
open: 30 threads · 47 frictions · 1 adopted-practices
last reconcile: 0d ago
```

Finds `thread:reconcile-2026-08-12` (today) → `0d ago`, no marker. Whole
command ~0.26 s wall against the 111 MB-log store — reads hit the derived
sqlite index, no latency concern.

**Tooling note, not a deviation**: the task's suggested exercise form
`uv run --package loops sl orient …` silently resolves `sl` to the
**globally installed** binary (`~/.local/bin/sl`) because the `sl` console
script is declared only in the root `strange-loops` package —
`apps/loops` declares only `loops`. First run therefore showed stale
output. Verified with `uv run --package loops sh -c 'command -v sl'` and
re-exercised via the `loops` entry point. This is the inverse of the
CLAUDE.md-anchored install-staleness footgun and may be worth a friction
emit from the arbiter's side; no code deviation resulted.

## Deviations from the contract

None. Threshold ~10d implemented as strictly `> 10.0` days on the float
age; the rendered day count truncates (`int(age_days)`), so an age of
10.4 d renders `10d ago — RECONCILE OVERDUE` — honest, marker governed by
the float, noted here so review isn't surprised.

## Commits

- `5adfab7` — feat(orient): reconcile-staleness sensor
- (this report committed on top; see `git log`)
