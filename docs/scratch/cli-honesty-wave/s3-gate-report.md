# S3 gate report — reconcile-staleness sensor

Gate agent, 2026-08-12. Independent re-run of the empirical oracle against
worktree `/Users/kaygee/Code/loops/.claude/worktrees/agent-a6a0e25537e663d36`
(branch `worktree-agent-a6a0e25537e663d36`, commits `5adfab7` + `19adf97`).
The implementer's report was not used as evidence.

**Verdict: GATE PASS** (6/6 checks pass; two non-blocking observations at the end.)

| # | Check | Verdict |
|---|-------|---------|
| 1 | Diff scope | PASS |
| 2 | Test runs | PASS |
| 3 | Live oracle (a–d) | PASS |
| 4 | Boundary probe ~10d | PASS (behavior recorded) |
| 5 | Read-only against the store | PASS |
| 6 | Emit-discipline receipts | PASS |

---

## 1. Diff scope — PASS

```
$ git -C <worktree> diff cli-honesty-wave...HEAD --stat
 apps/loops/src/loops/commands/orient.py         | 47 +++++++++++++
 apps/loops/tests/test_orient.py                 | 58 ++++++++++++++++
 docs/scratch/cli-honesty-wave/s3-impl-report.md | 89 +++++++++++++++++++++++++
 3 files changed, 194 insertions(+)
```

Only the orient command, its tests, and the scratch report. No engine code, no
hooks, no lib touched, no deletions (194 insertions, 0 removals). The sensor is
additive: a defaulted `reconcile_age_days: float | None = None` field on
`OrientSummary`, two private helpers (`_last_reconcile_ts`,
`_reconcile_age_days`), one renderer (`_render_reconcile_line`), and one extra
line in `render_orient`.

## 2. Fresh test run — PASS

```
$ cd <worktree> && uv run --package loops pytest apps/loops/tests/test_orient.py -v
6 passed in 0.23s
```

All six named: the two pre-existing orient tests plus the four new pinning tests
(`..._fresh_has_no_overdue_marker`, `..._stale_past_ten_days_renders_overdue`,
`..._no_record_renders_honest_line`, `..._matches_thread_kind_and_exact_prefix_only`).

```
$ cd <worktree> && uv run --package loops pytest apps/loops/tests -q
2446 passed, 1 xfailed in 9.30s
```

## 3. Live oracle — PASS

Throwaway JSONL-canonical stores built under `/tmp/s3gate` (vertex declaring
`thread`/`friction`/`decision`/`seal` kinds, `store "./data/<n>.jsonl"`), facts
emitted through the CLI and then backdated by rewriting the `ts` field in the
log with the derived `.db` deleted so the index rebuilds from the log. All runs
via `uv run --package loops loops orient …` from the worktree (not the stale
global `sl`).

**(a) recent reconcile — 3d, no marker**

```
$ loops orient /tmp/s3gate/caseA/caseA.vertex      # thread reconcile-2026-08-09 @ 3d
== loops orient ==
last seal: none
open: 1 threads · 0 frictions · 0 adopted-practices
last reconcile: 3d ago
```

The line lands directly under the `open:` counts, before `moved in last 3d`.
No overdue marker.

**(b) stale reconcile — 12d, marker present**

```
$ loops orient /tmp/s3gate/caseB/caseB.vertex      # thread reconcile-2026-07-31 @ 12d
last reconcile: 12d ago — RECONCILE OVERDUE
```

**(c) no reconcile on record**

```
$ loops orient /tmp/s3gate/caseC/caseC.vertex      # only thread some-thread
no reconcile on record
```

No fabricated age, no `last reconcile:` prefix.

**(d) decoys must not count**

Store seeded with four decoys, all 1d old and all listed under `moved`, so they
are demonstrably present and readable:

- `thread name=reconciliation-x` (right kind, prefix without the hyphen boundary)
- `thread name=pre-reconcile-x` (right kind, `reconcile-` not anchored at start)
- `friction name=reconcile-2026-08-11` (right prefix, wrong kind)
- `decision topic=reconcile-topic` (right prefix, wrong kind and wrong fold key)

```
$ loops orient /tmp/s3gate/caseD/caseD.vertex
open: 2 threads · 1 frictions · 0 adopted-practices
no reconcile on record
moved in last 3d:
  16:01 [thread] reconciliation-x: decoy
  16:01 [thread] pre-reconcile-x: decoy
  16:01 [friction] reconcile-2026-08-11: decoy
  16:01 [decision] reconcile-topic: decoy
```

None of the four counted. Matches the arbiter ruling exactly: exact kind
`thread`, anchored `reconcile-` prefix on the `name` fold key.

**Extra probes (not required, run anyway)**

- *Newest wins*: a store with `reconcile-old` @40d, `reconcile-mid` @20d,
  `reconcile-new` @5d renders `last reconcile: 5d ago` — the derivation is
  newest-by-`ts`, not first-found or fold order.
- *Combine vertex*: a `combine {}` vertex over caseA (3d) and caseB (12d)
  renders `last reconcile: 3d ago` — aggregates across children and takes the
  newest, consistent with how orient already handles combined seal history.
- *Real store, cost*: `loops orient .loops/project.vertex` renders
  `last reconcile: 0d ago` in 0.178s total wall clock on the 111 MB
  JSONL-canonical project store. No perceptible read-path cost.

## 4. Boundary probe ~10d — PASS (behavior recorded, threshold not judged)

Eight stores, one reconcile thread each, backdated to the ages below and read
immediately (so true age is the nominal age plus a few seconds of emit latency):

| nominal age | rendered line |
|---|---|
| 9.5d | `last reconcile: 9d ago` |
| 9.99d | `last reconcile: 9d ago` |
| 10.0d | `last reconcile: 10d ago — RECONCILE OVERDUE` |
| 10.001d | `last reconcile: 10d ago — RECONCILE OVERDUE` |
| 10.4d | `last reconcile: 10d ago — RECONCILE OVERDUE` |
| 10.6d | `last reconcile: 10d ago — RECONCILE OVERDUE` |
| 10.99d | `last reconcile: 10d ago — RECONCILE OVERDUE` |
| 11.0d | `last reconcile: 11d ago — RECONCILE OVERDUE` |

The marker fires on strict `> 10.0` days of true float age (`_RECONCILE_OVERDUE_DAYS
= 10.0`); the 10.0d row triggers because the few seconds between emit and read
push the true age just past the threshold. The displayed integer is a floor
(`int(age_days)`), so the number understates the true age by up to a day.

Rendered text is self-consistent: the only age that could display `10d ago`
*without* the marker is an exactly-10.000000d age, which is unreachable in
practice. There is no display value that appears on both sides of the boundary
in any real run. Threshold choice itself is out of gate scope.

## 5. Read-only — PASS

Two successive `loops orient` runs against an already-materialized index leave
the canonical log byte-identical:

```
$ shasum -a 256 /tmp/s3gate/caseA/data/caseA.jsonl
before: 368284773793daa93b5fd3842390159c08d7d4739bebc85e7a99c5c78482d0c8
after1: 368284773793daa93b5fd3842390159c08d7d4739bebc85e7a99c5c78482d0c8
after2: 368284773793daa93b5fd3842390159c08d7d4739bebc85e7a99c5c78482d0c8
```

The run that actually *writes* something is the one that materializes the
derived `.db` from the log, so it was bracketed separately — deleting the index
first, so this run takes the rebuild path:

```
$ rm /tmp/s3gate/caseA/data/caseA.db
before-rebuild: 368284773793daa93b5fd3842390159c08d7d4739bebc85e7a99c5c78482d0c8  size=439
after-rebuild:  368284773793daa93b5fd3842390159c08d7d4739bebc85e7a99c5c78482d0c8  size=439
```

Byte-identical across the rebuild too — no consumed-offset marker or any other
write lands in the canonical log. The index materialization is expected and
gitignored; its rebuild message goes to stderr, and all oracle runs above were
captured with stderr separated so the sensor line is unambiguous.

## 6. Emit-discipline receipts — PASS

```
$ cd /Users/kaygee/Code/loops && sl read project --facts --kind task | grep chw-s3
chw-s3-reconcile-sensor  mid  2  0  2026-08-12  completed · S3 closed: reconcile-staleness
sensor in orient — thread reconcile-* prefix derivation, one summary line (Nd ago /
RECONCILE OVERDUE past 10d / no reconcile on record), 4 pinning tests, full loops suite
2446 passed, live store shows 0d ago
```

Task fact present in the canonical store with two emissions (open → completed).

---

## Non-blocking observations

Neither changes the verdict; both are contract-conformant as ruled.

1. **Status is not consulted.** Any thread named `reconcile-*` counts regardless
   of `status=`, so a *planned* reconcile emitted as `status=open` would read as
   a completed one. The arbiter ruling specified name-prefix derivation only, so
   this is the specified behavior — but if reconcile threads are ever opened
   before the session runs, the sensor would read optimistically. Worth a line in
   the practice docs, or a later `status=resolved` narrowing.
2. **Floor rounding understates.** `int(age_days)` floors, so 9.99d renders as
   `9d ago`. Honest in the sense of never overstating staleness, and it never
   produces a display value that straddles the marker, but the number is up to a
   day low. Deliberate-looking; noting it so it isn't mistaken for a rounding bug
   later.
