# D0/D2 final review — primary triage

**ACCEPT. No remaining correctness blockers in this slice.** Fable-low reviewed
packet `f5ed9983fcf7f4f733dc4fde403419d62da4943ff007dc6caf6c2dcc7ee8bb85`;
the runner recorded no source drift. Root checked the completed-slot control
flow and the retained current-source probe before accepting the disposition.

The completed slot now checks its own retained intent independently of the
incoming token. Original-token create, original-token recover, and fresh-token
create all refuse a substituted valid key that contradicts that intent. With
the original index absent, the contradiction refuses before index restoration.
The earlier pending-before-index interruption and token reservation fixes remain
covered. The final custody suite passed 76 tests; its focused provider/recovery
run passed 26. Root's standalone probe also refuses all three invocation forms.

This acceptance closes the two root findings after the first implementation
review and the fresh-token finding from the focused recovery review. Their raw
verdicts and historical primary dispositions are preserved. The initial raw
implementation ACCEPT alone was insufficient evidence of recovery correctness.

Optional follow-ups are not blockers: stronger independent local public-key
pinning; absence of a retained pending marker; narrower refusal matching in one
regression; and fingerprint fixtures that assume the mutation lock already
exists. The provider's local files are not an authenticated external witness.
Arrival signing independently checks captured lineage history. No rotation,
revocation, automatic cleanup, or local tamper-proof storage is claimed.

The final full SDK run (578 passed) precedes only the final custody completed-slot
fix, covered by the final custody run. Engine (2,611 passed, 1 skipped), sign
(40 passed), and architecture (101 passed) production did not change. Final
scoped Ruff passed. No production or test files changed after the final review;
subsequent edits only close out documentation and evidence. No commit or push.
