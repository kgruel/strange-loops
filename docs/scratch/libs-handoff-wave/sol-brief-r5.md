# Sol review brief — libs-handoff-wave, round 5 (convergence candidate #2)

## 1. Anchor

- Repo: this checkout, branch `libs-handoff-wave`.
- Since r4: ONE remediation merge (fix/libs-handoff-r4, 6 commits): e8839257,
  e6aa268b, 0663c705, 3e5e6067 (+645af05e fixup), 010a97b9.
- Verify the five dispositions below, hunt evasions of these fixes, make the call.

## 2. R4 disposition table (verify each)

| Finding | Fix | Claim |
|---|---|---|
| R4-01 blocker (raw-string-blind guards) | e8839257 | ARBITER-RULED conservative refusal: provable domain = plain "…" strings only, stated in module docstring; all three mutation verbs refuse typed on #" / "# / """ ANYWHERE in the vertex text (whole-text scan deliberately — span-scoping would reopen the arms race). No KDL lexer. Corpus: 0 raw-string hits in .vertex files. Your two r4 repros must now REFUSE. Do not re-litigate the refusal ruling itself; DO probe for delimiter spellings outside the refused set that still evade the scanner (multi-# raw strings ####"..."####?) — if one exists, the refused-set must widen, not the scanner deepen. |
| R4-02 (row-absent conflation) | e6aa268b | _committed_row_state returns existence + signature separately; absent id → rollback + typed CommittedRowMissing. Facts and ticks, both stores. |
| R4-03 (log/index divergence) | 0663c705 | JsonlStore._write serializes EXACTLY the read-back committed row into the log; codec pre-flight on the assembled row retained pre-INSERT. Your signature-nulling repro: log derive-matches index, audit_agreement passes. |
| R4-04 (text-match locked guard) | 3e5e6067 | sql_util.sqlite_busy (one spelling, code-aware 5/6 low-byte) at preflight + BOTH jsonl recovery guards. Authentic SQLITE_LOCKED: no quarantine, same inode, preflight refused. |
| Ceremony full-row honesty (your r4 residue, arbiter-ratified) | 010a97b9 | absorb_genesis/edit compare the COMPLETE committed row; ANY mismatch → UnsignableGenesis/Edit + rollback before any log byte (rationale: a rewritten non-signature field leaves an attestation that no longer verifies — persisting either row is a verification lie). |

## 3. Standing dispositions (do not re-litigate)

All r1–r3 dispositions verified in prior rounds; genesis-refusal and
conservative-refusal rulings are ratified store facts; CLI-migration residue is
sequenced forcing-consumer work.

## 4. Verdict format

Per finding: id (SOL-R5-NN), file:line, severity, claim, empirical evidence,
fix direction. End with CONVERGED / NOT CONVERGED. CONVERGED = all five r4
dispositions sound, zero new blocker/major, branch honors the r1 contracts.
