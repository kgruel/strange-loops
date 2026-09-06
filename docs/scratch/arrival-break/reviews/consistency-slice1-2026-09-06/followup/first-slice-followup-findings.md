# first-slice-followup — Fable review

Effort: low. Finished: 2026-09-06T16:42:56.948353+00:00.
Packet SHA-256: `d3a5298690e733f2b6925a5cb1c9693fc0e2f85b31040b0e927c833938b80ee6`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** Both follow-ups do what they claim. Two low notes, no correction required.

## Follow-up A (C8a guard order)

`libs/sdk/src/sdk/declare.py:628-639` now normalizes, updates `details` when present, then bare-raises on identity. Behavior by case:

- Unchanged `ArrivalRefusal`: same object, `__cause__` untouched, `details` gains `intent_path` alongside the preexisting `marker`. The test at `libs/sdk/tests/test_arrival_init.py:290` asserts exactly that dict, so it would catch either regression (lost enrichment or lost identity).
- Unmapped `RuntimeError`: no `details` attribute, bare raise, original cause kept. Test at line 262 still holds.
- `KeyboardInterrupt`: `normalize_exception` returns it unchanged, no `details`, bare raise. Test at line 325 still holds.
- Mapped engine error (`UnknownBackend`): new `ArrivalRefusal` chained via `from exc`; line 230 test still asserts cause identity.

Taxonomy unchanged. Correct.

## Follow-up B (finding 3)

Consumer wrong-coordinate case returns `Head(lineage, H-1, "wrong")` for a watermark at H. The helper's coordinate check fires before the equal-height check, yielding `HeadMismatch`, and closure order `["snapshot", "query", "ledger"]` is asserted for all four cases. Matches the runtime/declaration suites. Gap closed.

## Follow-up B (finding 5)

The real-backend test does prove advance-before-open, not merely re-attestation:

- H is captured from the real attested ledger at `registry.open` (line 106).
- Inside the wrapped `open_snapshot`, the log is appended and `sync_projection` runs *before* the real `query.open_snapshot` (lines 119-143), with `captured_head == owner.captured` asserted on the way in.
- Assertions then pin `advanced.ordinal > captured.ordinal`, `represented_ordinal == advanced.ordinal`, and `basis.projected_through == captured`. So the real `FileLedger.head_at` resolved an ordinal above its attested head and the clamp applied.
- Read and runtime cases assert the post-H fact id is absent from returned rows, proving the `_FileQuerySnapshot` bound at `captured_head.ordinal` (line 960) is honored, not just the reported basis.

**1. Low, `libs/engine/tests/test_arrival_projection_custody_integration.py:177`, declaration case proves basis clamp but not row bounding.** The appended fact is a `note`, and preparation only reads `_decl` facts, so `status == "noop"` would hold with or without the bound. The triage wording ("no-op plan and full basis") is honest about this. Cheap hardening if wanted: append a signed `_decl.vertex_defined`-style change after H instead, and assert the plan is still `noop` against the original text. Not required for this slice.

**2. Low, same file line 138, the advance uses a second registry open on the same log while the attested ledger is held.** This works on the file backend (the test passes per triage), but it is a fixture property, not a contract. No change needed; just don't cite it as evidence of concurrent-writer safety.

## Validation boundary

Static review only. Reported counts (engine 2,528 passed / 1 skipped, SDK 497, initializer 11, integration 3) are unverified here. Continuation same-height/coordinate checks remain deferred as recorded.
