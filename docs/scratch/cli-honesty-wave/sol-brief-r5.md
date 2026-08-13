# Cross-family review brief — cli-honesty-wave, round 5 (R4-F1 confirmation)

r4 verified 6/7 claim-groups; the one FAIL (R4-F1, falsy-key truthiness) has
been fixed at the substrate. This round confirms that fix and calls the wave.

## Anchor
- Repo: /Users/kaygee/Code/loops — branch `cli-honesty-wave`
- Target: commit 108870ae (+ merge tip) — the ONLY code change since r4.
- Ruling applied: engine fold acceptance (key is valid iff not None) is the
  contract; surface._row_key now gates `is not None`. The old unit pin of the
  nulling behavior was INVERTED with the ruling cited (ratified by arbiter).
- Residues pinned, ruled follow-ups (do not re-report): empty-string keys
  keep the kind/<id> address fallback; _item_full_key source-side truthiness
  stays (thread:cli-error-surface-unification carries both).

## Verify
1. Your r4 reproduction: numeric-0 fold key, `--key 0,missing --status open`
   → exit 0 with the row, no statusless refusal.
2. The parity matrix now includes the corner and passes; construct 2-3 of
   your own falsy-key evasions (False key, "0" string vs 0 numeric, 0-keyed
   row under --status filtering and under plain --key).
3. Collateral sweep: falsy-keyed rows now carry real keys/addresses — probe
   one render path (fold view listing a 0-keyed item) and --refs/why if
   cheap, for anything that assumed Row.key is None.
4. Full suite (baseline 2516 passed / 1 xfailed) + ./dev check.

## Verdict
R4-F1: PASS/FAIL with evidence. New findings [R5-F<n>]. Overall:
CONVERGED / NOT CONVERGED — this is the wave-closing call; state residual
risk in one paragraph either way.
