# Cross-family review brief — cli-honesty-wave, round 7 (closing call, take 2)

r6 accepted the identity hold; its one finding (R6-F1 replay switching) is
fixed. Target: commit 586d1626 (+ merge tip) — the only change since r6.

## The fix
_winning_state_key resolves the winning identity ONCE before replay (string
wins when present; else the native value projecting to the address; else
honest empty); the loop reads only that item's state. Loser facts remain in
the shared chronology (they are in the bucket) but contribute nothing to
fields/changed. Docstring contract: "--why explains exactly the row read
renders." Pinned: both emission orders yield the string item's fields only,
content-invariant across orders (setter INDEXES track chronology position,
which legitimately reorders — the pinned invariant is content, disclosed in
the test); lone-native full attribution unchanged.

## Verify
1. Your r6 reproductions, both orders — no native residue, no smuggled
   priors, content-invariant attribution.
2. 1-2 evasions: three-way coexistence (0, "0", False under one projected
   key if constructible), winner-absent case (native only — full
   attribution), interleaved supersessions across the two items.
3. Full suite (baseline 2521 passed / 1 xfailed) + ./dev check.

## Verdict — closing call
[R7-F<n>] if any. CONVERGED / NOT CONVERGED + residual-risk paragraph for
the wave record. The identity design question remains held at
thread:fold-key-identity-native-vs-string per the accepted receipt.
