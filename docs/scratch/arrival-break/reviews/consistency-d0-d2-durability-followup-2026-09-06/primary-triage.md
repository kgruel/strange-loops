# D0/D2 final durability follow-up — primary triage

**ACCEPT. D0/D2 is complete as an opt-in implementation, uncommitted.**
Fable-low accepted frozen packet
`633243c0f5e61f2cf2eaea7793c4f4eb5cece9ca799d9ef3620143c098a42ca3`.
The runner and root's post-review hash check found no source drift.

Root checked the final non-created recovery branch and realistic interrupted-
import regression. Expected public material and the complete retained pair
are validated before unconditional key-directory fsync, which precedes binding
publication. Recovery does not reopen the original source. This closes the
accepted blocker from the preceding durability review. Created-key, existing-
reference, and published-binding paths preserve their validated sync ordering.
Read-only resolution remains free of fsync, directory creation, and locks.

Final full isolated custody: **81 passed / 0.55s**. Scoped Ruff and whitespace
checks pass. The raw log and final code hashes are retained in validation-evidence.
Engine **2,611 passed / 1 skipped**, SDK **578 passed**, signing **40 passed**,
and architecture **101 passed** retain their earlier measured results; their
production did not change during the narrow custody recovery/durability fixes.
The SDK run predates those final custody corrections, which the final custody
suite covers. Directory tests establish sync calls and ordering, not physical
power-loss simulation. No live keys or stores were migrated or used intentionally.

Optional notes are deferred: one stronger ordering assertion in the regression,
removing a redundant sync in the missing-public import branch, centralizing
existing-directory sync invariants, and reducing repeated ancestor fsync work.
They do not block the specified POSIX filesystem contract. Local tamper-proof
storage, rotation, revocation, cleanup, and automatic legacy migration remain
separate designs. No code/test changes follow this accepted freeze.

The initial broad implementation ACCEPT, its primary override, the focused
recovery REVISE/ACCEPT, and the durability REVISE/ACCEPT remain preserved as
historical findings. Completion reflects their corrected implementation and
this final accepted review, not retroactive approval of earlier code.
