# c2 — Fable review

Effort: low. Finished: 2026-09-06T18:09:38.066226+00:00.
Packet SHA-256: `2975dce5a9b22a68c027e5d75f63e2d27ff01743932b6346cfd29a108d45f697`.

Static reviewer output; findings still require primary triage.

**Verdict: needs correction** (two medium items, both introduced by this slice; the core routing/serializer work is sound).

## Findings

**1. Medium (introduced): preparation proof lives in a shared factory, not at coordinator raise sites.**
Source: `arrival_declarations.py:102-116`, used by `_descriptor_location`, `_validate_residence`, `_signed_with_existing_key`. These helpers are generic validators; the packet shows `_plan_from_intent` (recovery from a persisted intent) immediately above them and does not show whether recovery calls them. If any of these helpers is reached from an apply/recovery path, a refusal there would carry `custody={not-entered, not-attempted}` after an append may already have happened. Scenario: recovery re-validates residence of an intent whose append already committed, residence check fails, SDK reports a "no custody append" refusal. The implementation note says call sites were "checked", but the proof is still attached at the factory, which is exactly the constructor-default pattern the brief rules out. Correction: call `_preparation_refused` only from within `prepare_declaration_edit` (pass the proof from the coordinator into the helpers, or have helpers raise plain `DeclarationPreparationRefused` and let the coordinator re-raise with proof). At minimum add a test asserting recovery-path refusals carry no custody proof.

**2. Medium (introduced): constructor-default `captured_head=None` is emitted as an explicit null and blocks caller context.**
Source: `errors.py:149-154` plus `arrival_declarations.py:92`. Every `DeclarationPreparationRefused` now has `captured_head`/`projected_head` attributes defaulting to `None`, so `_identity_details` writes `captured_head: null` and `projected_head: null` for all preparation refusals, including pre-open ones like empty text. Then `normalize_exception` (line 408) skips any context field already present in `details`, so a caller-supplied `context={"captured_head": head}` is discarded for these refusals. Before this change the key was absent and context applied. This also weakens the doc's own claim that null means "explicitly unavailable" rather than "not supplied". Correction: either let context override an explicit `None` (`if details.get(name) is not None or name not in context_fields: continue`), or emit `None` only for wrappers that actually sought the head (the generic basis wrapper passes it explicitly; the factory default should not). Add a test: pre-open refusal plus context captured_head yields the caller's head.

**3. Low (introduced): `_json_value` now nulls unsupported scalars but keeps the key.**
Source: `errors.py:58-64`, `107-109`. Previously non-primitive coordinates were stringified; now they become `None` while the key is retained (test asserts `{"observer": None}`). Two effects: any whitelisted attribute that is an enum or small value object today (`kind`, `vertex`, `tick_id`, `observer` on some engine exceptions) silently flips from a string to `null` in the v1 details, and a reader cannot distinguish "explicitly unavailable" from "unsupported type". Correction: grep engine exception attributes in the whitelist for enum/object values before merging; and either omit the key when the helper returns `None` for a non-`None` input, or accept `Enum.value` in the helper. The intent to avoid `str`/`repr` is correct; the concern is only the silent shape change.

**4. Low (existing limitation, worth one line): serializer accepts `attempt=entered` with `state=not-attempted`.**
Source: `errors.py:221-229`. The invariant check only rejects `not-entered` paired with a non-`not-attempted` state. The reverse pairing is contradictory but passes through. No current producer emits it. Correction: also drop effects where `attempt == "entered"` and `state == "not-attempted"`, with a one-line test.

## What checks out

- `sync_target` now routes through the same `BaseException` catch-and-normalize as search; non-`Exception` returns unchanged, so cancellation identity holds. `ProjectionSyncError` removed from the generic refusal tuple.
- Projection wrapper starts at `catch_up` and claims only `entered/unknown`; `observed_after=None` remains uncertainty. Search flips `build_entered` immediately before `build`; snapshot open, `snapshot.close()`, provider acquisition and initial `coverage()` all report `not-entered/not-attempted`; post-build coverage mismatch reports `entered/unknown`.
- Cause serializer: `.cause` before `__cause__`, two nodes, id-based cycle guard, 512 truncation marker, no `__context__`, no `repr`. Tests cover each bound and the payload trap.
- `NotWitnessed` mint keeps head with no fabricated commit; legacy wrappers without proof omit phase/effects. Legacy `details.phase` stays separate from `evidence.phase`.
- File-backed SDK tests are the strongest part: they verify real index mutation before the injected refusal, unchanged ledger head, and no `commit` key.
- Evidence attaches a `cause` node to any normalized error with a cause (e.g. `WriteCommitUnknown`); that is additive and matches the implementation note, not a scope creep.

## Test gaps to close alongside the corrections

- Recovery/apply-path refusal carries no custody proof (finding 1).
- Context `captured_head` survives a pre-open preparation refusal (finding 2).
- Note the validation doc: full package runs predate the constructor patch; rerun the SDK suite after fixing 2, since `test_errors.py` equality assertions on `details` are the likely place a null-key change surfaces.
