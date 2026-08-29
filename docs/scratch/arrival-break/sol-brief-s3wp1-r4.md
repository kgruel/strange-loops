# Sol review brief — arrival-break slice 3 / WP1, round 4 (per-WP, LOW — final verify)

Round 4, verifying your r3 finding S3WP1-L-3 (lower-bound prose said "unreadable
lines"). Runtime was verified in r2; r3 verified seven prose fixes; this round
verifies the TERMINOLOGY fix that should end the prose-lag series.

## Anchor

- Branch: `slice3/arrival-witness`, NEW tip `9ed893fe` (two commits over r3's
  `5d24cf06`). Diff: `git diff 5d24cf06...9ed893fe`.

## The fix's claims — verify each

1. The term is **"incomplete read"**, canonically defined on `HeadLowerBound`: the
   read needed something it did not get (unparseable line, unclassifiable line,
   later-build entry, or the header itself); non-empty `.skipped` IS the condition.
   Defined by what the read LACKS, not why — a new cause joins without new
   vocabulary. Applied to: HeadLowerBound docstring, IndeterminateComparison summary,
   established_head docstring, the parser summary, and BOTH emitted refusal messages.
2. NOT prose-only: the refusal messages changed ("this read of the journal is
   incomplete"; skipped labeled "The read missed:"). The impl checked no test pinned
   the old text before editing (verify), and ADDED one test pinning the term for the
   missing-header-all-entries-readable case — asserting the message says "incomplete"
   and does NOT say "unreadable lines". Engine 2158+1s (+1, that test).
3. Post-fix sweep verifiable by re-grep: every remaining "unreadable"/"cannot be
   read" is about text that genuinely cannot be read (the two exception classes, the
   per-line skip note, read_journal's OSError arm, the torn-tail guard). Re-run the
   grep yourself; anything else reaching for the old vocabulary is a finding.
4. "unaccounted for" (your r3 phrasing) was REJECTED for colliding with
   `unaccounted_heads` (heads the STORE cannot account for — different question,
   different party). Assess: is that collision argument sound, or do you want the
   rename? Say which explicitly.

## Verdict format

Fix: PASS/FAIL + evidence. Any new findings: `S3WP1-L-<n>`. Then one line:
**CONVERGED** or **NOT CONVERGED**.
