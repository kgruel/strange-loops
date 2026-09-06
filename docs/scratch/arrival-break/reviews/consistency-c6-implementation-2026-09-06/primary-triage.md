# C6 implementation review — primary triage

Status: complete and accepted; external ACCEPT, no blockers, all six notes triaged.

Fable 5.1 reviewed the frozen implementation at **low** effort on September 6,
2026 (21:32:21–21:35:39 UTC), after two high-effort design reviews and primary
triage. The runner completed with exit 0, verified substantive Fable output,
and no source drift. A 16-token Haiku CLI helper was not a second reviewer.

Packet SHA-256:
`790d16340d92c25d5d394db28c1539178fd234d66fe96e48ef225fd31d1ceacc`.
The [raw findings](c6-implementation-findings.md), frozen complete patch,
manifest, model usage, and validation evidence are retained beside this report.
The existing parameter-pin gate and its call chain were included in this
packet; the earlier design review's missing-gate claim was not repeated.

## Optional notes

1. **Inline template rows — coverage added after review.** Canonical inline
   rows do use `payload.params[*].values`. Terra added a real-store SDK case
   that asserts this serialization, records a generated-loop tick, previews
   and signs an unrelated declaration edit, and emits another tick. Focused
   C6 SDK: **6 passed**; full SDK: **546 passed**; scoped Ruff passed. This is
   additional native validation after Fable's frozen review, not a claim that
   Fable reviewed the added test. Production remains byte-identical.
2. **Vertex subject / multiple documents — no supported-path defect.**
   `lang/document.py:739-746` serializes one vertex with subject and payload
   name from `ast.name`; routine identity changes refuse in declaration diff
   (`:1075-1078`, `:1136-1147`). Multiple subjects in malformed/imported history
   use insertion order in the existing resolver (`engine/declaration.py:258-276`)
   and last-iterated selection in `documents_to_vertex` (`lang/document.py:940-953`).
   C6 matches that behavior. A future imported-evidence singleton validation
   belongs with identity/rename design, not an unrequested C6 rename protocol.
3. **Missing vertex name — compatibility limit, no demonstrated regression.**
   Canonical serialization always includes `name`. Existing runtime construction
   already calls `effective_declaration_from_documents` before C6, whose
   `documents_to_vertex` requires `payload["name"]`. Nameless manually malformed
   history already failed runtime construction; C6 also refuses to infer a
   historical role from it. Preparation may consequently refuse an attempted
   repair of that malformed history. No old-canonical serializer defect was found.
4. **Pre-genesis overlays — conservative distinction retained.** The existing
   snapshot resolver folds self-scoped overlays before genesis despite its
   documented later-row rule (`engine/declaration.py:258-275`, `:353-360`). C6
   cannot let such a row license historical tick membership. It separately
   receives the resolver-selected target, and refuses consumed roles that only
   that early row could establish. Aligning C6 to the broader fold would weaken
   evidence; changing reads here would broaden the slice. Record a future
   resolver hardening/migration audit, preserving existing read semantics now.
5. **Repeated reconstruction / copy cost — accepted limitation.** Collector and
   analyzer reconstruct revisions separately, and the analyzer checks each
   relevant tick across its subsequent revisions. This is bounded to captured
   H but is not incremental history evaluation. The implementation report
   makes no performance claim; optimization can share captured reconstruction
   without weakening receipt ordering or omitting intermediate revisions.
6. **Negative timestamp hydration — documented policy, no change.** Continuity
   examines the complete timestamp range. Hydration/pending retain the existing
   nonnegative selection. A historical edge can therefore be safety-relevant
   without being the hydrated edge. C6 deliberately does not widen hydration
   semantics; tests exercise negative-time retirement refusal.

The pre-review suites passed engine 2,597 / 1 skipped, SDK 545, architecture 101,
with matching before/after production/test hashes. Scoped lint passed; broad
compiler lint reproduces 57 baseline findings. The sole post-review source-tree change is the additional SDK test:
`libs/sdk/tests/test_arrival_boundary_continuity.py`, SHA-256
`d7eca43eb2a52045e2684bb0d64a65d28335691fb3ff6088a48911ddf13eaee3`.
Its separate patch/evidence and final source comparison are retained here.
No production change followed review; another external review is unnecessary
for this added positive acceptance case. No review or validation jobs remain. Closeout evidence is retained, and
`final-source-check.json` confirms all reviewed production bytes are unchanged.
