# D0/D2 imported-key durability final follow-up

The directory durability review returned REVISE for one remaining branch:
non-created provenance recovery skipped key-directory fsync when both copied
key files were already visible. Root accepted the finding in
[primary triage](reviews/consistency-d0-d2-durability-2026-09-06/primary-triage.md).

The branch now unconditionally fsyncs the key directory after reloading a
complete pair and checking expected public material, before binding publication.
It neither needs nor reopens the original legacy source at this stage. Existing-
reference recovery retains missing-public refusal; created-key recovery already
syncs its validated directory. Read-only resolution remains unchanged.

The new regression performs a real temporary legacy import, interrupts its
second key-directory sync (after the public link is visible), moves the original
legacy key directory away, then recovers from the retained candidate. Recovery
syncs that directory and publishes one binding. It checks sync behavior, not
literal power loss. All credentials and stores are isolated temporary fixtures.

Focused `test_binding.py`: **18 passed**. Final full custody: **81 passed / 0.55s**,
raw `custody-durability-followup.txt`. Scoped Ruff and diff checks pass. The only
code/test changes since the prior review are this branch and its regression.
Engine (2,611 passed, 1 skipped), SDK (578 passed), sign (40 passed), architecture
(101 passed) production remains unchanged from its measured runs. The SDK run
precedes the final custody recovery/durability fixes, covered by final custody.

Frozen for final Fable-low review and primary triage. No commit or push.
