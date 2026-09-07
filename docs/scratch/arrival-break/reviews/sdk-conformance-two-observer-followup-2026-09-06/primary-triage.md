# Primary triage: corrected two-observer conformance

Fable 5.1 LOW: **ACCEPT**. Primary: **ACCEPT**. No remaining blockers.
Packet SHA-256: `f717b118ec76c00e3f0a216cb8b341ddc5439a2d69236cdab6dbc182992c6fdd`.

The initial review's wrong-namespace false positive is closed. The test proves
that the alternative binding resolves and carries a distinct public key, then
checks the write-time refusal's exact authorization reason, complete request,
key reference, public key, captured head and successor position. Root's probe
allows preflight resolution and fails the write-time resolver: the corrected
test rejects it. This separates captured authorization from provider readiness.

Accepted writes also explicitly advance ordinal within one lineage. The report
states the case-distinct label's admission boundary separately from its direct
public binding resolution. No production change was needed.

Native evidence: full SDK **579 passed** and architecture **101 passed** before
the assertion-only correction; final focused mapped/workload suite **13 passed**
and Ruff passed afterward. Root's false-positive and corrected probe results
are archived with this review. The reviewer performed static analysis of this
evidence and did not independently execute tests.

All frozen sources matched at primary closure before status/report edits.
The final workload SHA-256 remains
`241f73336fe57b2047d549e2cddcfcfbf6bb489a060e2c58becdbb3dfd46869e`.
The README also matches the reviewed source. No post-review implementation or
test changes were made.

Optional notes: the explicit reason/request assertions already make the
session authorization intent clear, so no extra causal-chain comment is
required. Update the maintained report and orchestration status to accepted;
preserve the original frozen packets and initial REVISE verdict.

This closes the first workload-conformance slice, not C9 retirement. Next is
declaration interruption/recovery, then partial source tiers and captured
export/restore/sync/read, followed by the remaining roadmap work.
