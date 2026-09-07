# durability-followup — Fable review

Effort: low. Finished: 2026-09-07T00:04:13.387749+00:00.
Packet SHA-256: `633243c0f5e61f2cf2eaea7793c4f4eb5cece9ca799d9ef3620143c098a42ca3`.

Static reviewer output; findings still require primary triage.

**ACCEPT.**

The final correction closes the blocker from my prior review, and I found no regressions in the surrounding paths.

**Ordering in the non-created recovery branch** (`libs/custody/src/custody/binding.py:977-1009`): load private and optional public, check expected public against the intent, handle a missing public file, reload with the public file required, then the new unconditional key-directory fsync, then binding publication. Validation strictly precedes the sync, and the sync strictly precedes the binding link. That is the order the triage asked for. The legacy source is not reopened anywhere in this branch.

**All provenance branches now sync a validated key directory before publication:**
- created: unconditional sync at the end of key creation, unchanged from the prior review.
- legacy-import, public missing: publish, sync, reload, sync again. The second sync is redundant but harmless.
- legacy-import, both files present: the previously missing case. Now synced at line 1006.
- existing-ref, public missing: still refuses with recovery-required, so no partial candidate is published.
- existing-ref, both present: synced at line 1006. The candidate was already validated against a completed binding at bind time, so re-syncing is correct and cheap.
- published-slot recovery: validates the slot, then syncs pending, bindings, and the key directory before restoring the token index. Unchanged.

**Read-only resolution is unchanged.** The resolve path and its helpers make no fsync, mkdir, or lock calls. The key loader used by both paths has no side effects.

**Prior corrections are preserved from the full current source:** missing-ancestor recursion and full lexical parent-chain fsync in the directory helper, symlink refusal via lstat on provider-owned paths, and the completed-slot retry that re-syncs bindings, key directory, pending, and intents after content validation. No wire or tamper-evidence changes were introduced.

**The regression test is a real interrupted import.** I traced the fsync counting in `libs/custody/tests/test_binding.py:411-422`. Parent-chain syncs from the directory helper target the keys directory or above, so they are not counted. The first counted key-directory sync follows the private-key link, and the second follows the public-key link. Interrupting the second leaves both files visible with the directory sync incomplete, which is exactly the failure shape. The error is an OSError, so the mutation wrapper converts it to an incomplete result with the expected phase. Moving the legacy keys directory before recovery proves the source is not reopened. Recovery syncs the retained candidate directory and publishes one binding. This checks sync ordering, not physical power loss, as the packet states.

**Optional notes, not blockers:**
- The regression asserts the key directory appears in the retry sync list but not that it precedes the bindings directory sync. Adding an index comparison would pin the ordering the code comment promises.
- The legacy-import missing-public branch performs two consecutive key-directory syncs. Dropping the inner one would be a small tidy-up with no durability change.
- The packet claims for engine, SDK, sign, and architecture runs are stated as unchanged from earlier measurements. I did not verify those and they are outside the scope of this correction.
