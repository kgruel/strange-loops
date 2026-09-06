# Arrival SDK source execution stage — 2026-09-05

Status: implementation and local verification complete; Fable review queued for the reported 21:20 CDT quota reset.

## Result

`sdk.run_sources` is an async, descriptor-first source operation for one explicit Arrival Authority. It requires a lifecycle observer, accepts registry and credential-provider injection, loads existing custody keys without creating them, and exposes force, collector, dispatcher, and evaluated-time seams. Non-Arrival, aggregate, and non-Authority targets refuse without entering the legacy program or store probe paths.

The SDK result is a frozen `SourceRunResult` with serializable cadence and dependency decisions, initial and per-tier read bases, exact collected domain and lifecycle fact bodies with stable IDs, actual per-tier Commit objects, all prepared fact/tick identities, witness/projection status, dispatch intents and outcomes, error lifecycle identities, and a whitelisted terminal classification. It contains no `RuntimeCapture`, declaration AST, record drafts, or backend record bodies.

Known uncommitted collection and unknown append durability use separate fields and tier outcomes. A source error whose error lifecycle fact committed remains `status="error"` with no terminal interruption. Unwitnessed, projection-failed, and dispatch-failed results retain the actual commit. When no dispatcher is supplied, exact frozen run intents remain visible as `attempted=False`, `succeeded=None`, and `dispatch_status="not-requested"`.

`SourceFactResult` retains payloads as `Any` in memory. Its wire serializer converts valid mapping payloads to their exact JSON shape, identifies non-object payloads without coercion, records typed paths for non-JSON values, and replaces non-finite numeric envelope values with explicit issue evidence. It never uses `default=str` or `repr` as a payload substitute, so retained failure evidence remains strict-JSON serializable.

## Acceptance coverage

Real temporary Arrival SDK fixtures cover dependency tiers and current projection reads, injected registry and credentials, durable source errors, nested non-JSON payload values, `None`/list payload shapes, NaN timestamps under `allow_nan=False`, invalid collector output, append unknown versus unwitnessed identity, callback-absent run intents, dispatch failure, projection failure, default credential loading without key creation, explicit observer admission, Replica refusal, and legacy refusal.

Validation at freeze:

- SDK source tests: `11 passed`.
- Full SDK suite: `463 passed`.
- Source plus capture/ordinary/batch engine tests: `69 passed`.
- Architecture suite: `101 passed`.
- Ruff and ty over the SDK/engine source surfaces: passed.
- `git diff --check`: passed.

## Review queue

The static Fable 5.1 packet is `/tmp/loops-arrival-review/sdk-source-prompt.txt`. It requests at most eight concrete findings and 1,500 words, with severity, reproduction, smallest correction, and limitations. It has not been invoked before the quota reset.

## Deliberate limits

This stage does not change legacy `Executor`/`VertexProgram` or CLI source routes, support aggregate/cross-lineage execution, retry collectors, or claim delivery guarantees for run clauses. A dispatcher is explicit; absent callbacks expose unattempted intents rather than claiming execution.
