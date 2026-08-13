# Cross-family review brief — cli-honesty-wave, round 6 (closing call)

r5: R4-F1 PASS; NOT CONVERGED on the exposed key-identity seam. The arbiter
split it by contract: the LOOKUP bug is fixed in-wave (this round's target);
the IDENTITY question (native 0 vs string "0" as distinct engine items behind
one projected address) is deliberately HELD at Kyle's gate as
thread:fold-key-identity-native-vs-string — blast radius (engine fold
semantics, replay determinism) exceeds a CLI wave. It ships DISCLOSED: the
thread receipt + a pinning test documenting the duality as known behavior.

## Anchor
- Branch cli-honesty-wave; target commit 3bb55891 (+ merge tip) — the only
  code change since r5. New leaf module apps/loops/src/loops/foldkey.py owns
  project_fold_key; surface._row_key delegates; provenance._entry_for_key
  uses it (direct string hit first, projection scan otherwise — string "0"
  is the deterministic tie-winner, docstring'd with the thread ref).
- Baseline 2518 passed / 1 xfailed.

## Verify
1. Your r5 reproduction: native-numeric-0 item, `--why --json` → real field
   attributions (was fields:[]).
2. Evasions on the lookup: False key --why; native-0 AND string-"0"
   coexisting → --why deterministic (string wins, per docstring); --why on
   a string-keyed item unchanged.
3. The duality pin: confirm the test asserts current two-rows-one-address
   behavior WITH the thread reference (disclosure quality, not silence).
4. Full suite + ./dev check.

## Verdict — the closing call
[R6-F<n>] findings if any. Overall CONVERGED / NOT CONVERGED. If your r5
objection stands DESPITE the disclosed-not-resolved framing (receipted
thread at the owner's gate + pinned disclosure), say so with the receipt
you find insufficient — the arbiter will weigh it, not defend. Either way:
one paragraph of residual risk for the wave record.
