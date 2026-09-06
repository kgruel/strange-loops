# followup — Fable review

Effort: low. Finished: 2026-09-06T18:16:34.733193+00:00.
Packet SHA-256: `a7e5cb6256f2626ce9b14fec614963d2bcf9bd139559e8769b0466e0070a673a`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** The three accepted corrections are present in the packet source, the rejection of finding 1 holds against the full module, and I found no remaining concrete regression. One low, optional observation below.

## Verification of accepted fixes

**Finding 2 (context suppression) — fixed.** `arrival_declarations.py:98-101` sets `captured_head`/`projected_head` only when a concrete head is supplied, and `errors.py:151-156` emits null only when the attribute exists and is `None`. A pre-open refusal therefore has no key, and `normalize_exception` (line 412) lets the caller's context supply it. Initialization's explicit `captured_head=None` (`arrival_initialization.py:84`) still wins over context. Both branches are asserted in `test_preopen_declaration_context_keeps_actual_head_and_explicit_null_is_preserved`. The generic basis wrapper at line 944-948 passes `captured_head=None` when the failure precedes head capture, which correctly yields an absent attribute rather than a null. The `*args` constructor preserves inherited `Exception.args`; tested at `test_arrival_declaration_custody.py:271-278`.

**Finding 3 (unsupported scalars) — fixed.** `errors.py:107-111` omits a whitelisted identity attribute when `_json_value` returns `None` for a non-`None` input; `errors.py:415` applies the same rule to context. No `str`/`repr` is executed; the payload trap test asserts `first["details"] == {}` for an `observer` value object. The triage's claim that no enum-valued whitelisted attribute exists in the engine cannot be verified from this packet, but nothing in the supplied modules contradicts it.

**Finding 4 (contradictory pairs) — fixed.** `errors.py:227-230` drops both `not-entered/≠not-attempted` and `entered/not-attempted`; the parametrized cycle test covers both directions.

## Rejection of finding 1

Sound. With the full module in hand, every `_preparation_refused` call edge is inside preparation:

- `_descriptor_location` (635) has one caller, `_validate_residence` (673); `_validate_residence` has one caller, `prepare_declaration_edit` (839).
- `_signed_with_existing_key` is called at 745 (`_declaration_row`), 779 (`_key_draft`) and 1002 (prepare directly). `_declaration_row` and `_key_draft` are called only at 985 and 1041, both inside prepare.
- The lambdas at 902-903 are passed to `complete_projection_custody` from prepare only.
- `_apply_declaration_edit` (1136-1273) and `_recover_declaration_edit` (1290-1398) call none of these; recovery rebuilds via `_plan_from_intent` (550-632), which raises only `DeclarationApplyError`/`DeclarationStale`.

The factory's proof is therefore coordinator-scoped in fact, not merely by convention. My original concern rested on a hypothetical caller that does not exist. No framework change is warranted.

## Remaining observation

**1. Low (existing, optional): established captured head is dropped by in-basis refusals other than "behind".**
Source: `arrival_declarations.py:855-935` and `902-903`, re-raised bare at 941-942. Once `captured_head` is assigned at line 869, refusals such as "no historized declaration", "no matching lineage basis", cache-basis mismatch, or the custody lineage/conflict lambdas raise via `_preparation_refused(message)` without passing `captured_head`. Only the `ProjectionBehind` path and the generic `Exception` wrapper attach heads. Scenario: custody substitution case refuses; the engine-level refusal carries `prepare` and custody proof but no captured head, and the SDK fills `captured_head` from the caller's own read basis, which is a different open. The implementation note's wording ("where established") is accurate for the behind path, so this is not a correctness bug. Minimal correction, if wanted: pass `captured_head=captured_head` in those calls and in the two lambdas. No test or doc change is required to accept this slice.

## Not verified

I did not execute tests. The reported final runs (engine 2,550/1 skipped, SDK 525, architecture 101) and Ruff results are taken from the validation note as stated by its authors; the packet source is consistent with the tests it shows.

**Accept.**
