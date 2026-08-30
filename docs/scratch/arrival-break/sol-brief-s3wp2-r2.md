# Sol review brief — arrival-break slice 3 / WP2, round 2 (per-WP, LOW)

Round 2, verifying your r1 blocking finding S3WP2-L-1 (the above-the-bound cell
unpinned — your three-rule adversary passed all 26 vectors).

## Anchor

- Branch: `slice3/wp2-vectors`, NEW tip `319bd076` (one commit over r1's `9735ce3f`).
- Diff: `git diff 9735ce3f...319bd076`.

## The fix's claims — verify each

1. New vector `comparison-incomplete-a-bound-cannot-answer-above-itself`: journal
   form, presented 95 same-lineage ABOVE the bound of 91, `at_known` supplied and
   valid so `advanced` cannot plead missing descent evidence, outcome null,
   sound_answer null. DEVIATION (arbiter-approved): the torn entry sits at ordinal
   200, not the routed 92 — so the fixture EXHIBITS the hazard (true accepted head
   200 unreadable; presenting 95 is a provable 105-ordinal rollback the read cannot
   see). Assess: does the 200 shape genuinely strengthen the vector as claimed?
2. YOUR OWN adversary re-run (below→rollback, equal→decline, above→advanced): at
   9735ce3f it passes all bounded vectors; at 319bd076 it is caught by exactly the
   new vector with the other five green. Re-run both halves yourself.
3. The cell-enumeration ratchet `test_every_cell_of_the_bound_is_exercised_by_some_vector`:
   re-run the impl's demonstration (drop the new vector AND its inventory entry →
   fails naming 'above' as unexercised). Then try to defeat it: can a vector satisfy
   the cell nominally while not actually pinning the behavior (e.g. above-the-bound
   with at_known missing)? If yes, that is a finding.
4. SCHEMA.md's three-row bound table (below→rollback, equal→null, above→null with
   reasons): read it as the foreign implementer again — is the three-cell obligation
   now unambiguous without the Python module?
5. Counts: 27 vectors by three independent counts; engine 2190 (+2); generator
   byte-reproducible; ruff clean; diff touches only generator, vectors, consumer,
   SCHEMA.md, report.

## Verdict format

Fix: PASS/FAIL + evidence. New findings: `S3WP2-L-<n>` continuing your numbering.
Then one line: **CONVERGED** or **NOT CONVERGED**.
