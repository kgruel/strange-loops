# sdk-declaration — Fable review

Effort: low. Finished: 2026-09-06T02:44:37.912654+00:00.
Packet SHA-256: `cdfc9bafa32bcb67a7ce78ee4048924e09ad1135a62c082029fde3bba64d5b50`.

Static reviewer output; findings still require primary triage.

**Blocking: one.** Finding 1 breaks the SDK recovery entry point. The engine coordinator itself looks sound for this stage; the rest are non-blocking.

**1. High — `sdk.recover_declaration` raises `AttributeError` on every successful recovery**
Location: `libs/sdk/src/sdk/declare.py`, `recover_declaration` → `_arrival_result(result, result)`, which executes `asdict(plan.basis)`.
Trigger: any call to `recover_declaration` (or `recover_ceremony` on a v1 declaration intent) where the engine returns `recovered` or `not-applied`. The engine `DeclarationEditResult` has no `basis` field, and unlike `changes` the access is unguarded.
Consequence: the engine has already finished publication and removed the intent, then the SDK crashes with an untyped `AttributeError` instead of returning the v2 result. `recover_ceremony` only catches `OSError/ValueError/KeyError`, so the error propagates raw. No test covers the SDK recovery surface, only the engine function, so the local pass counts do not exercise this path. Engine failures inside recovery still normalize correctly; only the success path is broken.

**2. Medium — a provably not-applied intent whose head has moved is left in place and locks out all future edits**
Location: `arrival_declarations.py`, `_recover_declaration_edit`, the suffix loop after `actual != captured`.
Trigger: apply reaches `append-unknown` or the "before entering the append call" refusal without appending, then any other writer (e.g. an ordinary `emit_fact`) appends at `captured.ordinal + 1`. Recovery finds a non-matching record at `first`, raises `DeclarationStale("does not occupy its exact expected suffix")`, and retains the intent.
Consequence: under full-head CAS, a foreign record at `first` proves the planned append never landed, so the intent could be cleared exactly as the `actual == captured` branch does. Instead every subsequent `apply_declaration_edit` fails with "unfinished declaration intent already exists" until an operator deletes the sidecar by hand. The design's `not-applied` versus `conflict` distinction collapses into one stale refusal, the `conflict` result status and `DeclarationNotApplied` exception are never produced, and the SDK reports outcome `refused` with no guidance. Behavior is safe (nothing is overwritten), but the recovery contract stated in the design is not met.

**3. Low — pre-append refusals that retain the intent do not report the intent path through the SDK**
Location: `arrival_declarations.py`, the two `DeclarationApplyError` raises in `_apply_declaration_edit` ("intent was durable but append did not start", "before entering the append call"); `sdk/errors.py` `_identity_details`.
Trigger: `registry.open` fails or the after-intent hook raises after the sidecar is durable.
Consequence: the exception is a bare `DeclarationApplyError` with no `intent_path`/`captured_head` attributes, so the normalized `ArrivalRefusal` carries no evidence that a sidecar now exists. The caller's next edit fails on the intent gate with no prior hint. Adding the attributes (as `DeclarationOutcomeUnknown` does) would fix it without protocol change.

**4. Low — `ProjectionBehind` is downgraded to a preparation refusal**
Location: `prepare_declaration_edit`, the broad `except Exception` after the `ProjectionBehind` raise.
Trigger: CURRENT snapshot `represented.ordinal < captured_head.ordinal`.
Consequence: the typed contract error is wrapped as `DeclarationPreparationRefused("cannot establish declaration preparation basis: ...")`, so callers cannot distinguish "run `sync_projection` and retry" from a genuine refusal. Also note the following `<=` branch is always taken after the `<` guard, so `projected_through` is always re-read via `head_at`; harmless, but the condition is dead.

**5. Low — `kind.py` cache-basis bytes go through newline translation**
Location: `sdk/kind.py` mutation entry points pass `source_cache_bytes=current_text.encode("utf-8")` where `current_text` came from `read_text()`; the engine compares against `read_bytes()`.
Trigger: a `.vertex` cache containing `\r\n` (or a lone `\r`).
Consequence: `read_text` normalizes newlines, so the encoded bytes never equal the raw cache and preparation refuses with "declaration cache changed while preparing the requested splice" on an unchanged file. Safe, but the splice path is unusable for such files and the message misattributes the cause. Reading bytes once and decoding explicitly resolves it.

**Deferred/out of scope, not counted as bugs:** legacy cutover arms in `kind.py` and `inspect_declaration`, empty-receiver import, and restore-forward. Ordinary opens still route through the attested `Compared` comparison in `prepare_declaration_edit` and full-head CAS in apply, so rollback checks are retained as required.

**Not verified independently:** the assumptions that `ContractRefusal` is strictly pre-mutation, that `keys_valid_at(observer, head.ordinal + 1)` semantics match the verifier used at replay, and that non-file adapters return record bodies structurally equal to JSON round-tripped drafts in `_record_matches_draft`. Those are contract properties of files outside this snapshot.
