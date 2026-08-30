# Sol review brief — arrival-break slice 3, integration round 2 (per-WP, LOW)

Round 2 of the integration review, verifying the fixes for your r1 findings
S3I-L-1 (the silent reset/restore loop — BLOCKING) and S3I-L-2 (weakening field
on refused reads).

## 1. Anchor

- Worktree: this directory (`~/Code/loops-s3wp1`), branch `slice3/arrival-witness`,
  NEW tip `4b1a14a4`. Diff since your r1: `git diff b98ec734...4b1a14a4`.
- Suites: engine per-package, architecture SEPARATELY. Claimed: engine 2283
  passed + 1 skipped + 0 failed, arch 99, generator byte-reproducible, ruff clean.
- Arbiter-applied fixes since r1: NONE (the one from r1's table was verified by
  you already).

## 2. Unverified fixes, by commit

- `4061f0c9` + `970fc490` — S3I-L-1: AMENDMENT #6, the abandoned-epoch fence.
  ADVANCED is refused (new typed seam refusal `AbandonedHistoryFenced`) when the
  verified descent path touches an entry journaled in an abandoned epoch.
  Identity-keyed (ordinal+hash) anchor set from the abandoned epochs' entries;
  reach = every walked coordinate via `head_at` at each anchor's own ordinal;
  placement after ADVANCED, before `_Earned` — a fenced open journals NOTHING
  (`test_the_fenced_open_journals_nothing`); `compare()` untouched, comparison
  vectors untouched. LIFT RULE — NOTE AN IMPL-NARROWING OF THE ARBITER'S RULING,
  ratified: lift only by the CURRENT boundary decree (the one decree nothing has
  superseded), NOT "any later reset decreeing at/above" — the broader wording
  reopens the loop via reset-to-10 / reset-back-to-5 (the 10-entry would lift on
  the overridden decree forever). The `trust_reset` disclosure docstring is
  rewritten: states the fence, the one-ceremony recovery cost, and records what
  it used to say and why that was the loop's own description.
- `26556270` — S3I-L-2: `weakening` emitted as `null` on refused reads (chosen
  over schema-exemption; SCHEMA.md states the four counts travel together,
  all-or-nothing, why absent ≠ null). The consumer's early return on refused
  reads is GONE — every journal vector passes an exact key-set check and a
  both-directions all-or-nothing rule on the four counts.
- `4b1a14a4` merge — doc rounds 3-4: §04b "What a reset fences out" (fence
  mechanism, lift narrowing with the counterexample, the superseded sentence
  recorded as the loop's own description), §08 replayed-reset row corrected +
  NEW restored-abandoned-backup row, §07 ADVANCED action cell qualified +
  `open()` sketch shows the fence pre-journaling, §11 callout, §02 threat-list
  entry "Return to history a ceremony abandoned (§04b)".

## 3. Verify each — empirically where possible

1. **S3I-L-1 regression**: your loop construction verbatim — reset from
   abandoned N+1 to N, restore the authentic N+1 backup, open must be REFUSED
   (`AbandonedHistoryFenced`), and the fenced open must journal nothing and
   write no binding. Re-run their test AND rebuild your own r1 construction
   independently.
2. **Mutation demo**: fence reverted → 5 failed, the cycle reopens
   (advanced-then-unchanged). Re-run.
3. **The lift rule end-to-end**: after the operator re-decrees at the recovered
   head (a reset AT the abandoned coordinate — verified possible: `trust_reset`
   can decree at/above K and the reset-inclusive epoch makes the boundary entry
   K itself), the previously-fenced open proceeds. Re-run their test.
4. **Identity-not-span, both sides**: a legitimate post-reset re-advance at an
   abandoned ORDINAL with a different hash stays ADVANCED (what a span fence
   would destroy); the grown-offline variant (present N+3 over abandoned N+1)
   is fenced via the walked path. Re-run both.
5. **S3I-L-2**: both consumer demos — drop `weakening` from the refused vector →
   1 failed naming the field; a COMPLETED read stating `weakening: null` →
   1 failed. Re-run both; confirm the exact-key-set assertion also rejects a
   STRAY field on any journal vector.
6. **Doc-code agreement on the fence**: §04b's mechanism paragraphs vs the seam
   implementation (anchors, reach, placement, lift narrowing); §08's two changed
   rows vs actual refusal behavior; §02's new entry not overclaiming (the fence
   detects RETURN to abandoned history — it does not claim to detect the
   abandonment-era damage itself).
7. Counts: engine 2283+1s+0f, arch 99 (separate process), generator regenerated
   → identical digest, 31 vector JSONs tracked, ruff clean.

## 4. Try-to-defeat seeds

- **ATTACK THE NARROWED LIFT RULE** (this round's sharpest seed): can any
  crafted reset sequence un-fence an abandoned entry the operator never
  re-decreed? Sequences to try: reset-to-10/reset-to-5 (the counterexample the
  narrowing answers — verify it is actually closed in code, not just in prose);
  reset-at-N+1-then-reset-back-below (does the transient boundary decree lift
  permanently or only while current?); interleaved advances between resets;
  a decree at a coordinate ABOVE the abandoned entry (does at/above-lifting
  leak acceptance of entries BELOW the decreed head that were abandoned by an
  earlier ceremony?).
- **Fence bypass via the other outcomes**: the fence guards ADVANCED. Walk the
  other acceptance paths — can abandoned history return via FIRST_CONTACT
  (binding deleted/aliased — does the L-1 object-identity sweep interact),
  or via a journal whose abandoned epochs are unreadable (damage in the
  abandoned region — do fence anchors survive a bounded read, and what does
  the fence do under HeadLowerBound/IndeterminateComparison)?
- **Fence × dedup composition**: dedup closes the UNCHANGED road, the fence the
  ADVANCED road (the doc's "same destination, different roads"). Is there a
  THIRD road — e.g. same-height at the abandoned coordinate after a partial
  re-advance, or an equivocation-resolution path that lands on abandoned bytes?
- **Performance honesty**: the fence walks `head_at` per abandoned anchor on
  ADVANCED opens. Journals with many resets/abandoned entries — is the cost
  bounded and disclosed, or does an adversarial journal make opens quadratic?

## 5. Verdict format

Per-item PASS/FAIL + evidence. New findings: `S3I-L-<n>` continuing, file:line,
severity, concrete failure scenario. Then one line: **CONVERGED** or
**NOT CONVERGED** (with the blocking list).
