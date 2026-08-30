# Sol review brief — arrival-break slice 3, integration round 5 (per-WP, LOW — short verify)

Round 5, verifying the fixes for your r4 blockers S3I-L-6 (remedy promise
undecidable) and S3I-L-7 (shape filter silently drops).

## 1. Anchor

- Worktree: this directory (`~/Code/loops-s3wp1`), branch `slice3/arrival-witness`,
  NEW tip `63028677`. Diff since your r4: `git diff 7edca4b2...63028677`.
- Claimed: engine 2304 passed + 1 skipped + 0 failed, arch 99 separately, ruff
  clean on changed files.
- Arbiter-applied fixes since r4: NONE.

## 2. Unverified fixes (`f5166c01` + `63028677`)

- L-6, the contract re-scope: the two types KEEP their members and CHANGE their
  claims. `BindingsUnreadable` = the bytes ARRIVED but are uninterpretable as
  bindings (decode, parse, shape). `ProbeUnanswered` = the bytes NEVER arrived
  (OSError family, `IsADirectoryError` included). The parent no longer promises
  retryability; remedy is advisory per-cause prose in the message — the
  directory case now says a directory sits where the file should be, says
  remove it, and says plainly that retrying will not resolve it. Family test
  upgraded from inheritance-only to the concrete cause→family mapping for all
  six causes (decode, parse, shape, permission wall, IsADirectoryError,
  unstattable path).
- L-7: `{}` and `[]` lines are content failures → `BindingsUnreadable` through
  BOTH readers. The narrow survivor is pinned at both readers: a well-formed
  binding naming a DIFFERENT location skips to None (else every multi-store
  bindings file is unopenable). `bound_lineage`'s "everything else refuses" is
  now claimed-and-true.
- Mutation demos: each reader's shape arm reverted separately (the impl
  discloses its first demo pass failed NOTHING for bound_lineage's arm — the
  seam's sweep also refuses unusable shape, so the integration test measured
  the outer layer; a direct-call pin was added and the demo now bites), plus
  the advisory prose reverted to a flat retry promise.

## 3. Verify

1. Your r4 constructions: `IsADirectoryError` → `ProbeUnanswered` whose MESSAGE
   carries the directory-specific no-retry advisory; `{}` and `[]` →
   `BindingsUnreadable` through both readers, nothing journaled, no binding
   written. Re-run yours; re-run theirs.
2. The six-cause mapping test: does it actually pin cause→family (construct a
   seventh cause — e.g. `NotADirectoryError`, or a decode failure mid-file —
   and check the family it lands in is the contract's answer, not an accident)?
3. The narrow survivor: a well-formed foreign-location binding line → None with
   no refusal; a multi-store bindings file with one valid local binding among
   foreign ones → the local binding found. Verify the survivor cannot be
   widened into a hole (a line that is binding-SHAPED but for a foreign
   location with CORRUPT fields — where does it land, and is that right?).
4. All mutation demos re-run, including the direct-call pins biting where the
   first pass was masked (revert one reader's shape arm → exactly the
   direct-call test for THAT reader fails, not zero, not several).
5. The rewritten parent/`bound_lineage` docstrings vs shipped behavior — the
   "everything else refuses" claim is now exhaustively true?
6. Counts: engine 2304+1s+0f (+5), arch 99 separate, ruff clean on changed
   files, `git diff --check` clean, worktree clean after mutations.

## 4. Verdict format

Per-item PASS/FAIL + evidence. New findings: `S3I-L-<n>` continuing. Then one
line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).
