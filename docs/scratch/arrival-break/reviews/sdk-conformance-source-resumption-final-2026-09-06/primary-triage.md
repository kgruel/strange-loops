# Primary triage: partial source failure and fresh invocation

Fable 5.1 LOW: **ACCEPT**. Primary: **ACCEPT**. No blockers.
Packet SHA-256:
`8a3fd0e1146360eaa2c085ccab15b285bffcc896c00d40e1518d77ba4b4d19e2`.
The substantive reviewer model was verified as `claude-fable-5-1`; the CLI
also reported a 15-output-token Haiku helper, not a substitute review.

The public workflow demonstrates durable error evidence in both before-yield
and after-yield cases, exact receipt-order fact identities, returned/persisted
body agreement, unchanged earlier rows, and a fresh cadence invocation using
a reconstructed mapped provider. The persisted upstream success drives its
skip, while its trigger and the absence of downstream success qualify only
the downstream source. A repeated logical observation gets a new fact ID.
No automatic resume, deduplication or external exactly-once behavior is claimed.

The optional findings do not require source changes:

- The failed-observation lookup is intentionally empty when that collector
  yielded nothing. Both cases inspect the failed lifecycle in the complete
  public fact page and exercise a successful `read_fact_by_id` after retry.
  A separate lifecycle lookup would duplicate that evidence for this scope.
- No ticks or dispatch intents occur in the fixture. Pinning `dispatch_status`
  to `none` would add a field-level assertion; dispatch status behavior has
  separate SDK source tests and is not this workflow's continuation claim.
- Agent roles belong to the scratch report; the SDK README does not contain
  orchestration details.

One reviewer phrase is stronger than the executable evidence: the clock wrapper
supplies 12/22, but the test explicitly pins the persisted upstream timestamp
to 12 through its cadence evidence. It does not separately assert the second
lifecycle's timestamp is 22. This does not weaken the demonstrated skip/retry
decision, which is evaluated at 20 against the persisted upstream timestamp.
Full verification remains limited to grammar, density, lineage and hash chain;
the test compares public projection/custody coordinates separately and does
not claim signature verification or a general projected-row audit.

Native validation: final focused SDK **28 passed** /0.99s, full SDK
**582 passed** /23.30s, architecture **101 passed** /6.79s, engine source and
coordinator regressions **30 passed** /0.78s. Scoped Ruff and maintained-file
whitespace checks pass. Test processes isolate XDG state/config and `LOOPS_HOME`;
only explicit logs and hashes are archived, not fixture stores or credentials.
The README was narrowed during broad validation; executable source was stable.

All packet sources match at closure before maintained status/handoff updates.
Final executable SHA-256:
`ac1513bd080f907e3f7722602f9a520475f9e315b9612abe152048363f27f48e`.
No production code changed. No post-review test or SDK-guidance edits, pending
jobs, commit or push. This slice is ready to checkpoint. Captured-prefix export,
restore-forward, verification, explicit synchronization and read are next;
C9 transition/retirement remains separate.
