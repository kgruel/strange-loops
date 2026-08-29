# Sol review brief — arrival-break slice 2 / WP3, round 2 (per-WP, LOW)

Round 2 of your review of slice-2 WP3 (admission extraction). Round 1 verdict was NOT
CONVERGED with one blocking finding, S2WP3-L-1 (target_state mutation → silent record
drop on CAS retry with a caller-owned cache), plus non-blocking S2WP3-L-2 (rederive
failure staleness — verified pre-existing at wave base, DEFERRED to slice 5, correctly
dispositioned, do not re-open unless the deferral is unsound).

## Anchor

- Branch: `slice2/wp3-admission`, NEW tip `18dc162b` (one commit over the r1 tip
  `e8c93295`). Diff to review: `git diff e8c93295...18dc162b` in full, plus anything
  your r1 flagged.

## Unverified fix — verify empirically, this is the round's core

| commit | claim | your job |
|---|---|---|
| 18dc162b | S2WP3-L-1 fixed by the arbiter-ruled construction arm: `admit_records` does `held = dict(held)` immediately after `target_state()`, every attempt; docstring states the copy as a guarantee this side keeps (NOT a caller freshness obligation). New test `test_admission_callback_ownership.py`: fake owned-cache backend (same mapping every call, seeded with one genuinely-held row) + CAS interloper → asserts facts_added=2/facts_skipped=0, both ids present by walking the log, caller mapping bidirectionally unmutated, exactly two attempts and one rederive. Mutation demo: removing the copy → `assert (0, 2) == (2, 0)` (your r1 counts). Engine 1990+1s (+1, the only branch delta). | Re-run YOUR OWN r1 repro against the fixed tip (your fake backend, not just theirs). Re-run their mutation demo. Check the copy is per-ATTEMPT (a stale-cache second attempt must also be protected). Check the test's assertions match the claim (bidirectional unmutated; retry proven not assumed). Confirm the diff contains nothing beyond the fix + test + report update. |

## Verdict format

Fix: PASS/FAIL + evidence. Any NEW findings: `S2WP3-L-<n>` continuing your numbering,
file:line, severity, failure scenario, evidence. Then one line: **CONVERGED** or
**NOT CONVERGED** (with the blocking list).
