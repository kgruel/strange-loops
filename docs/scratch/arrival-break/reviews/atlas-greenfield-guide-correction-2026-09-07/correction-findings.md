# correction — Fable review

Effort: low. Finished: 2026-09-07T06:07:07.167133+00:00.
Packet SHA-256: `0816d3f2affe5c3cfa9b99d1fc5903c99992d83877a278752596d34e4ed5e8c1`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT.** No blockers.

**B1 resolved.** Lines 15-21 now instruct saving the six blocks into one script and running it with `bash`, and warn against pasting the strict options interactively. That matches the native replay. The closure check confirms the six blocks still hash to the executed script.

**B2 withdrawn.** The extract shows `declaration.json` carries top-level `head` and `phase`. My original finding inferred absence from a checker that did not assert those fields, which was invalid. The adopted wording at lines 249-251 is accurate and does not contradict the actual shape.

**Optional adoptions checked.** Per-item signed/witnessed/stored wording, the `uv.lock` note, and the Python 3.11 floor as package metadata are all consistent with the evidence. The invocation count of 14 matches the six blocks. The concurrent edit to `scripts/generate-docs.py` is correctly scoped out, since the correction relies on archived before/after evidence plus command-byte equality rather than a rerun.

**Optional, non-blocking**

- The replay record still says "Fable prose correction review pending" on lines 3 and 73. Update on closure.
- Line 15 could read "Python 3.11+ per package metadata; tested on 3.13" to preempt the same question from readers.
