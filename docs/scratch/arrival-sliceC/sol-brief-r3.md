# Cut C — sol cross-family review r3 (final verification, narrow scope)

Your r1 and r2 rounds and their briefs are at docs/scratch/arrival-sliceC/sol-*-r{1,2}*.{md,log}; every ruling there stands. r2's three findings were remediated. This round verifies EXACTLY those three fixes — nothing else has changed except this brief's own commit (verify: `git diff d9a8ed7d..HEAD --stat` shows only libs/atoms/ordering.py, libs/atoms/tests/test_ordering.py, and docs/scratch files). Deliver ALL sections in one response; do not stop to ask questions.

Fix commits to verify (per-commit PASS/FAIL with evidence; re-run your own r2 probes and attack):
- 723dd535 [C-SOL-05] — refusal categories are now separate complete passes (mixed type > NaN key > NaN id, precedence by pass order). ATTACK: your exact ('n','i')/('i','n') pair must both give the mixed-type category; probe additional shapes (NaN present in both a mixed-type AND same-type region; the offending-value identity may differ by order — only the CATEGORY is pinned).
- 3ad2933e (+7f71f1e6 rewrap) [C-SOL-07] — float NaN tie-break id refuses, attributed to the ID side; string ids unaffected; default get_id can't produce floats (documented). ATTACK: your equal-K/NaN-id permutations; NaN id present but K distinct on every record (no tie needed — does the check still fire, and should it? the fix refuses on presence, which is the deterministic reading); mixed str/float ids with a NaN.
- 0b90c9ab [C-SOL-06] — the docstring ratchet was REMOVED by arbiter ruling (construction-over-detection: a prose ratchet that fell to evasions in one round is not improved, it is deleted; the two behavioral runtime-message pins remain). Verify the pins exist and pass; confirm removal left no dead allowlist/helpers. Do not re-report the removal itself — it is the ruling.

Verdict: per-fix PASS/FAIL with probe evidence; any NEW findings (C-SOL-08+); overall CONVERGED / NOT_CONVERGED. Proof-of-work bar as before.
