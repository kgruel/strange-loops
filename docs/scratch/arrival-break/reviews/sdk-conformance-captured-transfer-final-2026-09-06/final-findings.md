# final — Fable review

Effort: low. Finished: 2026-09-07T02:20:20.956202+00:00.
Packet SHA-256: `2d626f36e4197e2a0ce22bc866b6cb157d4ea85574c15a8cb295e685b37e6ecd`.

Static reviewer output; findings still require primary triage.

**ACCEPT.** No blockers found in the static review of the test, README delta, and supporting engine/SDK code.

**Contract coverage checked against the test**

- **Exact exported bytes/head/manifest/count**: `test_arrival_transfer_workload.py:120-131` asserts selected vs. captured head divergence, manifest lineage/ordinal/hash/count, byte count, byte-equality with the pre-advance source snapshot, and exclusion of the later record. Stable identity is rechecked at line 140 after the refusal.
- **Causal refusal specificity**: line 137 pins `source_type == "HeadRollback"`. In `arrival_restore.py:229-292` the only path producing that refusal for a receiver at genesis with `selected ≥ before` is the witness-floor observation at lines 282-292, which runs before `replicate` at line 297. Receiver bytes and descriptor are asserted unchanged (lines 139, 141).
- **Full-head chain and retention**: lines 145-152 assert `before`/`after`/`commit` agreement, receiver equals current source bytes, and the prior receiver prefix is retained. Role preserved at line 150.
- **Verify while projection stale**: lines 156-169 assert structural claims/excludes, then a CURRENT read raises `ProjectionBehind`. Line 174 (`projected_before == initial_head`) proves the failed read did no implicit repair.
- **Explicit sync before/target/after, rows, prior-row retention, no-op restore, strict JSON, isolation**: lines 171-226 and the autouse fixture at lines 24-28 cover these as specified. Source/receiver row and basis equality at lines 206-209 also covers receipt-order coordinates via full item equality.

**Concrete false positives a reviewer might raise, and why they are not blockers**

- "`ProjectionBehind` is an engine type, not `ArrivalRefusal`." README lines 445-447 document that descriptor reads surface engine contract refusals directly. Correct as written.
- "`manifest["count"] == ordinal + 1` hard-codes zero-based ordinals." That is the engine's ordinal convention and the assertion is the intended density check. No change needed.
- "The refusal at line 136 could be a receiver-side rollback." Receiver head is `initial_head`, below `selected_head`, so the prefix check at `arrival_restore.py:251` passes. Only the witness-floor proof can yield `HeadRollback` here.
- "Descriptor rewrite via string replace is fragile." A no-op replace would fail at line 150 (`role == "replica"`) or at line 60/143 through location mismatch, so the fixture is self-checking.

**Optional findings, non-blocking**

- Line 152 is implied by line 151 given line 129/131; it can stay as an explicit retention statement.
- `restored.source_store.role == "authority"` is not asserted; adding it would complete the descriptor-role claim symmetrically.
- The conformance note at `sdk-conformance-captured-transfer-2026-09-06.md:55-62` cites native run counts and a SHA. I did not execute anything; those remain prior evidence from the attached logs.
