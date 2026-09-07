# final — Fable review

Effort: low. Finished: 2026-09-07T01:01:38.837664+00:00.
Packet SHA-256: `c35bacd0203dbd495359d6fe5f4e46010c6d0dc77b390306567578b64001b2a8`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT.** No blockers. The executable assertions match the engine paths they claim to cover, and the README/scratch claims stay inside what the test demonstrates.

**What holds up under static trace**

- **Interruption site is real.** The hook fires at `arrival_declarations.py:1348`, after the intent phase is durably recorded as `appended` and before `sync_projection`. The resulting `DeclarationCommittedIncomplete` carries phase, head, commit, intent path and fact IDs, all of which `errors.py:_identity_details` serializes. The test's before/after/head/intent assertions (lines 147-159) are causally tied to that site, not to a generic failure.
- **Durable commit vs projection lag is separated.** Verified head advances to the durable head (line 161) while the cache bytes are unchanged (line 160), inspection refuses with `ProjectionBehind` (line 163), and the second edit refuses in `prepare` with custody `not-entered` and a `ProjectionBehind` cause (lines 176-184). That matches `_preparation_refused` and the `except Exception` arm at `arrival_declarations.py:1041`.
- **No duplicate append.** The head is unchanged across recovery and the noop re-edit (lines 209, 215, 267), and the continued write's commit predecessor equals the durable head (lines 287-288). Since drafts never re-sign or re-append in `_recover_declaration_edit`, this is the correct custody-level proof.
- **Original basis vs fresh basis is truthful.** `recovered.basis == baseline_basis` (line 211) pins the pre-edit basis. That only works because line 118 establishes nothing was appended between inspection and edit. The fresh basis is then separately obtained from inspection (lines 247-249), matching the README wording.
- **Credential-free recovery.** `recover_declaration` accepts no credentials, and the poisoned `resolve`/`for_write` guard would fail loudly if a default provider were constructed. Subsequent authorized write uses a reconstructed provider. Fine.
- **Isolation.** XDG state/config and `LOOPS_HOME` are redirected, custody root and store live under `tmp_path`, and the lock/intent sidecars sit beside the vertex in `tmp_path`.
- **Docs.** README lines 251-275 and the scratch doc claim only the deterministic `after-append` hook path, no commit on recovery, original basis, and the bounded `Full` exclusions. Consistent with the code.

**Optional findings (non-blocking)**

1. **Causal specificity of the interruption.** `phase == "appended"` is also produced if `_replace_json` at line 1346 fails for an incidental reason. Add one line to pin the cause to the injected exception:
   ```python
   assert failure.details["evidence"]["cause"]["type"] == "OSError"
   ```
2. **Exact append record count.** Line 155 only asserts `>`. The declaration envelope is one Arrival record with no key introductions here, so `== before_edit.ordinal + 1` is a tighter identity claim.
3. **Projection-level duplication.** Line 231 counts `note` declaration facts only within `recovered_rows`, so a projection that replayed the suffix under fresh IDs would not be caught by that assertion (the head checks catch custody duplication, not projection duplication). Filter over `recovered_internal.items` instead, or add `assert recovered_ids == baseline_ids + list(recovered.fact_ids)`.
4. `repeated.head` is not asserted; `== durable_head` would close the noop path.

Test logs are treated as native evidence only; I did not execute anything.
