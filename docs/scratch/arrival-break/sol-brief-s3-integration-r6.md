# Sol review brief — arrival-break slice 3, integration round 6 (per-WP, LOW — short verify)

Round 6, verifying the fix for your r5 finding S3I-L-8 (bound_lineage docstring
remedy residue) and presenting the arbiter's REFUTATION of S3I-L-9 for your
contest.

## 1. Anchor

- Worktree: this directory (`~/Code/loops-s3wp1`), branch `slice3/arrival-witness`,
  NEW tip `215e1c2e`. Diff since your r5: `git diff 63028677...215e1c2e`.
- Claimed: engine 2304 passed + 1 skipped + 0 failed, arch 99 separately, ruff
  clean. No test changes.

## 2. The S3I-L-9 refutation — contest it if wrong

The arbiter DISMISSED S3I-L-9 with the overclaim located in the arbiter's own
r5 brief: "exactly one failure" conflated demo LOCALIZATION (both failing
tests name the same arm — satisfied) with single-responsibility purism (whose
"fix" would narrow the six-cause mapping test to one reader, weakening it).
The guarded defect class is fails-ZERO (masking); fails-several-all-naming-one-
arm is redundant detection in the failing direction. No change was made to the
mapping test. If you believe overlapping test responsibilities here cause a
REAL problem the refutation misses (a scenario where the overlap misleads a
maintainer or hides a regression), say so with the scenario; otherwise confirm
the dismissal.

## 3. Unverified fix (`25b0a078` + `215e1c2e`)

S3I-L-8, WITH A DISCLOSED CAVEAT — not strictly prose-only:

- `bound_lineage`'s docstring now enumerates the actual answer surface, each
  row verified against the body by the impl: absent → None (FileNotFoundError
  arm); empty → None (loop never runs); blank line → skipped
  (`if not stripped: continue`); foreign binding → None (location comparison);
  uninterpretable content → `BindingsUnreadable`; unanswerable storage →
  `BindingProbeUnanswered`. States why there is no transience claim.
- THREE more sites swept in the same unit: a decode comment saying PERMANENT,
  an OSError comment saying TRANSIENT-flavoured (the superseded axis one line
  below the docstring correcting it), and a match-branch comment describing
  the skip branch it wasn't attached to.
- THE CAVEAT: two content-side refusal MESSAGES dropped a trailing "then retry
  the open" — remedy-axis residue inside content refusals where retry cannot
  help. The impl verified nothing pinned the text (the two tests asserting
  "retry the open" are storage-side, on `storage_advice` prose, and pass).
- Deliberately LEFT: `_identity_of`'s docstring names "a permission wall, a
  transient I/O error" as example causes — description of what can happen,
  not a family-promise claim. Named so you don't read it as missed residue.

## 4. Verify

1. The docstring's six rows against the body — is the enumeration exhaustively
   true now (your r5 construction set plus anything else the body can answer)?
2. The two message edits: content-side refusals no longer advise retry;
   storage-side advisories still do where retry can help; nothing else in the
   diff beyond prose/messages (verify the diff's actual reach).
3. The three swept comment sites and the deliberately-left descriptive prose —
   is the left prose genuinely descriptive rather than promissory?
4. Counts: engine 2304+1s+0f (unchanged — no test changes), arch 99 separate,
   ruff clean, `git diff --check` clean, worktree clean.

## 5. Verdict format

Per-item PASS/FAIL + evidence. New findings: `S3I-L-<n>` continuing. Then one
line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).
