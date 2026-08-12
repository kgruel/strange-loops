# Cross-family review brief — cli-honesty-wave, round 1

You are reviewing the full branch diff of the `cli-honesty-wave` branch in the
strange-loops monorepo. Adversarial posture: your job is to find what the
implementers and their gates missed. Findings cluster at cross-slice seams and
in fix commits — look there first.

## 1. Anchor

- Repo: /Users/kaygee/Code/loops
- Branch: `cli-honesty-wave`
- Diff spec: `git diff 17783fd...HEAD` — 19 commits (4 slices + R2 fix +
  S4 integration round, merged --no-ff per slice)
- Slice reports (committed): `docs/scratch/cli-honesty-wave/s*-impl-report.md`,
  `r2-fix-report.md`
- Gate reports (uncommitted, main checkout): `docs/scratch/cli-honesty-wave/s*-gate-report.md`
  — gates: S1 PASS 8/8, S2 PASS 8/8, S3 PASS 6/6, S4 gated post-merge (see report)

## 2. Design contract (ratified fact `design/implementation/cli-honesty-wave` — the code must honor this verbatim)

> S1 read --status filter — payload-field equality on the fold row, --kind/--key
> composable; honest about kinds lacking a status field; makes the r2 gate
> invocation '--kind finding --status open' real. AMENDED (arbiter ruling,
> receipted as finding:chw-s1-deviation-refuse-over-note): when NO fetched kind
> carries a status field the command REFUSES (exit 2, stderr) — note-only was
> rejected as script-misreadable; per-kind stderr notes apply only on mixed
> fetches; honest empty at exit 0 is reserved for status-bearing rows that
> simply don't match.
>
> S2 exit-discipline family — (a) ls unknown vertex: exit nonzero + error to
> STDERR + did-you-mean parity with read; (b) ls --kind bogus: same
> kind-validation as read (no plausible 0-entries render); (c) FTS staleness
> hint renders 'sl store reindex <vertex>' with the actual vertex name.
>
> S3 reconcile-staleness sensor — days-since-last-reconcile derived from the
> store at the READ PATH (sensor logic in-repo; plugin/hook change stays thin);
> explicit RECONCILE OVERDUE nudge past ~10d. Arbiter ruling: derivation =
> newest thread-kind fact with name prefix `reconcile-`; no match → honest
> "no reconcile on record", never a fabricated age.
>
> S4 cite vertex slot — verb-first 'sl cite' gains a vertex slot per intended
> grammar; a cite whose refs ALL drop is an error, not a WARN + empty attention
> signal.
>
> NON-NEGOTIABLE: every error path exits nonzero with the error on stderr; no
> new detection machinery where narrowing the claim suffices; agents emit facts
> only, never ticks/seals.
>
> S5 gate-fail Surface routing: DEFERRED — out of scope for this wave. Do not
> review for it; do flag if any wave code quietly reaches into Surface routing.

## 3. Unverified fixes

Fix commits with NO independent gate behind them — re-verify these
empirically; they are your highest-yield zone:

- `6c8d965` — R2 fix (bare `ls` empty-home error to stderr). Merged on the
  remediation agent's self-report; no independent gate re-ran it. Claimed:
  pre-flight refusal in `_run_ls_root` before painted's `run_cli`, condition
  mirrors fetch's re-raise condition, byte-identical message, exit 1, new
  pinning test. Reproduction: `LOOPS_HOME=<empty dir> loops ls --plain`.
- `7bda5ae` — S2 late fix (unknown-vertex error prints plain multi-line;
  painted flattens `\n`). Applied after S2's internal review; the S2 gate
  DID re-run the reproduction after this commit, but verify the painted
  interaction claim itself.
- `d36f119` — S4 integration round (TestCite hermeticity via
  monkeypatch.chdir + refusal-message counts). The S4 gate covers this;
  cross-check its two claims anyway: semantics unchanged (gate =
  `unresolved and not resolved`), and the five tests now cwd-independent.

Known-open findings (already receipted, do not re-report as new):
- `finding:chw-r2-sibling-store-error-to-stdout` — bare `loops store` has
  the same stdout defect (store.py:300); queued for remediation.
Known cross-slice seam: `fold.py` touched by both S1 (status re-injection)
and S2 (staleness hint) — merged clean; verify the two changes compose.

## 4. What to verify empirically

- Exit codes and stderr routing: run the actual failing invocations
  (`uv run --package loops loops ls projcets`; `loops ls tasked --kind bogus`;
  `loops read <v> --status open` on a status-less kind). NOTE: use the `loops`
  entry point — `uv run --package loops sl` resolves to the globally installed
  sl and reviews stale code.
- Composability matrix for --status × --kind × --key, including empty-result
  vs no-status-field disambiguation.
- The reconcile sensor against synthetic stores (fresh / >10d / absent /
  decoy-prefix threads).
- Regression: valid invocations still exit 0; existing goldens/tests untouched
  by behavior drift.

## 5. Verdict format

Per finding: `[S<slice>-F<n>] severity — claim — evidence (command + output)`.
Then a verdict table for the enumerated unverified fixes: PASS/FAIL each.
Finally an overall call: CONVERGED or NOT CONVERGED, one paragraph of
rationale.
