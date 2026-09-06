# SDK write/recovery consistency audit

Date: 2026-09-06

This audit compares the current descriptor-backed SDK paths with the stage
contracts in `completion-worklist-2026-09-05.md`, the runtime-write,
declaration-edit, initialization, and source handoffs, and the engine/SDK
package boundaries. It is a source audit; no implementation or new tests were
added.

## Contract matrix

| Operation | Authority and identity | Captured evidence and concurrency | Mutation and success | Refusal, interruption, unknown | Resources |
| --- | --- | --- | --- | --- | --- |
| `sdk.emit_fact` (Arrival) | `_arrival_descriptor` selects the explicit descriptor; `execute_ordinary_write` requires Authority, a compared attested head, and the declaration anchor. Fact inner signing uses `fact_signer`; the optional generated tick uses `tick_signer`; the Arrival envelope uses `arrival_signer`. | `prepare_ordinary_write` captures a CURRENT basis and immutable declaration/fact/tick evidence. Execute compares the full captured head and calls `ledger.append` once. | One fact plus an automatic tick is one ordered draft unit. An optional sync runs after custody commit and receives `Commit.after`. | Engine append unknown, unwitnessed, and post-commit projection failures retain IDs and head/commit evidence through `sdk.errors`. A pre-append `OrdinaryWritePreparationRefused` is instead converted directly to legacy `AdmissionFailed`, unlike batch normalization; this is a public taxonomy inconsistency. The SDK catches `Exception`, so interrupts propagate. | Runtime executor closes query and ledger; SDK legacy handle closes in `finally`. |
| `sdk.emit_batch` (Arrival) | Same descriptor, Authority, declaration anchor, and three signing domains. Each input gets its own admission decision. | One capture and one `BatchWritePlan`; exact full-head CAS and one `ledger.append`. Packing preserves adjacent same-observer body records; mixed observers use separate records under the same commit. | Empty input and all-duplicate input are explicit no-ops. A nonempty plan commits one batch and then synchronizes. | Invalid later inputs, admission, atomic-cap, and stale-head failures happen before append. Unknown, unwitnessed, and projection failures carry plural IDs and commit state. The retained legacy arm is deliberately sequential and returns `LegacyBatchPartialFailure` with its observable prefix. | Executor closes both handles. No retry is performed after an unknown append. |
| `sdk.run_sources` | SDK requires an Arrival Authority; engine capture repeats the Authority and compared-head gate. Source/lifecycle observers are checked against the effective declaration before collectors run. | Initial capture freezes basis, cadence, dependency tiers, locator, and IDs. Later tiers recapture and require declaration documents to remain equal; each tier uses its own exact-head batch plan. | Collection is external and occurs before custody. A tier packs source facts, lifecycle facts, pending ticks, and final `_sync` as configured, then appends once; dispatch occurs only after witnessed commit. | Collected source errors become lifecycle facts. Invalid output and admission are retained as known-uncommitted tier evidence. Unknown and unwitnessed append outcomes are distinct. Static gap: an execute-time pre-append `RuntimeWriteRefused`/contract refusal at `arrival_sources.py:848-856` falls through `_terminal_result` (`sdk/sources.py:264-285`) as category `failed`, even though `_result` retains `known_uncommitted`; the shared refusal/unknown distinction is not uniform here. | `_collect_one` (`arrival_sources.py:468-482`) explicitly calls `aclose` after invalid output. An async generator often self-closes when it raises, so no leak is confirmed; ownership for a custom async iterator or cancellation path remains a hypothesis requiring a focused probe. |
| `sdk.edit_declaration` and Arrival kind/grant/revoke wrappers | `prepare_declaration_edit` requires Authority, a pinned lineage, unchanged descriptor residence, historized declaration anchor, and an edit observer with a key valid at captured H. Inner declaration facts and outer declaration fact/batch use separate signers. New observer document keys are preceded by signed key records from an already-valid author. | Preparation captures CURRENT documents, full H, basis, exact old cache bytes/hash, key registry evidence, and exact signed drafts. Apply locks the target, writes an exclusive intent, rechecks cache bytes, and appends once against H. Recovery checks `ledger.head_at(captured)` and exact expected suffix records. | Semantic no-op is no append and no cache publication. Otherwise key introductions and declaration transition are one final atomic draft set; sync and exclusive cache publication follow custody. Convenience kind operations require local cache bytes and semantic documents to match CURRENT, preventing unrelated local drift. | Contract/stale refusal before append removes the intent; append unknown, unwitnessed, and committed-incomplete preserve intent and planned IDs. Recovery can report `not-applied` when exact H and old cache prove no append, and never resigns. Recovery knows the resulting head but has no original `Commit`, which is consistent with “Commit only when possessed.” | Preparation and append handles are closed before sync/publication. A per-target advisory lock serializes apply/recovery; cache temp/backup bytes are verified and competing files are not overwritten. |
| `sdk.init_vertex` Arrival arm | SDK owns custody lookup/creation; engine receives fact and Arrival signers plus public key. Fresh init requires Authority and validates declaration AST/documents, descriptor residence, lineage, and both signing domains. Physical genesis is ordinal zero; declaration genesis fact ID equals the physical lineage. | There is no pre-mint H. The adapter's exclusive `mint` decides absent/existing/corrupt state. A durable intent reserves exact genesis envelope, declaration drafts, IDs, timestamps, descriptor, and text before mint. Recovery compares exact genesis metadata and exact bootstrap records. | Phases are reserved, minted, declared, synced, published. Declaration append is one atomic unit (including declared key introductions); sync and cache publication are later phases. Existing/conflicting files remain intact. | Mint refusal is adapter evidence, not filesystem absence. Mint unknown, unwitnessed, and post-mint committed-incomplete outcomes retain lineage, intent, and available head/commit evidence. Static boundary gap: SDK `_init_arrival` catches `BaseException` and unconditionally executes `raise normalized from exc` at `sdk/declare.py:628-634`; unlike `verify_target` (`sdk/verify.py:87-91`), an unchanged interruption is not re-raised through a bare `raise`, so the process-boundary exception can acquire a self-cause. This is the precise issue; broad catching alone does not establish interruption loss. Successful `InitVertexResult` exposes lineage/head/phase, while declaration fact IDs and a custody `Commit` are not part of the success DTO; decide whether lineage-as-genesis identity is sufficient. | Engine closes ledger/query in all phases. Intent and parent directory fsyncs are explicit; publication uses a fully written sibling plus exclusive link. Recovery never creates a replacement key. |

## Shared interpretations and concrete gaps

The strongest shared seam is `capture_runtime` plus
`execute_ordinary_write`/`execute_batch_write`: all three use a compared
Arrival head, a CURRENT query basis, immutable drafts, full-head CAS, one
append attempt, and explicit post-append synchronization. Declaration apply
uses the same shape but reimplements basis assembly.

That reimplementation has one confirmed static discrepancy. In
`arrival_declarations.prepare_declaration_edit` (`engine/arrival_declarations.py:854-875`), when
`snapshot.represented.ordinal > captured_head.ordinal`, the code leaves
`projected_through=captured_head` without calling
`ledger.head_at(represented)`. In contrast,
`runtime_write._current_write_basis` (`engine/runtime_write.py:688-705`) calls
`head_at` for an observed watermark above H before clamping the execution
basis. This may be intentional because the declaration snapshot is opened at
H, but the two paths do not establish the same membership evidence. A focused
fake query whose represented watermark is ahead of H would settle whether
declaration preparation must adopt the runtime helper or explicitly document
its stronger snapshot guarantee.

Outcome models are also split at the process boundary. Single Arrival emit
maps preparation refusal to the older `AdmissionFailed`; batch emit maps
engine preparation refusal through `AdmissionRefusal`; source execution
embeds a `SourceTerminalResult`; declaration and initialization raise typed
SDK exceptions. This preserves compatibility but makes callers branch on
operation rather than on one refusal/committed/unknown contract. The existing
tests cover each arm separately:
`libs/sdk/tests/test_arrival_emit.py` (CAS, projection, unknown, and
unwitnessed), `test_arrival_sources.py` (tier outcomes), and
`test_arrival_declarations.py` (intent/recovery outcomes). A cross-operation
conformance table should be added when implementation resumes.

The intended distinctions are otherwise clear and should remain separate:
pre-append refusal proves zero append; unwitnessed means custody supplied a
commit but witnessing failed; unknown means append durability is unresolved;
projection or cache failure means custody is known and later derived work is
incomplete. Declaration recovery's missing original Commit is evidence
availability, not a claim that no commit occurred.

## Deferred or intentionally separate behavior

Legacy SQLite/JSONL emission and replay remain compatibility paths. The
legacy batch arm explicitly reports sequential partial completion. Legacy
`Vertex.evaluate_boundaries` also retains its historical global tick cutoff;
it should not inherit Arrival origin semantics without a separate compatibility
decision.

Descriptor adoption/authority transfer, search/index maintenance, source
dispatch retry policy, and CLI initialization remain separate stages.
Aggregate capture and cross-lineage read/fold composition are implemented with
per-member evidence; aggregate search/entity behavior remains separately
scoped. Declaration edits preserve residence and therefore must not be used as
adoption. Source collectors are intentionally not retried after either
collection error or unknown append. The current test inventory supports these
boundaries but does not make deferred operations available.

The main next shared work is a small conformance adapter for basis construction
and outcome classification, plus an explicit failed-collector close policy.
Neither requires changing the Arrival wire format or retaining SQLite as an
authority.
