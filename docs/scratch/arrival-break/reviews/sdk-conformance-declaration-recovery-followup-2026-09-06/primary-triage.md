# Primary triage: final declaration recovery workflow

Fable 5.1 LOW: **ACCEPT**. Primary: **ACCEPT**. No remaining blockers.
Packet SHA-256: `0ad7ef2e13d27c80278255c66b8c923945e8ce23bf73e6a35d8a82f71b833a14`.

All four optional initial findings are closed: the fault hook is observed
explicitly, the one-kind/no-key edit advances exactly one Arrival envelope,
the recovered projected fact-ID list is exactly baseline plus retained edit
IDs, and the no-op result reports the reconciled head. These refine test
coverage without changing production behavior or public contracts.

The reviewer performed static analysis; native validation is full SDK
**580 passed** /21.79s and architecture **101 passed** /6.20s before only those
assertion refinements, followed by final focused **49 passed** /1.28s, scoped
Ruff and whitespace checks. All processes used isolated state/config/Loops
roots. The final executable SHA-256 is
`75260f0bdaad5a140f61bd04203934e33c7a63b0926ca87f28ae81515b8a4563`.
All follow-up sources and initial reviewed README/SDK sources match at closure,
before maintained status/handoff updates. No subsequent test/source edits.

Optional follow-up notes are resolved without further changes. The fixed
fixture has a small complete internal fact list below the explicit limit 20;
if fixture growth fills the page, the exact-list assertion fails loudly.
Unbounded pagination is outside this workflow and the public read signature
uses an integer limit. Restoring the original apply function before the no-op
is intentional isolation of the injected failure seam.

Poison guards cover mapped resolution and legacy credential acquisition;
they do not instrument every possible private file access or constructor.
The deterministic exception test does not claim process/power-loss survival.
Prefix verification does not supply signature or projection verification;
the workflow compares public projection and custody evidence separately.

This completes declaration interruption/recovery/inspection/continued writing.
Next is partial source-tier failure and safe resumption, then captured export,
restore-forward, verify, explicit sync and read. C9 retirement remains separate.
