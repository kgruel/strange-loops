# C5 Fable-low primary triage — September 6, 2026

Status: complete. Both Fable-low reviews accepted with no blockers. One optional
consistency improvement is implemented and validated; all notes are adjudicated.
No reviews or validation jobs remain.

## Initial review

Fable 5.1 at low effort reviewed packet SHA-256
`6c246406041901559d7d3a24aa61aaa464f3a3ab32a51da0b0cc5ae59ebd6c5d`
(175,673 bytes), finishing at `2026-09-06T19:21:39Z`. The tool-free CLI runner
verified substantive Fable output; a 13-token CLI Haiku helper was not the
reviewer. Source drift was empty at review start and initial primary triage.
Raw findings/model usage and the initial packet are preserved unchanged.

1. **Low: declaration preview refusal family. Accepted and fixed.** The SDK's
   semantic preview originally passed `RuntimeWriteRefused` to the shared
   validator, while signed preparation used `DeclarationPreparationRefused`.
   Both normalized to `ArrivalRefusal`, but their `source_type` values differed.
   Preview now uses `DeclarationPreparationRefused`, and its public regression
   expects that family. The constructor carries no automatic phase/effect
   proof, so using it in preview invents no preparation receipt or custody
   evidence. Only `sdk/kind.py` and its SDK test changed after the initial review.

2. **Low: duplicated implicit-loop knowledge. Optional, deferred.** `cite` is
   known to both materialization and the pure name validator. A future addition
   to the compiler's implicit loop set must update this policy and its tests;
   extracting a common low-level definition is a maintenance option. Importing
   the compiler into declaration validation solely for that constant would
   expand dependencies for a preflight predicate. No current implicit name is
   missed. A future implicit loop would be visible to the ordinary/batch
   candidate checks after materialization, so those planners would still refuse
   at write planning. The earlier spec check cannot see compiler-inserted loops;
   the later fallback does not establish refusal before custody opening or
   runtime hydration. The follow-up requested this distinction be made explicit.
   This maintenance boundary remains explicit rather than claiming automatic
   protection against future compiler changes.

3. **Low: engine repair test stops at signer requirements. Covered by SDK
   acceptance; no further test needed.** The engine test isolates acceptance
   of a collision-free proposed result against tick-free ambiguous history.
   The real file-backed SDK test
   `test_tick_free_collision_can_be_corrected_by_signed_append_forward`
   supplies actual domain signers, receives a Commit, checks the old byte prefix,
   confirms removal through inspection and successfully emits afterward. It is
   the end-to-end acceptance evidence; duplicating that in the engine fixture
   would add no missing contract coverage.

## Validation and limits

Initial final runs passed engine 2,562 / 1 skipped, SDK 540 and architecture
101, with scoped Ruff clean. Engine source/tests remain unchanged after that
run. After the two-file preview taxonomy correction, final SDK **540 passed**
in 22.70s, architecture **101 passed** in 7.05s and scoped SDK Ruff passed.
Production and test hashes match the final validation and accepted follow-up.

The current-name reservation does not retroactively determine an old ambiguous
tick's role. D5/C6 historical continuity remains explicit, and declaration or
initialization recovery retains reserved intent semantics. Fact-only folds and
raw evidence reads/export remain available. These scope statements were
accepted by the initial reviewer.

## Follow-up and final disposition

The focused follow-up **accepted**, finishing at `2026-09-06T19:25:47Z`.
Packet SHA-256:
`134669568db92c9551c664588a7e6baab46d267f548fac6280c36d632554d554`
(37,069 bytes). Source drift was empty at review start and final primary
triage. Substantive Fable output was verified; the CLI's 24-token Haiku helper
was auxiliary. The sole low documentation note is addressed by the explicit
future planner-fallback wording in item 2 above. No code change was requested.

One explanatory statement in the follow-up needs qualification: opening a
bounded read is not itself entry into custody append. In the C2 effect contract,
custody non-entry refers to the append boundary; attested opening can separately
update a witness. Signed preparation can therefore honestly carry custody
non-entry proof even after opening. Preview's use of the bare refusal constructor
still correctly claims no phase or effects, because that call site supplies no
explicit coordinator proof. No serializer or effect-policy change is needed.

Frozen packets and raw findings remain unchanged. `status.json` in each review
directory records the runner's historical awaiting-triage state;
`triage-status.json` is authoritative completion. `final-source-hashes.json`
records the final 14 production/test/README files; the initial snapshot is
preserved separately. Only completion documentation changes after acceptance.
C5 remains uncommitted on `arrival/finish`, based on C4 checkpoint `79696a72`.
Nothing pushed or applied to live stores.
