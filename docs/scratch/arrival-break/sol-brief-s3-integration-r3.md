# Sol review brief — arrival-break slice 3, integration round 3 (per-WP, LOW)

Round 3, verifying the fixes for your r2 blocking finding S3I-L-3 (fence probe
fails open) plus the pattern-audit follow-through it triggered.

## 1. Anchor

- Worktree: this directory (`~/Code/loops-s3wp1`), branch `slice3/arrival-witness`,
  NEW tip `32234eac`. Diff since your r2: `git diff 4b1a14a4...32234eac`.
- Suites: engine per-package, architecture SEPARATELY. Claimed at 0d9da45f:
  engine 2295 passed + 1 skipped + 0 failed, arch 99, ruff clean.
- ARBITER-APPLIED fix at the tip (prose-only, no independent gate — you are its
  only verification): `32234eac` adds the fence's cost sentence to §04b (one
  verified lookup per abandoned anchor on advancing opens; scales with ceremony
  history; never paid on the dominant unchanged open) — your r2 perf residual.
  Verify it against the implementation's actual cost shape and that it neither
  under- nor over-claims.

## 2. Unverified fixes, by commit

- `333021bc` + `f85a5648` — S3I-L-3: `FenceProbeUnanswered`, a SIBLING of
  `AbandonedHistoryFenced` (different claim, different remedy: "touches
  decreed-away ground → ceremony" vs "could not determine → retry"). An
  unanswered fence probe refuses, typed, before `_Earned`. Probe audit: exactly
  one probe in the fence; lift check is pure comparison, no I/O.
- `c1a578c8` + `0d9da45f` — the pattern audit's harvest, ruled fixed now
  (finding:s3wp3-binding-probes-fail-acceptance-side): FOUR sites in the
  transitional binding unit. Three read I/O/parse failure as "no alias found"
  (silent first contact): `aliased_lineage` OSError, `_identity_of` OSError,
  binding-line-loop ValueError. The FOURTH was found while testing and gated
  the others' reachability: `bound_lineage` let a raw OSError ESCAPE UNTYPED
  past every `except AttestationRefusal` (wrong by being untyped, not by
  direction), and it reads the bindings file BEFORE `aliased_lineage`. Pattern
  named: `ProbeUnanswered` parent; `BindingProbeUnanswered` dies with the unit
  at slice 5, parent + fence subclass survive. One WP1 test inverted (it pinned
  the malformed-line skip, and the skip was the defect).

## 3. Verify each — empirically where possible

1. **S3I-L-3 regression**: your repro — transient failure on the anchor lookup
   → open REFUSED (`FenceProbeUnanswered`), journal AND binding byte-identical.
   Re-run their test AND your own r2 construction. NOTE their demo lesson: the
   probe must fail SELECTIVELY at the anchor ordinal — failing every `head_at`
   makes `_descent` refuse first (`HeadRewrite`) and proves nothing about the
   fence. Verify their selective construction actually isolates the fence.
2. **Mutation demo**: catch-and-continue restored → 2 failed, the loop
   reproduced (probe raises → advanced → journaled → next clean open
   unchanged). Re-run.
3. **The four binding sites**: per-site regressions (probe raises → typed
   refusal, nothing journaled, no binding written) and FIVE per-site mutation
   demos each failing EXACTLY ONE test — their first pass had no failing test
   for two arms because `bound_lineage` refuses before `aliased_lineage` is
   reached through an open; each arm now has a direct-call test. Verify the
   demos still fail exactly one each (that is the depth-is-pinned-separately
   claim — if a demo fails zero or several, the claim is broken).
4. **Real-filesystem construction**: the tests use a permission wall and a
   locked directory (skip as root), and the alias is a HARD LINK (a symlink
   resolves to the same canonical form and never reaches the alias probe).
   Verify the constructions actually exercise the probe paths claimed — and
   that root-skip leaves each judgment covered by some other test on this
   platform.
5. **The inverted WP1 test**: its reasoning (absent file = no binding is fine;
   unreadable LINE = refusal) — verify the inversion is right and no other test
   still pins the old skip.
6. **Typed-escape sweep**: `bound_lineage`'s raw-OSError escape was invisible
   to an acceptance-side audit. Sweep the seam + attestation module for any
   OTHER path where a builtin exception escapes past the typed-refusal
   boundary (the `JournalUnreadable` pattern one file over is the model).
7. Counts: engine 2295+1s+0f (+9 over r2), arch 99 separate, ruff clean,
   `git diff --check` clean.

## 4. Try-to-defeat seeds

- **ProbeUnanswered as a new uniform-outcome surface**: two sibling refusal
  types now say "retry". Can a caller catch the parent and retry FOREVER on a
  permanent condition (deleted-then-recreated store dir, permanently
  unreadable bindings file) — is there anything that distinguishes
  transient-retry from permanent-operator-problem, and if not, is that honest
  (documented) or a hole?
- **The fence under probe-refusal pressure**: repeated FenceProbeUnanswered
  opens (flaky NFS) — does anything degrade, cache, or give up in a way that
  weakens the fence after N failures?
- **Order dependence**: `bound_lineage` reads the bindings file before
  `aliased_lineage`. Construct a state where the FIRST read succeeds and the
  SECOND fails (file replaced between reads within one open) — typed refusal
  or something worse?
- **The §04b cost sentence**: is "never on the dominant unchanged open" true
  under every path (including a fenced-then-retried open that lands unchanged)?

## 5. Verdict format

Per-item PASS/FAIL + evidence. New findings: `S3I-L-<n>` continuing, file:line,
severity, concrete failure scenario. Then one line: **CONVERGED** or
**NOT CONVERGED** (with the blocking list).
