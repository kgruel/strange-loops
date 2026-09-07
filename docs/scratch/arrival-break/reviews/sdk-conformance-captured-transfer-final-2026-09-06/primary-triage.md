# Primary triage: captured export and restore-forward

Fable 5.1 LOW: **ACCEPT**. Primary: **ACCEPT**. No blockers.
Packet SHA-256:
`2d626f36e4197e2a0ce22bc866b6cb157d4ea85574c15a8cb295e685b37e6ecd`.
The substantive reviewer model was verified as `claude-fable-5-1` (3,051 output
tokens; 1,982 thinking tokens reported). The CLI also reported a 17-output-token
Haiku helper, not a substitute reviewer. No launch source drift occurred.

The public workflow separates selected export identity from the newer captured
source head, and proves exact historical bytes against a retained pre-advance
source snapshot. A below-witness selection refuses before receiver append;
a fresh live-source restore appends through the witnessed head, preserving
exact receiver prefix bytes and its replica descriptor. Verification retains
its structural-only claims. A CURRENT read refuses while the projection is
behind, then explicit sync reports the old projection as its before-head and
catches it up. Complete public internal/domain rows match both stores and
retain prior declaration rows. Repeating restoration returns no Commit and
leaves receiver bytes unchanged.

Optional findings do not require source changes:

- Keep the explicit `startswith` assertion: it states prior-prefix retention
  directly alongside exact source/receiver equality, even where other fixture
  facts help establish the same conclusion.
- A separate `restored.source_store.role == "authority"` assertion would test
  an additional result field. The workflow already establishes the initialized
  authority and explicitly checks the receiver role/unchanged descriptor; its
  role-preservation claim concerns the receiver. No source-role mutation is
  exercised or claimed here.
- The reviewer did not run tests. Native logs are separate, previously executed
  evidence; this review was static and had tools disabled.

The sync before-head proves that preceding restore, verification and refused
read did not catch the projection up. It does not prove that no byte anywhere
in derived state was touched. Existing engine restore projection audits and
fault tests supply complementary coverage. This deterministic sequence is not
concurrent writer, crash, empty-receiver import or witness-reset coverage.

Final native validation: focused SDK **16 passed** /0.49s; full SDK
**583 passed** /20.96s; architecture **101 passed** /5.67s; engine transfer and
restore **55 passed** /0.38s. Scoped Ruff and maintained-file whitespace pass.
Test processes isolate XDG state/config and LOOPS_HOME; only explicit logs and
hashes are archived, not fixture stores or credentials.

All frozen packet sources matched at closure before maintained status/handoff
updates. Test SHA-256:
`5103a21f0bf0cabb65b3e3a3b3d95426619ec8f0f1022b6958f205fd58746d83`.
SDK README SHA-256:
`6a4dbbd92dfcc8c4d57a79867051fd0c121a4763f1658ca9f0699c51d2623bbe`.
No production code changed, no test/guidance edits followed review, and no
review jobs remain. Ready to checkpoint; nothing committed or pushed here.
C9 transition inventory and first CLI slice selection are next, with larger
maintenance/transfer/adoption work separate.
