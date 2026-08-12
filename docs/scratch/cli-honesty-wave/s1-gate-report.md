# S1 gate report — `read --status` (cli-honesty-wave)

Independent gate. Every result below was re-derived from scratch against the
worktree code; nothing is inherited from the implementer's report.

- Worktree: `/Users/kaygee/Code/loops/.claude/worktrees/agent-a9ae889ad9ced450c`
- Commits under gate: `7b2cb76` (impl + tests), `0f114d5` (impl report)
- Exercise form: `uv run --project <worktree> --package loops loops …`
  (`--project` points uv at the worktree **without** changing cwd, so canonical-store
  reads resolve `/Users/kaygee/Code/loops/.loops` while still running worktree code —
  `--directory` would have resolved an empty `.loops` inside the worktree and produced
  a false PASS via the exact plausible-empty this slice exists to kill)
- Throwaway store: `<scratchpad>/gate/tv.vertex` + `tv.db` — kinds `thread`/`task`
  (status-bearing) and `decision` (statusless), seeded with
  open/parked/resolved threads, one open task, two statusless decisions.

**Overall: GATE PASS.**

---

## 1. Diff scope — PASS

```
git -C <worktree> diff cli-honesty-wave...HEAD --stat
 apps/loops/src/loops/cli/dispatch.py            |  85 +++++++++-
 apps/loops/src/loops/cli/operation.py           |   7 +
 apps/loops/src/loops/cli/read_args.py           |  13 ++
 apps/loops/src/loops/cli/views/fold.py          |  50 ++++++
 apps/loops/src/loops/cli/views/read.py          |  22 +++
 apps/loops/tests/test_read_status.py            | 204 ++++++++++++++++++++++++
 docs/scratch/cli-honesty-wave/s1-impl-report.md | 117 ++++++++++++++
 7 files changed, 496 insertions(+), 2 deletions(-)
```

Five source files, all on the read path; one new test file; one scratch doc.
No collateral edits, no unrelated files, nothing outside `apps/loops`.

## 2. Fresh tests — PASS

- `uv run --package loops pytest apps/loops/tests/test_read_status.py -q` → **13 passed** (0.71s)
- `uv run --package loops pytest apps/loops/tests -q` → **2455 passed, 1 xfailed** (10.52s)
- Collateral control: same suite with `--ignore=apps/loops/tests/test_read_status.py`
  → **2442 passed, 1 xfailed**. 2442 + 13 = 2455 exactly, so the whole delta is the
  new file and no pre-existing test changed state.

## 3. The r2 gate invocation, live on the canonical store — PASS

Unfiltered population first (proving store resolution, not an empty read):

```
loops read project --kind finding --plain        → exit 0, FINDING (5)
  smoke-test-finding                          dismissed
  chw-s1-deviation-refuse-over-note           dismissed
  chw-s3-deviation-sl-entrypoint-fallthrough  open
  chw-s3-status-not-consulted                 deferred
  chw-s3-floor-rounding                       dismissed
```

Filtered:

```
loops read project --kind finding --status open --plain
  → exit 0, FINDING (1): chw-s3-deviation-sl-entrypoint-fallthrough   (stderr empty)

loops read project --kind finding --status dismissed,deferred --plain
  → exit 0, FINDING (4): the other four                                (stderr empty)

loops read project --kind finding --status zzz --plain
  → exit 0, "No data yet."                                             (stderr empty)
```

1 + 4 = 5, an exact partition of the unfiltered population with no overlap and no
loss. The open finding is returned and every dispositioned one is excluded. The
r2 gate invocation is real.

Also live on the canonical store: `--kind thread --status open` → THREAD (30);
`--kind thread --status resolved` → THREAD (162), i.e. the `status` where-field
defeats the lifecycle hide as the impl claims (269 threads unfiltered).

## 4. Composability, throwaway store — PASS

| Invocation | Exit | Result |
|---|---|---|
| `--kind thread --status open` | 0 | THREAD (1) alpha/one |
| `--kind thread --key alpha/ --status open,parked,resolved` | 0 | THREAD (2) alpha/one, alpha/two — `beta/three` excluded by `--key`, so the key predicate demonstrably still applies under `--status` |
| `--kind thread --status open,parked` | 0 | THREAD (2) alpha/one (open), alpha/two (parked) — comma-OR |
| `--kind thread --status nosuch` | 0 | "No data yet.", stderr empty — honest silent empty on a status-bearing kind |

## 5. Honesty matrix — PASS (see §5a note on the known deviation)

**(a) all-statusless fetch** — `--kind decision --status open` (throwaway store,
where `decision` rows provably carry no `status`; the canonical store's `decision`
rows could not be used as a control because some carry status):

```
exit 2 · stdout EMPTY · stderr:
read --status: kind 'decision' has no status field — no folded row carries one,
so --status open cannot match anything. Drop --status, or target a status-bearing kind.
```

Same under `--key design/ --status open` and under `--json` (stdout still empty —
no partial JSON document leaks before the refusal).

This **matches the reported deviation exactly** (refuse, exit 2, stderr; not
note-only + exit 0). Recorded as ground truth for the arbiter; ruling on whether
the strengthening is accepted is not this gate's call. Note: the store already
carries `finding:chw-s1-deviation-refuse-over-note` with status `dismissed` and
an arbiter disposition of ACCEPTED.

**(b) mixed fetch** — unscoped `read tv --status open`:

```
exit 0 · stdout: THREAD (1) alpha/one, TASK (1) t1
stderr: note: kind 'decision' has no status field — --status cannot match it
```

Filtered output rendered, per-kind note on stderr, exit 0. Same shape under
`--json` (valid single JSON document on stdout, note on stderr) and under
bare `--facts --status open` (fold route, honored, note emitted).

**(c) statusless kind alone, unfiltered** — `--kind decision --plain` → exit 0,
DECISION (2), stderr empty. Unchanged behavior; the honesty layer is inert
without `--status`.

## 6. Refusal surfaces — PASS

Every row: nonzero exit, error on stderr, **stdout empty** (checked explicitly —
the contract's non-negotiable is not satisfied by exit code alone).

| Invocation | Exit | stdout | stderr |
|---|---|---|---|
| `--ticks --status open` | 2 | empty | "…the status filter applies to folded state — `--ticks` reads tick windows, not folded rows." |
| `--facts --since 7d --status open` | 2 | empty | "…`--facts` with a temporal window/anchor routes to the event-history view, which doesn't apply it yet." |
| `--why thread/alpha/one --status open` | 2 | empty | "…--why owns its own fetch and does not apply the status filter…" |
| `read tv thread/alpha/one --why --status open` (positional form) | 2 | empty | same |
| `--diff 7d --status open` | 2 | empty | "…--diff owns its own fetch and does not apply the status filter…" |
| `--live --status open` **under a real TTY (pty)** | 2 | empty | "read --status: live mode renders the raw fold and does not apply the status filter — drop --status, or drop --live." |
| `-i --lens autoresearch --status open` **under a real TTY (pty)** | 2 | empty | "read --status: interactive mode renders the raw fold and does not apply the status filter — drop --status, or drop -i." |
| `--review --status open` | 2 | empty | "read --review: --status is not honored — the review projection is a full canonical snapshot…" (existing `_REVIEW_COMPOSE` whitelist; no S1 code) |
| `--status ""` / `--status ,` | 2 | empty | "read: empty --status value — name at least one status…" |
| `--status open status=open` | 2 | empty | "read: --status and a status= predicate are the same filter — give one, not both." |

Two clarifications the gate had to establish itself, both benign:

- On a **pipe**, `--live --status open` exits **0** and applies the filter. That is
  not a missed refusal: `_resolve_mode` downgrades `--live` to static on a non-TTY
  (pre-existing, `friction:live-mode-hangs-silently-on-pipe`), so the static path
  runs and the filter really is honored. The refusal is TTY-only by construction,
  and the pty run above confirms it fires there.
- Plain `-i --status open` exits 0 and applies the filter because `-i` resolves to
  INTERACTIVE only with `--lens autoresearch`. With the lens present under a pty,
  the refusal fires. No path accepts `--status` and silently drops it.

## 7. Regression, canonical store — PASS

| Invocation | Exit | Output |
|---|---|---|
| `loops read project --plain` | 0 | 1464 lines, stderr empty |
| `loops read project --kind thread --plain` | 0 | THREAD (269), 273 lines, stderr empty |
| `loops read project --kind thread --facts --plain` | 0 | 933 lines, stderr empty |
| `loops read project --kind decision --plain` | 0 | DECISION (581), 585 lines, stderr empty — a statusless-adjacent kind reads exactly as before when `--status` is absent |

Full-suite arithmetic (§2) confirms no collateral at the test level.

## 8. Emit receipts — PASS

- `task:chw-s1-read-status` — status `completed`, message describes the sugar-over-
  predicate design, the dispatch honesty layer, the honor-or-refuse routes, 13 tests
  and the 2455 suite.
- `finding:chw-s1-deviation-refuse-over-note` — present, `dismissed`, carrying the
  arbiter's ACCEPTED disposition for the refuse-over-note deviation.
- Driving `friction:read-status-filter-missing` is present and still `status=open`.
  Not a gate failure (the fix is unmerged), but it is the outstanding close-out:
  it should flip to `resolved` when the wave lands, or the friction backlog will
  keep surfacing a fix that already shipped.

---

## Verdict

| # | Check | Verdict |
|---|---|---|
| 1 | Diff scope | PASS |
| 2 | Fresh tests (13) + full suite (2455/+1 xfail), no collateral | PASS |
| 3 | r2 gate invocation live on canonical store | PASS |
| 4 | Composability: `--kind`, `--key`, comma-OR, honest empty | PASS |
| 5 | Honesty matrix (a refuse / b note / c unchanged) | PASS — (a) matches the reported deviation |
| 6 | Refusal surfaces: all nonzero, stderr, stdout empty | PASS |
| 7 | Regression on unfiltered reads | PASS |
| 8 | Emit receipts | PASS |

**GATE PASS.** The only contract divergence is the already-reported, already-
dispositioned refuse-over-note strengthening; observed behavior matches the
report bit-for-bit. Non-gating follow-up: flip
`friction:read-status-filter-missing` to `resolved` when the wave merges.
