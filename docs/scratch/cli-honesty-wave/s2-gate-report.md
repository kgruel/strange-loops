# S2 Gate Report — cli-honesty-wave exit-discipline family

**Gate:** independent (implementer's report not consulted for verdicts; oracle re-run from scratch)
**Worktree:** `/Users/kaygee/Code/loops/.claude/worktrees/agent-adae74acc7918f0c4`
**Branch:** `worktree-agent-adae74acc7918f0c4` @ `7bda5ae`
**Base (true parent, = `main`):** `17783fd`
**Date:** 2026-08-12

**VERDICT: GATE PASS** — all three contract items verified empirically with
before/after reproductions. Three residuals recorded below; none blocks S2.

All CLI exercise via `uv run --package loops loops …`. The "BEFORE" column is the
same command run from `/Users/kaygee/Code/loops` (main = `17783fd` = the branch's
true parent), so before/after differ only in the S2 diff.

---

## Check 1 — Diff scope: **PASS**

```
$ git diff cli-honesty-wave...HEAD --stat     # merge-base = 17783fd; identical to 17783fd..HEAD
 apps/loops/src/loops/commands/ls.py             |  86 ++++++--
 apps/loops/src/loops/commands/resolve.py        |  21 +++
 apps/loops/src/loops/lenses/fold.py             |   9 +-
 apps/loops/tests/test_ls_exit_discipline.py     | 159 ++++++++++++++
 apps/loops/tests/test_ls_flag_grammar.py        |  15 +--
 docs/scratch/cli-honesty-wave/s2-impl-report.md | 121 ++++++++++++
 6 files changed, 391 insertions(+), 20 deletions(-)
```

Command / lens / test / scratch only. Nothing outside scope.

- `ls.py` — the exit-discipline change (eager fetch, `_exit_on_fetch_error`, kind validation).
- `resolve.py` — **purely additive**: one new function `_unknown_vertex_message`
  inserted above `_validate_kind_or_exit`. No existing read-path behavior modified.
- `fold.py` — contract item (c) only: the staleness-hint string plus its comment.

## Check 2 — Fresh test runs: **PASS**

```
$ uv run --package loops pytest apps/loops/tests/test_ls_exit_discipline.py \
      apps/loops/tests/test_ls_flag_grammar.py -q
66 passed in 0.39s

$ uv run --package loops pytest apps/loops/tests -q
2450 passed, 1 xfailed in 9.34s
```

## Check 3 — Friction (a), unknown vertex: **PASS**

BEFORE (`main`), the friction reproduces exactly as filed — exit 0, error on STDOUT:

```
$ loops ls projcets
EXIT=0
[stdout] Error: vertex not found: /Users/kaygee/.config/loops/projcets/projcets.vertex
[stderr] (empty)
```

AFTER — nonzero exit, empty stdout, error + did-you-mean on stderr:

```
$ loops ls projcets   →  EXIT=1
[stdout] (empty)
[stderr] vertex not found: projcets
         Did you mean: projects, project?
         Known vertices: cli-completion, comms, comms/discord, comms/native,
                         identity, meta, project, projects, session, stories, tasked, tasks
```

Second and third misspellings, same shape:

```
$ loops ls identiy  →  EXIT=1, stdout empty, stderr "Did you mean: identity?"
$ loops ls taskss   →  EXIT=1, stdout empty, stderr "Did you mean: tasks, tasked?"
```

The three-line shape (miss / close matches / known set) is preserved multi-line —
commit `7bda5ae`'s plain-`print` fix is real, painted's `Block.text` newline
flattening does not collapse it.

**Judgment call on "did-you-mean parity with read".** Read's *vertex* path has no
did-you-mean at all: `loops read identiy` → exit 1, stderr `No vertex resolved —
run \`loops init\` first.` (`cli/views/fold.py:655`). The strict
message-identity reading of the contract is therefore unsatisfiable — read has no
vertex did-you-mean to be at parity with. The satisfiable reading, and the one the
implementer took, is parity with read's did-you-mean *treatment* — the kind
validator's three-line shape at `resolve.py:1580`, reused verbatim in structure.
Ruled **PASS**. See Residual 1 for the divergence this leaves behind.

## Check 4 — Friction (b), bogus `--kind`: **PASS**

BEFORE — the plausible 0-entries render, exit 0:

```
$ loops ls identity --kind bogus-kind
EXIT=0
[stdout] bogus-kind (0)
           0.0% of identity · 0 observers
           (no entries)
```

AFTER — byte-for-byte identical stderr to read, same exit code, on two vertices:

```
$ loops ls identity --kind bogus-kind   → EXIT=2
$ loops read identity --kind bogus-kind → EXIT=2
$ diff <ls stderr> <read stderr>        → IDENTICAL

  Vertex 'identity' does not declare kind 'bogus-kind'.
  Declared kinds: cite, decision, hypothesis, intention, observation, principle, seal, self

$ loops ls tasks --kind bogus-kind      → EXIT=2, stderr IDENTICAL to read's
```

Both stdouts empty. This is the same validator, not a lookalike message.

## Check 5 — Friction (c), FTS staleness hint: **PASS (constructed end-to-end, not test-only)**

The new unit test builds a `Surface` by hand, which does not prove the vertex name
flows from real data. So the hint was reproduced end-to-end against a real store:
a throwaway vertex `gatevx` under `LOOPS_HOME=/tmp/s2gate/home` declaring
`search "topic" "message"` on `decision`, two facts emitted, **never reindexed**
(→ `coverage.missing` → `Window.stale`).

```
BEFORE:  (1 index stale — run `sl store reindex`: decision)
AFTER:   (1 index stale — run `sl store reindex gatevx`: decision)
```

The friction's premise and the fix's efficacy both confirmed:

```
$ loops store reindex          → EXIT=1  "/tmp/s2gate/home/.vertex not found. Run 'loops init' first."
$ loops store reindex gatevx   → EXIT=0  "✓ gatevx: reindexed — 2/2 facts indexed across 1 kind(s)"
$ loops read gatevx --match auth --plain   → hint gone
```

The bare form recommended before genuinely sent the reader to a refusal; the named
form heals the condition and the hint disappears. The vertex name comes from real
`Surface.vertex` data, not a test fixture.

## Check 6 — Regression and other flipped error paths: **PASS**

Valid invocations, all exit 0 with output on stdout and empty stderr:

| Command | Exit | Result |
|---|---|---|
| `loops ls --plain` (real home) | 0 | root listing renders |
| `loops ls gatevx --plain` | 0 | 2 facts, 1 kind |
| `loops ls gatevx --kind decision --plain` | 0 | stat view, 2 topics |
| `loops ls gatevx --kind decision --key design/ --plain` | 0 | prefix-scoped, 2 entries |
| `loops ls gatevx --kind log --plain` | 0 | by-observer breakdown (collect-fold) |

Other flipped error path probed — `--key` on a collect-fold kind:

```
BEFORE: $ loops ls gatevx --kind log --key foo
        EXIT=0, stdout: "Error: kind 'log' is a collect-fold (no fold key) — --key doesn't apply…"
AFTER:  EXIT=1, stdout empty, stderr: same message
```

Aggregation-vertex refusal also flipped correctly (`loops ls project --kind
bogus-kind` → exit 1, stderr, stdout empty). Nothing that previously succeeded now
fails.

`--help` delta checked, since the diff moved the fetch ahead of `run_cli`:
`--help` is intercepted upstream of the fetch, so there is no delta —
`loops ls projcets --help` and `loops ls gatevx --help` both exit 0 and their
output is byte-identical between base and S2.

## Check 7 — Read unchanged: **PASS**

`fold.py` is the only read-path file in the diff, and its sole change is contract
item (c)'s hint string. Verified behaviorally:

```
$ loops read gatevx --plain    →  base vs S2 output byte-identical, exit 0 both
$ loops read gatevx --kind decision --plain  →  exit 0, renders normally
```

`resolve.py`'s change is a pure function insertion; no existing read code path
reads it except the new `ls` caller.

## Check 8 — Receipts: **PASS**

```
$ sl read project --facts --kind task | grep chw-s2
chw-s2-exit-discipline  mid  2  0  2026-08-12  completed · S2 closed: ls exit
discipline (unknown vertex exit 1 + did-you-mean, bogus --kind exit 2 via read's
validator, all ls error dicts stderr+nonzero) + vertex-named reindex hint.
2450 tests pass; report in docs/scratch/cli-honesty-wave/s2-impl-report.md
```

Open (20:54) and close (21:05) both present; the 2450 count matches this gate's
independent run exactly.

---

## Residuals (recorded, non-blocking)

**R1 — `ls` and `read` now give different unknown-vertex messages.** `ls` gained a
did-you-mean; `read` still says `No vertex resolved — run \`loops init\` first.`
for the same input. `ls`'s is strictly better, and read is intentionally untouched
by this diff (check 7), so this is a *widened* parity gap, not a regression.
Candidate follow-up friction for the wave: give read's vertex path the same
`_unknown_vertex_message` treatment — the function already exists and is reusable.

**R2 — bare `loops ls` with no config root prints its error to STDOUT.**

```
$ LOOPS_HOME=/tmp/empty loops ls --plain
EXIT=1, stdout: "/tmp/empty/.vertex not found. Run 'loops init' first.", stderr empty
```

Base code behaves identically, and the source (`resolve.py:1488` /
`vertices.py:299`) is untouched by this diff. Exit is nonzero (correct); the
stream is wrong. This is a genuine hit against the wave's NON-NEGOTIABLE clause,
inherited from a shared root-resolution path used by several commands — flagged
for arbiter disposition rather than failed against S2, since fixing it here would
be scope creep into a shared path outside the three named contract items.

**R3 — aggregation vertices refuse before kind validation.** `loops ls project
--kind bogus-kind` → exit 1, stderr `Error: project is an aggregation vertex — no
own store to stat`, where `read` gives exit 2 and the kind error. Nonzero + stderr
holds, so the non-negotiable is satisfied; the *structural* refusal simply fires
first. Recorded as an observed asymmetry, not a defect.

---

## Verdict

| # | Check | Verdict |
|---|---|---|
| 1 | Diff scope | PASS |
| 2 | Fresh test runs (66 / 2450+1 xfail) | PASS |
| 3 | Friction (a) unknown vertex | PASS |
| 4 | Friction (b) bogus `--kind`, byte-identical to read | PASS |
| 5 | Friction (c) staleness hint, end-to-end | PASS |
| 6 | Regression + other flipped paths + `--help` | PASS |
| 7 | Read unchanged | PASS |
| 8 | Receipts | PASS |

**GATE PASS.**
