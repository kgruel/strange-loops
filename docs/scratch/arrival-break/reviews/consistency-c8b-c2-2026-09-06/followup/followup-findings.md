# followup — Fable review

Effort: low. Finished: 2026-09-06T17:47:36.067675+00:00.
Packet SHA-256: `4d593b6904584073e9145256c2939776beb25df0202d83222ce558ff55fa3b4d`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** Prior findings are resolved as triaged; the corrections do not introduce regressions in the frozen packet.

**Resolution check**

- **C8b sibling control exception** (`arrival_sources.py:716-727`): settled non-step, non-cancel BaseExceptions now re-raise by identity with no `from`, so an existing `__cause__` survives. The regression test at `test_arrival_sources_c8b.py:452` asserts identity and explicit cause. Ordering is deterministic because neither fake stream suspends, so task A's bookkeeping failure completes before B's interrupt; if B won instead, the `except BaseException` branch at line 749 yields the same escaping exception.
- **Basis serialization**: `_safe_detail` checks the Head shape before the ReadBasis shape, and ReadBasis lacks `ordinal`/`record_hash`, so no misclassification. The SDK test asserts all four fields plus JSON round trip.
- **Envelope freeze**: frozen `_CollectionState` with a mutable `pairs` list is coherent; only the list is mutated.
- **C2 design**: `coordinator_phase` is distinct from `details.phase`, which `_identity_details` still copies at `errors.py:101`. The search not-entered proof matches `arrival_search.py:171-178`, where `open_snapshot`, provider acquisition and `coverage()` all precede `build`. The projection entered/unknown claim matches the wrapper starting at `arrival_maintenance.py:243`. The dead `ProjectionSyncError` member at `errors.py:375` is indeed unreachable after line 339.

**Findings (all low, none blocking)**

1. **Implicit context on sibling re-raise** (existing limitation, not a regression). `raise result` at line 727 executes inside `except _CollectionStepFailed as primary`, so the propagated interrupt gets `__context__ = primary`. Cause identity is preserved as required, but tracebacks will show "During handling of the above exception" with the bookkeeping failure. If that is unwanted, `raise result from result.__cause__` is not safe either, since it would rewrite a None cause. Minimal correction: none required; document that `__context__` is intentionally left untouched, or set `__suppress_context__` only if the team decides the bookkeeping context is noise.

2. **Only the first sibling BaseException survives** (existing limitation). If two siblings both raise unexpected control exceptions, the first in source order propagates and the second is dropped after its stream is closed. Consistent with the deferred secondary-diagnostics decision in triage item 3, so no change now.

3. **C2 design: search `coverage()` failure before `build`** (design refinement). The design names `query.open_snapshot` and provider acquisition as the not-entered cases, but `maintenance.coverage()` at line 177 also runs before `build`. The worklist's "flip a local flag immediately before `build`" already covers it; the acceptance-test bullet should list a pre-build `coverage()` failure explicitly so the flag placement is tested, not assumed.

Nothing in the packet lets me verify the claimed `sync_target` routing or test counts; those remain submitted evidence.
