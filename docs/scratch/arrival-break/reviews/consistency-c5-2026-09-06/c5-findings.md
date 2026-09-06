# c5 — Fable review

Effort: low. Finished: 2026-09-06T19:21:39.297024+00:00.
Packet SHA-256: `6c246406041901559d7d3a24aa61aaa464f3a3ab32a51da0b0cc5ae59ebd6c5d`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** No blockers or regressions found in the packet. Three optional improvements below. I did not execute any tests; the pass counts in the validation note are the owners' evidence, not mine.

**Coverage and ordering checked against the diff**

- Runtime construction validates the effective declaration (from bounded documents, not the locator) before source compilation, then the merged declared plus template specs after expansion, before materialization and hydration. The implicit `cite` case is handled by the hardcoded name check. Ordinary and batch planners re-check the detached candidate's registered kinds, which include the materialized `cite` loop.
- Proposed declaration edits validate right after grammar/semantic validation and before residence checks or registry open. The custody test asserts zero activity and custody not entered.
- Initialization validates in the preflight before intent or mint. Recovery paths are untouched, matching the stated intent semantics.
- SDK init checks name against the scaffolded `item` loop and implicit `cite` before key creation. Legacy sqlite init is unchanged and tested.
- Evidence reads, inspection, export, and `read_state` are not routed through the validator. The SDK tests for an ambiguous history with a raw tick confirm this.
- Effective history wins over a locally rewritten cache. The repair path is exercised end to end in the SDK append-forward test with a real commit.
- Exact-label comparison is tested with the case-distinct `X` case.

**Optional improvements**

1. **Refusal family mismatch in the SDK kind preview.** Severity: low. Source: `libs/sdk/src/sdk/kind.py:123-125`. Trigger: `plan_kind_mutation(target, "add", "<vertex name>")` without credentials. Consequence: the preview surfaces `RuntimeWriteRefused` for a declaration-shaped operation, while the signed execution of the same edit surfaces `DeclarationPreparationRefused` from `prepare_declaration_edit`. Same condition, two families, and the preview module now imports the runtime-write module only for the exception class. The bounded policy says callers keep their operation-specific family. Correction: raise the declaration-preparation family here (or the SDK's own value error) and update the test expectation in `test_arrival_kind_preview_refuses_new_vertex_name_loop_collision` accordingly.

2. **Implicit-loop knowledge is duplicated.** Severity: low. Source: `libs/engine/src/engine/declaration.py:866` hardcodes `"cite"`; the authority is `materialize_vertex` at `compiler.py:1008`. Trigger: a future change to the implicit-loop set in the compiler. Consequence: the preflight validator (declaration prep, init, SDK init) silently drifts from the runtime; the post-expansion runtime check would still catch collisions, but preflight would no longer refuse before custody. Correction: expose the implicit loop names as a module constant next to `materialize_vertex` and have the validator union that constant into `loop_names`.

3. **Engine repair test proves only that the gate is reached.** Severity: low. Source: `test_arrival_declaration_custody.py:301-328`. Trigger: none at runtime; this is test strength. Consequence: the engine-level test stops at the "require signers" refusal, so it does not show the resulting plan tombstones the colliding loop. The SDK test `test_tick_free_collision_can_be_corrected_by_signed_append_forward` does cover the full path with a real commit, so the gap is engine-local. Correction: either leave as is and note the SDK test as the acceptance evidence, or extend the fixture ledger's `scan` to return a key registration so the plan can be built and `changes` inspected.

**Scope statements that hold**

The README and C5 note accurately describe what is and is not covered: no wire change, no key mapping, no rename, no history rewrite, no retroactive role assignment for recorded ambiguous ticks, and no template compilation solely for declaration validation. The D5/C6 continuity audit remains explicitly open.
