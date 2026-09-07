# D0/D2 final completed-slot review handoff

The [focused recovery review](reviews/consistency-d0-d2-recovery-2026-09-06/recovery-findings.md)
confirmed the original two fixes and found one remaining fresh-token bypass.
Its [primary triage](reviews/consistency-d0-d2-recovery-2026-09-06/primary-triage.md)
accepted that finding.

The completed branch now reads the slot's own retained pending marker,
independently of the incoming token. If present, its binding/ref/provenance,
original index, and completion evidence are checked before any return. A fresh
token is not permission to forget an earlier operation's evidence. The fix
also checks the missing-original-index plus substituted-slot combination.
Fresh-token inspection does not restore the original missing metadata.

Terra's isolated full custody suite passed **76 tests**; its focused provider/
recovery run passed **26 tests**. Root's standalone current-source probe now
refuses under original-token create, original-token recover, and fresh-token
create. Root's independent regression uses all three calls. The first two
probe failures remain fixed, and no engine/SDK production changed in this last
narrow custody patch.

The last full SDK run (**578 passed / 22.17s**) predates only this final
completed-slot fix; final custody tests cover the altered branch. Engine
(**2,611 passed, 1 skipped**), sign (**40 passed**), and architecture (**101
passed**) production remain unchanged. Scoped Ruff and diff checks pass.

All current-source tests and probes used isolated XDG state/config and
LOOPS_HOME. No real key, live store, commit, or push occurred. This final
focused review must still be triaged before the overall work is complete.
