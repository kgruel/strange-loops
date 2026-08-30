# Sol review brief — arrival-break slice 3, integration round 4 (per-WP, LOW — short verify)

Round 4, verifying the two fixes for your r3 blockers S3I-L-4 (untyped decode
escape) and S3I-L-5 (cost-sentence overclaim).

## 1. Anchor

- Worktree: this directory (`~/Code/loops-s3wp1`), branch `slice3/arrival-witness`,
  NEW tip `7edca4b2`. Diff since your r3: `git diff 32234eac...7edca4b2`.
- Claimed: engine 2299 passed + 1 skipped + 0 failed, arch 99 separately, ruff
  clean on changed files.

## 2. Unverified fixes

- `b2c35955` — ARBITER-APPLIED (prose, you are its only verification): §04b cost
  sentence now your suggested wording — one verified lookup per distinct,
  currently fenced anchor ordinal on an advancing open; exclusions named;
  ADVANCED-only claim retained. Verify it no longer over- or under-claims.
- `1cf379fe` + `7edca4b2` — S3I-L-4, WITH AN ARM CORRECTION beyond the routed
  scope: the impl split the refusal family BY REMEDY, moving two of last
  round's cases. `BindingsUnreadable` (SIBLING of `ProbeUnanswered`; the
  `JournalUnreadable` parallel; REPAIR): non-UTF-8 file, unparseable line —
  the unparseable-line case MOVED out from under `ProbeUnanswered` because
  the parent's docstring promises every subclass asks to be retried, and a
  non-JSON line reads identically on every retry. `BindingProbeUnanswered`
  (under `ProbeUnanswered`; RETRY): permission wall, I/O error, unstattable
  path. Both catchable as one `AttestationRefusal`; a test asserts the split;
  three existing tests moved arms. `bound_lineage`'s docstring (your r3 stale
  find — the two turned out to be one site) rewritten: absent answers None,
  everything else refuses, which refusal asks for what.

## 3. Verify

1. Your b"\xff\xfe" repro through BOTH `bound_lineage()` and
   `aliased_lineage()` → typed refusal (`BindingsUnreadable`), nothing
   journaled, no binding written. Re-run.
2. Mutation demos re-run: each decode arm reverted SEPARATELY (bound_lineage's
   revert fails open-path + direct repros; aliased_lineage's fails the direct
   alias-sweep repro) — and the escape reproduces as `ESCAPED untyped:
   UnicodeDecodeError` to an `AttestationRefusal` catcher.
3. THE ARM SPLIT, adversarially: the impl reshuffled types you verified last
   round. Is the remedy split TRUE — every `ProbeUnanswered` subclass case now
   genuinely transient-retryable, every `BindingsUnreadable` case genuinely
   repair-requiring? Construct a case that lands in the wrong arm if you can
   (e.g. a transient decode failure — does one exist? — or a permanent
   permission wall filed under retry). The moved tests: do they still pin what
   they pinned?
4. The rewritten `bound_lineage` docstring vs shipped behavior; and the impl's
   deliberate leave-alone (journal-side "skipped" prose still describes real
   journal skip-and-report behavior) — confirm the leave-alone is right.
5. §04b cost sentence (b2c35955) against the implementation once more.
6. Counts: engine 2299+1s+0f (+4), arch 99 separate, ruff clean on changed
   files, `git diff --check` clean, worktree clean after mutations.

## 4. Verdict format

Per-item PASS/FAIL + evidence. New findings: `S3I-L-<n>` continuing. Then one
line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).
