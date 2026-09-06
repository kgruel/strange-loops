# c3-continuation — Fable review

Effort: low. Finished: 2026-09-06T19:58:26.134650+00:00.
Packet SHA-256: `4e8101465c55c506e779583ab5f6aa91f745efe6317d1733a9c31c91663a97d4`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** No blockers. The one-line production change routes the resumed watermark through the same helper the fresh path uses, and the surrounding contracts hold on inspection.

**Contract check**

- **Original H/P never widen.** Resumed basis at `arrival_consumer.py:210-215` still takes `captured` and `represented_from_token`, both revalidated by `_head_at`. The helper's return value is unused on the resume branch, so a vouched advance cannot leak into the token basis. The positive test asserts exactly this.
- **Foreign, missing, substitution, coordinate.** Consumer line 183 refuses foreign lineage before any lookup. The helper then raises the backend's exception unchanged for a missing prefix, `HeadMismatch` for coordinate or same-height hash disagreement. The five-case matrix maps each to the contract's refusal family and asserts the missing exception is the same instance.
- **Existing protections unchanged.** Generation mismatch, prefix regression and disappearance remain `InvalidContinuation` and still sit after the custody lookup, the same order as the baseline's bare `head_at`. No new refusal is inferred from progress.
- **Handles.** The synthetic matrix asserts snapshot, query, ledger close order on every refusal.
- **Scope.** No token, receipt, sync or custody change. The SDK test uses real append plus explicit sync between pages and confirms the resumed basis equals the original while a fresh read sees the new rows.

**Optional improvements**

1. **Low, test adequacy.** No resumed regression exercises a watermark strictly between P and H, or below P, through the consumer seam. Source: `arrival_consumer.py:205-209`. Trigger: a future adapter that omits the file backend's own prefix check. Consequence: the consumer's "no longer reaches the continuation prefix" branch is only covered indirectly by the file backend raising first. Correction: add two synthetic cases to the matrix, one accepting P ≤ W < H with basis still H/P, one expecting `InvalidContinuation` for W < P.

2. **Low, evidence claim.** The SDK test reads `advanced.projected_after` from `sync_target`; that attribute is not in the packet, so I cannot confirm the shape. The validation doc reports the SDK suite green, which would cover it. Correction: none needed if the reported run is accurate.

Everything else in the packet is agent-reported. I executed no tests.
