# Sol review brief — arrival-break slice 2 / WP2, round 2 (per-WP, LOW)

Round 2 of your review of slice-2 WP2. Round 1 was NOT CONVERGED with blocking
S2WP2-L-1 (short import accepted) and non-blocking S2WP2-L-2 (family-completeness not
inventory). Both claimed fixed in one commit.

## Anchor

- Branch: `slice2/wp2-replicate`, NEW tip `b4d61809` (one commit over r1's `165d86ea`).
- Diff to review: `git diff 165d86ea...b4d61809` in full.

## Unverified fixes — verify empirically, this is the round's core

| finding | claim | your job |
|---|---|---|
| L-1 | Length-first explicit check (`len(imported) < head.ordinal+1` → refuse), surviving zip `strict=True` over `imported[:overlap]`. Refusal = `HeadMismatch` naming both heights (deliberately NOT `SameHeightFork` — nothing disagrees at any height; re-export at/past the head is HeadMismatch's remedy). The old test asserting your repro as success was split: refusal test (your exact repro → HeadMismatch, log bytes and head unchanged) + same-length idempotent accept as negative control (green under fix AND mutation). | Re-run YOUR r1 repro against the fix. Re-run their mutation (restore strict=False acceptance → refusal test fails, control still green). Assess the HeadMismatch-vs-SameHeightFork choice against the taxonomy your r1 endorsed (ForkedHeight = different record at a height you'd fill; is "stops short, agrees everywhere" correctly NOT a fork?). Confirm log bytes + head untouched on refusal. |
| L-2 | `VECTOR_INVENTORY`: exact per-family filenames, asserted both directions (missing fixture fails naming itself; unfiled vector fails; stems match family prefix). | Re-run their mutation (delete one fixture → fails naming it, siblings present). Try the reverse: add a stray `replicate-*.json` → must fail as unclassified. |

## Scope check

The commit must touch only `arrival_file_backend.py`, the two test files, and the
report. Engine claimed 2034 (+1 net). Store 180, architecture 99 unchanged.

## Seeded static diagnostics (assess, don't assume)

Pyright on the current tip flags `arrival_file_backend.py:664` (`.ordinal` on a
possibly-None value) and `:707` (unreachable code). WP1's gate proved an earlier
sibling flag (:309) unreachable by construction — check whether these two are the same
pattern or real (construct the None/unreachable case if reachable).

## Verdict format

Per fix: PASS/FAIL + evidence. New findings: `S2WP2-L-<n>` continuing your numbering.
Then one line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).
