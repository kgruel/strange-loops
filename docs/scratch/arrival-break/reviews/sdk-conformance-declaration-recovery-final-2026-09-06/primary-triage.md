# Primary triage: declaration recovery conformance

Fable 5.1 LOW: **ACCEPT**. Primary: **ACCEPT**, no blockers.
Packet SHA-256: `c35bacd0203dbd495359d6fe5f4e46010c6d0dc77b390306567578b64001b2a8`.

The deterministic public workflow correctly distinguishes committed custody
from projection/cache readiness. Recovery preserves the original basis and
head without signing or another append; fresh inspection and the subsequent
mapped write establish the new declaration's usable state. Full verification
claims remain bounded, and fixtures use isolated temporary roots.

Root elected to incorporate the four optional assertion improvements before
final closure: exact hook firing, one-record ordinal advancement, the complete
projected fact-ID list, and the no-op result head. The proposed OSError-type
check alone would also match an incidental filesystem OSError; explicit hook
firing is stronger for this fixture. The projection-list assertion is useful
because existing head equality proves no custody duplication while the list
also catches unexpected query rows with fresh IDs.

Reviewer wording that the poison catches provider construction is too broad:
the guards intercept mapped resolution and legacy `for_write`, not constructors
or every possible private key access. Maintained documentation makes the
narrower claim. No production credential or recovery change is required.

Full SDK 580/21.79s and architecture 101/6.20s passed on the reviewed test;
focused 49/1.13s and Ruff passed. Review was static, not independent execution.
All sources matched at review launch. The post-review source check raced the
optional test refinement: production, guidance and logs still match, while the
test has the documented optional changes. Final focused validation is 49/1.28s
and Ruff passes; a separate follow-up review covers the refined test.

Optional refinements are complete. Final focused Fable-low and primary
verdicts are **ACCEPT**; see the [follow-up closure](../sdk-conformance-declaration-recovery-followup-2026-09-06/primary-triage.md). No jobs or blockers remain.
