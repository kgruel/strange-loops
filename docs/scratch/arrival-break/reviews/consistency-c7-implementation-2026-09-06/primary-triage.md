# C7 Fable-low review: primary triage

Fable 5.1 returned **ACCEPT**, no blockers, for the frozen implementation packet
SHA-256 `0c52a207c76f9d4ecc6ab5479104a90fee991636eeafb3afa0924ab9d78c4c8f`.
The one-shot CLI completed at 2026-09-06 22:26:02 UTC, exit 0, low effort.
The substantive reviewer model was `claude-fable-5-1`; the CLI also used a
15-token Haiku helper. Launch-time source drift was empty.

Root accepts the review after checking its four optional notes:

1. **Topology drift assertion — addressed.** The independent opaque-root test
   now asserts `local_status == "drifted"` and differing semantic fingerprints
   in both topology disagreement directions. Those fixtures differ only in
   discovery topology, so this directly checks the reviewer's concern. The
   assertions were added after the frozen review; Fable did not see them.
   Focused validation: `5 passed in 0.21s`; scoped Ruff passes. Production is
   unchanged, so another external review/full suite is unnecessary.
2. **Older aggregate-read resolver reparses — recorded follow-up.**
   `_aggregate_aware_arrival_descriptor` in `sdk/read.py` still catches the
   single-store refusal and parses again. Replacing that bridge with the new
   explicit opt-in is a bounded future simplification for summary/state/timeline,
   with replacement-during-resolution tests. It is pre-existing and outside
   C7's declaration-inspection path. No change to those readers is claimed.
3. **Client handling of local-frozen — documented integration obligation.**
   Storeless results already allow absent store fields; the new read-path and
   local-only statuses are explicit in the DTO docstring and C7 contract.
   Repository search found no `inspect_declaration`/`DeclarationInspectionResult`
   consumer under `apps/`. SDK tests cover storeless serialization. The later
   C9 minimal/rich client transition should retain this distinction; external
   client compatibility was not tested.
4. **Plain storeless stays legacy — intentional.** C7's local-frozen branch
   requires aggregate shape and no store. Plain storeless and legacy stored
   inspection remain compatibility paths, as selected in the contract.

All optional notes are addressed or explicitly scoped follow-ups. No C7
implementation or review blocker remains. The early test-state isolation
mistake is separately disclosed in the validation report and preserved
validation evidence; it is not hidden by the external acceptance.
