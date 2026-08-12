# Cross-family review brief — cli-honesty-wave, round 2

Round 1 returned NOT CONVERGED with 4 findings. All 4, plus 2 arbiter-held
findings, were fixed in a remediation round. Your job in r2: verify the six
fixes empirically, hunt for evasions and collateral in the remediation diff,
and re-call convergence. History says rounds 2+ are dominated by holes in
round-1 fixes — the remediation commits are your primary target, the rest of
the branch is regression backdrop.

## 1. Anchor

- Repo: /Users/kaygee/Code/loops
- Branch: `cli-honesty-wave`
- Full-wave diff: `git diff 17783fd...HEAD`
- Remediation delta (primary target): commits `859702b`, `cf05ca3`,
  `649c81b`, `49e4e4c`, `5f1b0df`, report `b411deb`, merged at the branch tip
- Your r1 findings + reproductions: `docs/scratch/cli-honesty-wave/sol-r1-stdout.log`
- Remediation evidence: `docs/scratch/cli-honesty-wave/r1-remediation-report.md`

## 2. Design contract

Unchanged from r1 (see sol-brief-r1.md §2) plus these arbiter rulings now in
force:
- S1 statusless refusal: census computes on the post-`key_or` fetch set —
  comma-key and single-key spellings must answer identically.
- Custom-lens static reads REFUSE `--status` (exit 2, stderr) — inert-note
  overturned. Bareword `status=` predicate keeps the note.
- `ls` kind validation precedes key-applicability; `--kind bogus --key x`
  byte-identical to `--kind bogus`.
- Cite gate, one condition: stores only when the `ref` FIELD carries >=1
  address AND not all attempted ref-field resolutions failed. Message-field
  addresses never rescue; zero-address cites refuse; all-inert cites store
  as provenance-only.
- Bare `loops store` empty-home refusal: stderr, exit 1, byte-identical
  message (mirror of the ls R2 fix).

## 3. Disposition table (r1 findings — verify each fix, then verdict PASS/FAIL)

| Finding | Disposition | Commit |
|---|---|---|
| S1-F1 comma-key census bypass (HIGH) | fixed | 859702b |
| S1-F2 custom-lens --status inert (HIGH) | fixed | cf05ca3 |
| S2-F1 key-applicability before kind validation (MED) | fixed | 649c81b |
| S4-F1 non-ref-field resolution rescues cite (HIGH) | fixed | 49e4e4c |
| chw-r2-sibling: bare `loops store` stdout (held from S2 gate) | fixed | 5f1b0df |
| chw-s4-raw-emit-empty-cite: zero-address cite stores (held from S4 gate) | fixed | 49e4e4c |

None of these six fixes has an independent gate behind it — re-verify each
empirically with your own reproductions, including your original r1 ones
verbatim, plus evasion variants you construct (adjacent spellings, flag
orders, aggregation vertices, --json/--plain variants, dry-run).

Known-open, already receipted, do NOT re-report as new:
- `observation:test/chw-store-missing-name-stdout` — `loops store <missing>`
  errors to stdout (third family member, raised inside fetch under run_cli);
  queued for the next remediation batch.
- `friction:stored-receipt-omits-vertex` — emit-wide, out of wave scope.

## 4. Regression backdrop

Full suite currently 2500 passed / 1 xfailed from both a `.loops`-bearing
and a `.loops`-free cwd; `./dev check` 59 passed. Exercise CLI via
`uv run --package loops loops ...` only (the `sl` form runs the stale
global install). One pre-existing fixture was adapted (test_why_flag.py seed
cites gain a resolvable ref, forced by the zero-address ruling) — check the
adaptation preserved that test's subject.

## 5. Verdict format

Per r1 finding: PASS/FAIL with evidence. New findings as
`[R2-F<n>] severity — claim — evidence`. Then overall: CONVERGED or NOT
CONVERGED with rationale.
