# Minimal CLI refusal boundary: Fable 5.1 supplement — 2026-09-05

## Invocation

```text
claude -p --safe-mode --model 'claude-fable-5-1[1m]' \
  --no-session-persistence --tools '' --output-format json \
  < /tmp/loops-arrival-review/minimal-cli-supplement-prompt-2026-09-05.md \
  > /tmp/loops-arrival-review/minimal-cli-supplement-result-2026-09-05.json \
  2> /tmp/loops-arrival-review/minimal-cli-supplement-stderr-2026-09-05.txt
```

The raw packet/result are retained in `/tmp/loops-arrival-review/`.
Metadata identifies `claude-fable-5-1` with 3,431 output tokens and 1,988
thinking tokens; the review used no tools or web search and returned
`approve-with-fixes`.

## Findings and dispositions

1. **Fixed — category-6 JSON omitted the outcome discriminator.** The CLI now
   serializes SDK error models through `as_dict()`, preserving schema, type,
   outcome, source type, and identity details.

2. **Fixed — fallback evidence was not guaranteed JSON-safe.** SDK error
   identity extraction now converts non-primitive diagnostic values safely;
   complete JSON encoding happens before stdout is written, with a safe
   fallback envelope if serialization still fails.

3. **Fixed — malformed error details could escape the guard.** CLI details
   extraction validates mappings and handles pathological diagnostic values.

4. **Fixed — refusal models lacked `as_dict()`.** `ArrivalRefusal` and each
   committed outcome model now provide `loops.sdk/error/v1` serialization.

5. **Fixed — import test was too broad.** The AST test now permits exact
   standard-library modules plus `sdk` and `sdk.errors`; it rejects arbitrary
   `sdk.*` imports.

6. **Fixed — `SystemExit(None)` handling.** The parser boundary now handles
   empty exit codes deterministically.

The owner’s additional acceptance checks exercise real temporary file-backed
Arrival processes: corrupted records, rollback after a witnessed advance, and
missing projection indexes all return exit 4 with `ArrivalRefusal`, source type,
and preserved details. Admission errors normalize to existing
`AdmissionFailed` and retain exit 5. `WriteCommitUnknown`, `NotWitnessed`, and
`PostCommitProjectionFailed` remain distinct typed outcomes with exit 6 and
captured head/fact/tick/commit evidence.

Projection maintenance is represented separately as
`ProjectionOutcomeUnknown` (exit 4), retaining target, projected-before, and
observed-after heads without claiming that no derived mutation occurred. The
normalizer also accepts explicit `context={"captured_head", "fact_id",
"tick_id"}` for `NotWitnessed`, whose engine exception does not carry planned
record identities.

**VERDICT:** approve-with-fixes; all supplement findings were addressed.

**LIMITS:** Static Fable review plus owner-run subprocess and focused SDK
classification tests. The new error types are available from `sdk.errors`;
their apex `sdk` re-exports are owned by the descriptor/SDK integration stage.
