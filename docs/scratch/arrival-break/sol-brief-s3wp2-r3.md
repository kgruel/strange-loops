# Sol review brief — arrival-break slice 3 / WP2, round 3 (per-WP, LOW — final verify)

Round 3, verifying your r2 finding S3WP2-L-2 (hollow occupancy of the above cell).

## Anchor

- Branch: `slice3/wp2-vectors`, NEW tip `9a4b0fa3` (fix at aa042510).
  Diff: `git diff 319bd076...9a4b0fa3`.

## The fix's claims — verify each

1. Vector-envelope assertion (not the cell ratchet — deliberate: the ratchet
   reporting "unexercised: above" about a non-empty cell would be a true alarm with
   a false reason): any bounded vector presenting above the bound must supply
   `at_known` EQUAL to the bound's own coordinate and record hash. SHARPENED past
   the routed "non-null": a wrong-head at_known is answered `rewrite` and is hollow
   identically — their demo (ii) is the justification. Assess the sharpening and the
   placement.
2. Re-run both mutation demos on the disk JSON: (i) at_known → null → 1 failure
   naming the fixture and at_known=None (your r2 defeat, now caught); (ii) at_known
   → non-null wrong head → same assertion fails. Byte-clean restores.
3. Try to defeat the strengthened predicate once more: any remaining artifact shape
   that occupies the above cell while discriminating nothing? (e.g. games with
   lineage, with the presented hash, with a second bounded vector.) If yes, finding.
4. SCHEMA.md's normative obligation for the above cell: foreign-implementer clear?
5. Counts unchanged (engine 2190+1s, arch 99, 27 vectors); generator untouched and
   byte-reproducible; diff touches only consumer, SCHEMA.md, vector? (verify the
   exact file set — the fix claims no new test, no new vector).

## Verdict format

Fix: PASS/FAIL + evidence. New findings: `S3WP2-L-<n>`. Then one line:
**CONVERGED** or **NOT CONVERGED**.
