# Sol review brief — libs-handoff-wave, round 4 (convergence candidate)

## 1. Anchor

- Repo: this checkout, branch `libs-handoff-wave`.
- Since r3: ONE remediation merge (fix/libs-handoff-r3, 7 commits — your six r3
  findings + one advisor follow-up). Diff since your r3 look: the fix branch
  commits (5c4ae34a, 0c191515, 771184c4, 16d320a2, d2f9bfc0, a002b34a,
  1e9ccf20). Full context: `git diff main...HEAD`.
- This is the convergence round: verify the six dispositions, hunt holes in
  these fixes specifically, and make the call.

## 2. R3 disposition table (verify each)

| Finding | Fix | Claim |
|---|---|---|
| R3-01 blocker (dup kinds / comment loss) | 5c4ae34a | Duplicate loop-kind input refuses typed pre-mutation (raw-text multiplicity check — a PRE-condition; parser oracle stays post-condition authority); _verified asserts target == requested LoopDef; edit preserves trailing suffix, refuses on interior-span comments rather than dropping. Evasions: multiplicity check's own lexical blind spots (raw strings again? kind named in a comment?) — note the parser oracle + equality assertion backstop; what matters is no silent loss, not that the precondition catches everything first. |
| R3-02 (assembly vs committed state) | 0c191515 + 1e9ccf20 | Read-back INSIDE the write txn, post-INSERT pre-commit, both stores, fact+tick+absorb paths; ticks-PRAGMA cache kept. Genesis/edit read-back mismatch → UnsignableGenesis/Edit refusal, rollback before any log byte (arbiter-ratified: decision:design/genesis-attestation-mismatch-refuses — an unsigned genesis is unrepresentable, so honest-but-unsigned is unavailable; refusal preserves invariant AND honesty). Your trigger repros must now show honest receipts / typed refusals. |
| R3-03 (typed floor gaps) | 771184c4 | _writable total over inaccessible paths; pre-intent open catches JsonlCanonicalUnsupported + codec/unicode failures → typed refused, no residue. |
| R3-04 (recovery race) | 16d320a2 | flock recovery lock beside the index across detect→discard→rebuild; losers reopen winner's inode under lock; quarantine rename (pid+seq, no wall clock). Your two-thread harness must converge on one inode. |
| R3-05 (busy ≠ corrupt) | d2f9bfc0 | sqlite BUSY/LOCKED → "refused" with busy reason before the generic branch; no discard. |
| R3-06 (handle leak) | a002b34a | Intent write inside store-lifetime try/finally; OSError → typed refusal, handle closed. |

## 3. Standing dispositions (do not re-litigate)

All r1/r2 dispositions previously verified; the genesis-refusal fork is
arbiter-ratified (fact cited above); CLI-migration residue is sequenced
forcing-consumer work (succession plan), not wave scope.

## 4. Verdict format

Per finding: id (SOL-R4-NN), file:line, severity, claim, empirical evidence,
fix direction. End with CONVERGED / NOT CONVERGED. CONVERGED requires: all six
r3 dispositions verified sound, zero new blocker/major, and your judgment that
the branch honors the r1 brief's contracts.
