# followup — Fable review

Effort: low. Finished: 2026-09-06T19:25:47.247643+00:00.
Packet SHA-256: `134669568db92c9551c664588a7e6baab46d267f548fac6280c36d632554d554`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.**

**Error family consistency.** `sdk/kind.py:123-125` now passes `DeclarationPreparationRefused` as the refusal callable. The validator invokes it with the message only (`declaration.py:867-870`), so `coordinator_phase` and `effects` are `None` and neither head attribute is set (`arrival_declarations.py:88-102`). `normalize_exception` maps it through the `ArrivalError` branch to `ArrivalRefusal` with `source_type="DeclarationPreparationRefused"` (`errors.py:473-482`), and `_evidence_details` returns `None` because no phase or effects are present (`errors.py:208-241`). The preview therefore surfaces the same family and identical message as signed preparation without inventing a preparation receipt or custody claim. That asymmetry with `_preparation_refused` (which adds `phase="prepare"` and custody not-entered) is correct rather than a gap: the preview has already opened a bounded read via `_open_arrival_read`, so asserting custody not-entered would be false. Test expectation at `test_arrival_declarations.py:710` follows the change; the byte-prefix check at line 714 still shows no mutation. The case-distinct `X` test is unaffected.

**Findings**

1. **Low, documentation only. Source: `primary-triage.md:30-32`.** Scenario: the triage says the runtime spec check precedes materialization and so a newly added implicit loop would not be caught by the later check. Per the accepted validation note (`consistency-c5-validation-2026-09-06.md:131-134`, and my original item at `c5-findings.md:12`), the ordinary and batch planners re-check the detached candidate's registered kinds after `materialize_vertex`, which is where a new implicit loop would appear. The runtime fallback I described does exist for write planning; what it does not provide is preflight refusal before custody, which is the triage's real point. Correction: reword the sentence to say the post-materialization planner check would still refuse at write time but not before custody/hydration. Deferral of the shared constant remains a reasonable maintenance decision; no code change requested.

**Other note dispositions.** Note 3 disposition is sound: `test_tick_free_collision_can_be_corrected_by_signed_append_forward` (`test_arrival_emit.py:249-277`) supplies real signers, receives a Commit, checks append-only prefix, and emits afterward, which is the end-to-end evidence I asked for. No engine-fixture duplication needed. D5/C6 historical-role design remains explicitly deferred and I did not expand into it.

I did not execute any tests; the pass counts in the validation note are the owners' evidence.
