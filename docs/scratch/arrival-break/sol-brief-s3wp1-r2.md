# Sol review brief — arrival-break slice 3 / WP1, round 2 (per-WP, LOW)

Round 2 of your review of slice-3 WP1 (head-attestation module). Round 1 was NOT
CONVERGED with blocking S3WP1-L-1 (header recognition's kindless precondition —
your v2-header demo refused the whole journal).

## Anchor

- Branch: `slice3/arrival-witness`, NEW tip `8ce304c6` (two commits over r1's
  `fbdc5770`). Diff to review: `git diff fbdc5770...8ce304c6` in full.

## The ruling your finding received (and why not your implied fix)

Type-ALONE recognition was REJECTED: it opens the mirror channel — a future ENTRY
carrying the type string would be silently ABSORBED as a header, the same class the
gate's round-1 BLOCKING-1 closed. Ruled three-way instead: (1) kindless object bearing
the type string = header; (2) object bearing BOTH type and kind = UNCLASSIFIABLE by
this build — skipped and reported with the ambiguity named, never absorbed, never a
header, never refuses the file; (3) readable entries with no recognized header =
tolerated, `known` weakens to `HeadLowerBound` with the header absence reported
(without a line number — an absence has none). `JournalUnreadable` narrows to
nothing-to-parse (directory, permission wall, non-text bytes) — the impl reports this
CLOSED a latent gap (those cases previously escaped as raw OSError/UnicodeDecodeError
past any `AttestationRefusal` catcher).

## Unverified fix — verify empirically, this is the round's core

| commit | claim | your job |
|---|---|---|
| 8ce304c6 (impl 9b616e28) | The three-way rule as above; contract sentence corrected at the site; three mutation demos — (i-a) kindless precondition restored → 2 named failures (your demo test + the mirror test); (i-b) headerless-entries refuse restored → 1 failure; (ii) type+kind classified as header (absorption arm) → 2 failures. Engine 2157+1s (+3 net). Existing create-race and header-only tests green throughout. | Re-run YOUR OWN r1 demo (the v2-shaped header + valid entry journal) against the fix — journal must read, ambiguous line skipped+reported, entries readable, comparisons behave per the weakened-claim rules. Construct the MIRROR case yourself (an entry-shaped object carrying the type string) — must be skipped, never absorbed, and the loss must weaken `known`. Re-run all three mutation demos. Verify the latent-gap claim: pre-fix, a directory (or non-UTF8 bytes) at the journal path escaped as a builtin exception; post-fix it is typed. Confirm the diff touches only the module, tests, and report. |

## Deliberately out of scope (flag only if you find it UNSOUND, not unbuilt)

The header's protocol/wire values are written and never read — a v2-shaped header is
now recognized and its values ignored, so a skewed journal reads anyway. Deferred to
wherever wire v2 lands (handoff notes carry it). Analysis so far says skew produces
spurious typed refusals (different hash derivations → same-ordinal/different-hash →
fork/equivocation), never silent acceptance — if you can construct silent acceptance
through version skew, THAT is a finding.

## Verdict format

Fix: PASS/FAIL + evidence. New findings: `S3WP1-L-<n>` continuing your numbering.
Then one line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).
