# Arrival consistency contract matrix — September 6, 2026

Status: source-backed audit and recommended work order, **not implementation**.
Sol audited reads and transfer, Terra audited identity, Luna audited writes and
recovery, and root reconciled their findings against the current implementation.
The worktree is `loops-wt/arrival-finish` on `arrival/finish`; prior correctness
remediation remains intact and uncommitted.

The next consistency pass should first align descriptor injection, captured
projection evidence, and public outcome classification. Those are concrete
differences between entrypoints that already claim the same contract. Identity
work should preserve existing namespaces, reject ambiguous local boundary
interpretation, and replace filename-derived credential selection with an
explicit binding in a separately specified implementation slice.

## Evidence and scope

- [Read, inspection, maintenance and transfer audit](consistency-audit-read-transfer-2026-09-06.md): per-entrypoint source references, resource ownership, and current test coverage.
- [Write, source and recovery audit](consistency-audit-write-recovery-2026-09-06.md): capture/CAS, durable outcomes and interruption questions.
- [Identity audit](consistency-audit-identity-2026-09-06.md): the current namespaces and implementation constraints.
- [Root identity decisions](identity-decisions-2026-09-06.md): recommendations, existing restrictions, compatibility implications, and deferred semantic choices.

Normative baseline: the Arrival [backend contract](../../architecture/arrival/backend-contract.html),
[protocol](../../architecture/arrival/protocol.html), and
[wire profile](../../architecture/arrival/wire-format.html). Historical package
guides still describe suffix-selected stores, repairing opens, and a future
unused backend seam. Those descriptions are transitional documentation debt,
not authority to reintroduce those behaviors into descriptor-first Arrival.

The matrices below describe current supported Arrival paths unless explicitly
marked as a gap or recommendation. Legacy branches are identified separately;
their presence does not confer the Arrival guarantees.

## Shared vocabulary

`H` is a captured **full Head**, including hash. `P` is the custody-resolved
prefix represented by the query answer. `G` is an opaque derived-view generation.
An observed projection watermark must be resolved through custody before it
is accepted as evidence. A concurrent legitimate projection advance may be
observed above H, while the answer and write CAS remain bounded to H.

`CURRENT` refuses an absent/behind projection; it does not authorize repair.
Ordinary open checks identity and available projection evidence, but it is not
a full comparison of every projected row against custody. Full content audit
is a stronger, explicitly invoked operation used by restore.

`W` below means an accepted registry open **may write external witness/binding
evidence**. Query/read/preview does not therefore mean zero filesystem writes.
The attestation constructor refuses before its own witness writes, but a later
query or declaration refusal can occur after a successful open advanced that
witness. Current SDK read DTOs expose their basis, not a complete witness-write
receipt. No new public witness receipt is assumed by this matrix.

## Capture and authority matrix

| Operation | Authority / declaration source | Fixed evidence and concurrency | Actual supported distinction |
| --- | --- | --- | --- |
| Target resolution | Explicit backend and role; locator supplies adapter address. No backend open. | Parsed locator only; it has not authenticated genesis or captured H. | Legacy `resolve_target`/discovery still probe filesystem-shaped targets. `resolve_arrival_target` is currently single-descriptor only. |
| Facts, lookup, ticks, entity | Descriptor/genesis plus one CURRENT snapshot; declared semantics come from bounded documents where needed. | H/P/G; fact pages additionally bind request, receipt cursor and generation. Later records cannot enter the captured answer. | Literal exact-first fact-ID lookup; internal rows are hidden by public defaults. Registry injection is missing for entity resolution. |
| Summary, state, timeline | Single-store captured effective declaration; aggregate topology from each descriptor's effective declaration, or frozen local definition for storeless nodes. | One H/P/G or per-occurrence basis vector. Timeline orders by event time; fold/receipt order is a different axis. | Same-lineage occurrences remain distinct; own declared fold kinds shadow children even when empty. Timeline lacks registry injection. |
| Declaration inspection | Captured effective declaration, plus separately reported local cache fingerprint. | CURRENT H/P/G; local drift is not substituted for effective history. | Registry injection absent; aggregate declaration inspection currently refuses. Supporting it is a scope decision, not permission to invent an aggregate H. |
| Search | Captured declaration supplies indexed-field specification. | H/P/G plus exact FTS coverage, field hash, schema/ranking evidence. | CURRENT base projection is insufficient when FTS coverage is stale. Search never builds its own index. |
| Preview, ordinary emit, batch | Authority; snapshot anchor and effective admission/folds; operation-fresh domain-separated credentials. | Detached CURRENT capture; full-head CAS for execution. A batch has one final atomic draft set, even with mixed observers. | Preview does not reserve H. Exact duplicates and empty batches can be no-ops; preview success cannot promise a later append. |
| Source execution | Authority and frozen source graph/observers selected before collection. | Deterministic dependency tiers; later tiers recapture and check declaration continuity; one CAS per tier. | External collection precedes custody. External dispatch follows the required commit/witness evidence; it has no exactly-once guarantee. |
| Declaration edit / recovery | Authority; own historized declarations, edit author's already-valid key at H, unchanged descriptor residence. This is key-history validation, not an added admin/grant rule. | CURRENT H and exact cache/draft evidence; operation lock, durable intent and full-head CAS. Recovery proves predecessor and exact suffix. | Convenience edits require cache semantics to match history. Preparation's observed-watermark membership check differs from read/runtime capture. Vertex rename is already refused as a routine edit. |
| Initialization / recovery | Explicit new Authority; signed physical genesis and own declaration genesis share lineage identity. | No pre-mint H; exclusive mint plus durable reserved initialization evidence and exact bootstrap reconciliation. | Several durable phases, not one global transaction. Recovery uses reserved evidence and does not mint a replacement identity. |
| Projection sync | Attested descriptor; verify selected H before private maintenance. | Target fixed at captured H; actual P may advance further under another maintainer and must be reported honestly. | Catch-up only, including a physically absent projection; existing unwatermarked rows and inconsistent/foreign markers refuse. No rebuild, witness reset or custody mutation. |
| Search sync | First capture selects declaration/spec; coordinator's second capture verifies that exact target. | First basis, coordinator H, fixed target and before/after FTS coverage remain separate. | Two captures are deliberate. The newer coordinator head must not silently enlarge the search corpus. |
| Verify / export | Descriptor and custody prefix membership; no query snapshot/current P required. | Capture H; optional selected prefix must resolve to its exact hash and be fully structurally verified. | Ordinary attestation still checks available projection evidence. Verify does not claim authorship or full projection agreement. |
| Restore-forward | Source normally attested; private receiver procedure proves actual older prefix and source containment. | Fixed source H/selected head, receiver full before-head, one exact-suffix CAS, post-append observation/audit. | Source and receiver keep their roles. Receiver projection is audited but not caught up. No raw bypass handle or lowered witness escapes. |

## Mutation, outcome and ownership matrix

These dimensions are deliberately separate: custody certainty, witness state,
derived-state completion, and actions performed by this invocation. Similar
meaning should have consistent SDK classification even when one operation
returns a structured tier result and another raises an exception.

| Operation | Mutations | Success / interruption evidence | Resource owner |
| --- | --- | --- | --- |
| Resolution | None beyond reading locator files. | Named descriptor is not proof of a live authority. | Resolver's file reads. |
| Query / inspection / search | W only. | Typed basis on hits, misses and empty results; a refusal may follow an already-successful attestation. Some public readers currently leak engine error families. | Read context closes snapshot, query, ledger. Aggregate closes all captures, including partial construction failures. |
| Preview | W; local signer loading only. | Captured admission/plan evidence; zero custody append or key mint. | Capture closes backend resources; plan is detached. |
| Emit / batch | W, one custody append for non-no-op plan, witness, post-commit projection sync. | Actual Commit retained on known post-commit failure. Unknown outcome is not retried. No-op does not fabricate Commit. | Runtime executor and post-commit maintenance own their handles. |
| Sources | W per capture, external collection, custody per tier, projection maintenance, optional external dispatch. | Collected, known-uncommitted, committed, unknown and dispatch outcomes remain distinct. An earlier tier can be durable when a later tier fails. | Coordinator owns captures/execution; failed/custom collector stream close policy needs verification. |
| Declaration edit | W, lock/intent/temp/cache files, one custody append, witness, projection sync and cache publication. | Intent survives uncertain or incomplete commit. Exact old/cache checks prevent overwriting unrelated edits. | Coordinator closes backend handles and scopes the operation lock/publication files. |
| Declaration recovery | W plus only reconciliation actions required by durable intent. | Original Commit is unavailable: `commit=None` is honest even if recovery proves completion. `file_written` means this invocation actually published the cache. | Recovery lock and coordinator resources. |
| Initialization | Explicit SDK key creation when requested, intent, genesis mint, declaration append, witness, projection/cache publication. | Phase and reserved identity survive interruption. Success currently gives lineage/head/phase, not a universal initialization Commit. | SDK custody composition and engine initializer/recovery. |
| Projection / search sync | W and derived-state writes only. | Target/before/observed-after distinguish completed work from unknown derived outcome; no custody Commit. `sync_target` currently bypasses an existing SDK normalization mapping. | Registry-owned maintainer, snapshot where needed, query, ledger. |
| Verify | W only. | Captured and verified heads; structural verification coverage is explicit. | Query/ledger handles closed even without a query snapshot. |
| Export | W plus new destination artifact. | Complete bytes staged/fsynced, published exclusively, then directory synced. Source error preserves its identity; publication error states whether the complete artifact became visible. | Captured stream owns iterator/query/ledger; SDK owns output/temp cleanup. |
| Restore-forward | Source W, exact receiver custody suffix, receiver witness on success. | No-op or actual Commit; unknown and known-committed-incomplete are distinct. A failed call does not imply receiver unchanged. | Private coordinator closes all source/receiver handles. |

## Prioritized consistency worklist

“Source-confirmed” means the divergent code paths were inspected, not that a
new adversarial failing test was executed in this documentation pass. Each
implementation item starts with a public reproduction or a focused contract
test where the question concerns an injected backend.

| ID / order | Finding and disposition | Bounded next change and acceptance |
| --- | --- | --- |
| C1 / first | Source-confirmed: `resolve_entity`, `read_timeline`, `inspect_declaration` hardcode built-in registry selection. | Thread one optional registry consistently through single and aggregate paths. A registered opaque backend must work across supported reads; an unknown backend must refuse without legacy probing. |
| C2 / first | Source-confirmed: `sync_target` bypasses `ProjectionSyncError -> ProjectionOutcomeUnknown`; ordinary reads also vary in normalization. Single/batch/source admission results have differing taxonomies. | Inventory and align SDK certainty/evidence mapping across the supported family. Preserve source type, IDs, H/Commit, original cancellation and useful admission detail. Do not flatten all failures into refusal or require every operation to raise instead of returning tier evidence. |
| C3 / first | Source-confirmed discrepancy: declaration preparation clamps a represented watermark above H without `head_at(represented)`, unlike read/runtime capture. | Exercise a legitimate concurrent advance and a nonexistent/foreign reported prefix; establish one shared custody-completion rule before clamping. Reuse a narrow basis helper if it removes the duplicated interpretation. No need to merge entire operation lifecycles. |
| C4 / next | Source-confirmed: SDK `CustodyCredentialProvider.key_dir` is accepted and unused. | Recommend clear refusal of non-None configuration until a consistent override exists; keep ordinary default behavior. Document compatibility impact. The later mapped provider must cover public-key registration and all signing domains. |
| C5 / next | Confirmed architectural ambiguity: local vertex ticks and same-named loops can share production/interpretation keys. | Define and test an effective-declaration collision predicate, including passive/count/boundary loops. Refuse ambiguous Arrival runtime materialization/planning and proposed declarations while preserving evidence reads/export. See D4. |
| C6 / design | Remove/recreate and incompatible same-name boundary edits have no incarnation evidence; hydration associates historical ticks by current name. | Define compatibility/continuity and refusal behavior before exposing automatic rename/reset. Preserve fixed facts and existing vertex-rename refusal. Separately design explicit key bindings and their compatibility migration. See D1–D5. |
| C7 / bounded scope decision | Inspection can report aggregate structure in its DTO, but Arrival aggregate inspection is blocked by single-store guards. | Admit local aggregate shape at descriptor resolution while preserving explicit role checks, then permit bounded effective-root inspection. Both guards need addressing. Inspect root topology without opening members for a fictitious global basis; specify storeless-root evidence separately and test both directions of local/effective topology disagreement. |
| C8 / verify before fixing | Source iterator cleanup and initialization exception rethrow need focused cases. | Test a resource-owning custom iterator's error/cancellation paths. Verify unchanged exceptions use a bare re-raise: initializer currently self-chains `normalized is exc`; verify already avoids this. Catching BaseException alone is not evidence that an interrupt was swallowed. |
| C9 / after conformance | Legacy resolution/writer paths and stale docs remain competing public interpretations. | Finish SDK/minimal-CLI transition and retire legacy authority paths deliberately. Update docs/help with the supported API; do not implement new storage behavior in the CLI. |

Projection preserve/rebuild recovery, empty-receiver exact import, foreign
admission and descriptor adoption remain on the larger
[completion worklist](completion-worklist-2026-09-05.md). They are not made
available by consistency cleanup. Restore projection recovery still has a
separate [design proposal](projection-recovery-correctness-design-2026-09-05.md).

## Cross-operation acceptance scenarios

Extend existing integration fixtures instead of reproducing implementation
branches in isolated unit tests. These are acceptance targets for the next
code pass, not tests newly added or claims newly established here.

| Scenario | Existing coverage to build on | Added cross-operation assertion |
| --- | --- | --- |
| Emit/batch → fresh read | `test_arrival_emit.py`: emit/sync/current-read and batch-boundary/lookup tests. | Same actual Commit, admitted IDs, declaration interpretation and read prefix across one registry; post-commit projection failure remains distinguishable from no append. |
| Declaration failure → recover → inspect/read/emit | `test_arrival_declarations.py`: interruption, exact suffix, cache drift, granted observer emission. | Public recovered result serializes independently, no invented Commit/cache write, and all subsequent operations use the recovered effective declaration. |
| Concurrent projection advance → read/runtime/declaration prepare | Consumer continuation tests and runtime capture tests; declaration anchor regression. | Every path validates reported watermark membership before clamping to H; fabricated evidence refuses before signing/append. |
| Sources → read and retry decision | `test_arrival_sources.py`: unknown, unwitnessed, projection and dispatch outcomes. | Public certainty matches persisted tiers; no recollection or dispatch replay inferred from a generic failure category; owned streams close under cancellation/errors. |
| Restore → verify → explicit sync → read | `test_arrival_restore.py` plus projection-maintenance tests. | Exact receiver prefix survives restoration, witness never lowers, structural verify matches selected head, and only explicit sync enables a formerly-behind CURRENT read. |
| Export while source advances → inspect artifact | `test_arrival_export.py` and engine captured-export tests. | Artifact ends at selected full head with returned byte count/manifest; output-close failure cannot mask source failure. |
| Same backend across SDK entrypoints | Existing fake-registry read fixtures. | Summary/facts/state/ticks/lookup/entity/timeline/inspection/search share injection and refusal behavior; serialization retains appropriate evidence. |
| Identity move/change → sign/hydrate | Custody alias/flat-nested tests and runtime boundary-consumption tests. | Stable binding survives locator moves; unauthorized replacement key is not a rotation; collisions and incompatible reincarnations are explicit rather than inferred. |

Inject failures before custody mutation, after a returned Commit, and during
derived/cache/artifact publication. Assert persisted evidence as well as the
returned result. Do not use an ordinal comparison as a substitute for exact
prefix or row agreement.

## Validation and completion boundary

Sol ran the focused existing SDK read/aggregate/inspection/search/verify/export/
restore suites: **56 passed**. This is current-behavior coverage; the newly
identified gaps need targeted tests in their implementation slices. Root
reviewed the strongest divergent call paths and reconciled agent conclusions,
including ordinary-open projection checks and the existing vertex-rename
restriction. No external reviewer was run for this documentation pass.

Root's final scope/link check is recorded in
`/tmp/loops-arrival-consistency-2026-09-06/validation.json`. No implementation,
test, dependency, live-store, or live-key changes are part of this pass. These
documents specify the next work; they do not claim that consistency fixes or
new identity capabilities have landed.
