# Arrival consistency contract matrix — September 6, 2026

Status: source-backed audit and work order; C3/C8a implementation is tracked in the
[first consistency slice](consistency-slice1-2026-09-06.md), and C1 in the
[registry consistency slice](consistency-c1-2026-09-06.md). C8b is implemented in the
[collection slice](consistency-c8b-2026-09-06.md); C2 is implemented in the
[evidence slice](consistency-c2-2026-09-06.md), accepted after Fable-low follow-up.
The opt-in D0/D2 credential binding is tracked in the
[D0/D2 report](consistency-d0-d2-2026-09-06.md). Remaining items are
recommendations unless a row says they are implemented.
Sol audited reads and transfer, Terra audited identity, Luna audited writes and
recovery, and root reconciled their findings against the current implementation.
The worktree is `loops-wt/arrival-finish` on `arrival/finish`; prior correctness
remediation and C1/C3/C8a are committed in `cfb26920`; C8b and the C2 design
are checkpointed in `8a045f1f`. Subsequent checkpoints are C2 `831698ff`,
C4 `79696a72`, C5 `bacaeb96`, and the C3 continuation `ef8b21b2`.
C6 is checkpointed with its implementation and retained review evidence.

Updated after [Fable-low review and root triage](reviews/consistency-2026-09-06/primary-triage.md).
Fable reviewed frozen copies; root's subsequent changes below are separately
identified in the triage. The later C3/C8a implementation and its own review are
recorded separately in the first-slice report; the original review did not review that code.

The first consistency slice aligns fresh captured projection evidence and
unchanged exception propagation. The subsequent C1 slice adds consistent registry
injection to the remaining supported read paths.
Public outcome classification needs a phase/cause evidence check before broader
normalization. Those are concrete
differences between entrypoints that already claim the same contract. Identity
work should preserve existing namespaces, reject ambiguous local boundary
interpretation. The explicit opt-in D0/D2 binding now replaces
filename-derived credential selection for mapped callers; default legacy
selection remains transitional rather than silently migrating.

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
| Facts, lookup, ticks, entity | Descriptor/genesis plus one CURRENT snapshot; declared semantics come from bounded documents where needed. | H/P/G; fact pages additionally bind request, receipt cursor and generation. Later records cannot enter the captured answer. | Literal exact-first fact-ID lookup; internal rows are hidden by public defaults. Entity resolution accepts the same optional registry as other supported reads. |
| Summary, state, timeline | Single-store captured effective declaration; aggregate topology from each descriptor's effective declaration, or frozen local definition for storeless nodes. | One H/P/G or per-occurrence basis vector. Timeline orders by event time; fold/receipt order is a different axis. | Same-lineage occurrences remain distinct; own declared fold kinds shadow children even when empty. Timeline forwards the supplied registry through root and member opens. |
| Declaration inspection | Captured effective root declaration, plus separately reported local cache fingerprint and unexpanded local/effective topology. Storeless aggregate roots use frozen local semantic evidence. | CURRENT root H/P/G for descriptor roots; no basis for storeless roots. Local drift is not substituted for effective history. | C7 is implemented and accepted. Optional registry injection is preserved; no member resolution/open, aggregate H, or recursive topology validity claim. |
| Search | Captured declaration supplies indexed-field specification. | H/P/G plus exact FTS coverage, field hash, schema/ranking evidence. | CURRENT base projection is insufficient when FTS coverage is stale. Search never builds its own index. |
| Preview, ordinary emit, batch | Authority; snapshot anchor and effective admission/folds; operation-fresh domain-separated credentials. Opt-in mapped credentials use explicit namespace/observer/domain requests and captured public-key authorization. | Detached CURRENT capture; full-head CAS for execution. A batch has one final atomic draft set, even with mixed observers. | Preview does not reserve H. Exact duplicates and empty batches can be no-ops; preview success cannot promise a later append. Mapped resolution creates no key or binding and never falls back to legacy callbacks. |
| Source execution | Authority and frozen source graph/observers selected before collection. | Deterministic dependency tiers; later tiers recapture and check declaration continuity; one CAS per tier. | External collection precedes custody. External dispatch follows the required commit/witness evidence; it has no exactly-once guarantee. |
| Declaration edit / recovery | Authority; own historized declarations, edit author's key introduced through H and valid for the proposed successor, unchanged descriptor residence. This is key-history validation, not an added admin/grant rule. | CURRENT H and exact cache/draft evidence; operation lock, durable intent and full-head CAS. Recovery proves predecessor and exact suffix. | Convenience edits require cache semantics to match history. Preparation now shares custody completion with fresh read/runtime capture. Vertex rename is already refused as a routine edit. |
| Initialization / recovery | Explicit new Authority; signed physical genesis and own declaration genesis share lineage identity. Mapped initialization requires a pre-created exact binding. | No pre-mint H; exclusive mint plus durable reserved initialization evidence and exact bootstrap reconciliation. | Several durable phases, not one global transaction. Mapped loading is read-only; explicit binding creation/import is a prior custody operation. Recovery uses reserved signatures and does not mint a replacement identity. |
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
| Sources | W per capture, external collection, custody per tier, projection maintenance, optional external dispatch. | Collected, known-uncommitted, committed, unknown and dispatch outcomes remain distinct. An earlier tier can be durable when a later tier fails. | Coordinator closes owned async iterators/distinct iterable owners, cancels and settles siblings, and preserves paired partial evidence on coordinator failure. External effects are not reversed. |
| Declaration edit | W, lock/intent/temp/cache files, one custody append, witness, projection sync and cache publication. | Intent survives uncertain or incomplete commit. Exact old/cache checks prevent overwriting unrelated edits. | Coordinator closes backend handles and scopes the operation lock/publication files. |
| Declaration recovery | W plus only reconciliation actions required by durable intent. | Original Commit is unavailable: `commit=None` is honest even if recovery proves completion. `file_written` means this invocation actually published the cache. | Recovery lock and coordinator resources. |
| Initialization | Legacy SDK key creation when explicitly requested, or read-only loading of a pre-created mapped binding; then intent, genesis mint, declaration append, witness and projection/cache publication. Explicit mapped binding creation/import is a separate earlier custody mutation. | Phase and reserved identity survive interruption. Success currently gives lineage/head/phase, not a universal initialization Commit. | SDK custody composition and engine initializer/recovery. |
| Projection / search sync | W and derived-state writes only. | Target/before/observed-after distinguish completed work from unknown derived outcome; no custody Commit. C2 routes `sync_target` through SDK maintenance normalization with explicit attempt/effect evidence. | Registry-owned maintainer, snapshot where needed, query, ledger. |
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
| C1 / implemented; review tracked separately | `resolve_entity`, `read_timeline`, and `inspect_declaration` accept optional registry injection. Timeline forwards it across local aggregation and effective-root member capture, retaining the opened root. | See the [C1 report](consistency-c1-2026-09-06.md) for registered opaque-backend and refusal coverage, validation and review status. Existing entity/inspection aggregate restrictions remain; C7 is separate. |
| C2 / implemented | Arrival `sync_target` now uses existing SDK maintenance normalization; wrappers carry explicit attempt/effect proof and bounded causal diagnostics. | [C2 implementation](consistency-c2-2026-09-06.md) preserves v1 errors, outcome/source type and existing phase, adds optional `details.evidence`, and distinguishes search pre-build non-entry from uncertain entered mutation. Declaration preparation retains captured/projected coordinates and custody non-entry proof. Cancellation, actual receipts, legacy wrappers without proof and structured source tiers remain intact. Valid advanced projection coverage remains supported without claiming a full row audit. |
| C3 / implemented and accepted, including continuation follow-up | Fresh read, resumed snapshot, runtime capture and declaration preparation use one custody-completion rule before use/clamping: lineage, membership, returned coordinate, equal-height full-head agreement. | See the [slice report](consistency-slice1-2026-09-06.md) and [continuation follow-up](consistency-c3-continuation-2026-09-06.md) for regressions, validation and Fable-low acceptance. The same-height comparison checks custody answers, not projected row contents. Resumed reads retain original H/P and generation policy while allowing legitimate projection advance; newly observed snapshot contradictions use HeadMismatch. |
| C4 / implemented and accepted | SDK `CustodyCredentialProvider` now refuses every non-None `key_dir` during construction with `SdkValueError`, instead of ignoring it. | Default construction and explicit None retain all three legacy custody signer domains. See the [C4 report](consistency-c4-2026-09-06.md). D0/D2 subsequently added a separate explicit mapped provider rather than reviving this ignored override. |
| C5 / implemented and accepted | Shared Arrival identity validation refuses every current loop/vertex name equality, including implicit `cite` and runtime-expanded loop names, before hydration/planning. | Proposed/new declarations and SDK semantic preview share the declared-name check; SDK scaffold conflicts refuse before key creation. See the [C5 report](consistency-c5-2026-09-06.md) for passive/count/reset/carry/boundary coverage, preserved evidence reads/export, append-forward configuration correction and Fable-low acceptance. Historical ambiguous tick roles remain D5/C6 continuity work; the current-name gate does not prove them. |
| C6 / implemented and accepted | Ordinary in-place edits inherit edges; shared receipt-history checks refuse consumed prior incarnations, relevant ambiguous roles and unprovable generated membership before runtime hydration and declaration preparation/preview. | See the [C6 report](consistency-c6-2026-09-06.md), [design](consistency-c6-boundary-design-2026-09-06.md), and [Fable-low acceptance/triage](reviews/consistency-c6-implementation-2026-09-06/primary-triage.md). Two Fable-high design reviews preceded implementation. D0/D2 are now implemented separately; explicit restart/carry and vertex aliases remain deferred. |
| C7 / implemented and accepted | Inspection explicitly opts into local aggregate descriptors and bounded effective aggregate declaration reconstruction, preserving default single-store guards and explicit roles. | See the [C7 report](consistency-c7-2026-09-06.md). DTO topology remains unexpanded; only the root has H/P/G. Storeless aggregates report local-frozen semantic evidence without custody. Both local/effective disagreement directions and no member opens are tested; Fable-low accepted with no blockers. The [resolver continuation](consistency-c7-followup-2026-09-06.md) also replaces the older aggregate-read catch-and-reparse bridge and is independently accepted. |
| C8a / implemented in slice 1 | Initialization now bare re-raises `normalized is exc` after existing intent-path enrichment. | Regressions retain identity, original cause, existing SDK details, intent path and interrupts; newly mapped exceptions still chain from the engine cause. See the [slice report](consistency-slice1-2026-09-06.md). |
| C8b / implemented | Owned iterator cleanup and atomically paired partial observations now survive collector/coordinator failure; failed current-tier custody is not attempted. | Typed collection terminal preserves completed/failed/cancelled sibling evidence and earlier commits through SDK serialization. No lifecycle is fabricated for an incomplete attempt. Fully collected final-summary failures retain known-uncommitted tier evidence. See the [C8b report](consistency-c8b-2026-09-06.md). The previous strict zip already refused mismatched lists before append. |
| D0/D2 / opt-in implementation accepted and checkpointed | Neutral exact credential requests separate local namespace/observer/domain selection from captured authorization. The mapped provider persists opaque key references through serialized, recoverable binding intents; resolution is read-only and default legacy callers are not auto-migrated. | See the [D0/D2 report](consistency-d0-d2-2026-09-06.md) and [design](consistency-d0-d2-design-2026-09-06.md). Runtime/declaration/source planning checks mapped public evidence at captured H+1 or against current receipt keys. Mapped initialization loads a pre-created binding; explicit create/import/recovery retains concurrent and interrupted operation evidence. Focused Fable-low and primary triage accepted completed-slot recovery and the subsequent directory/import durability corrections; final custody validation passed 81 tests. |
| C9 / after conformance | Legacy resolution/writer paths and stale docs remain competing public interpretations. | Finish SDK/minimal-CLI transition and retire legacy authority paths deliberately. Update docs/help with the supported API; do not implement new storage behavior in the CLI. |

Projection preserve/rebuild recovery, empty-receiver exact import, foreign
admission and descriptor adoption remain on the larger
[completion worklist](completion-worklist-2026-09-05.md). They are not made
available by consistency cleanup. Restore projection recovery still has a
separate [design proposal](projection-recovery-correctness-design-2026-09-05.md).

## Cross-operation acceptance scenarios

Extend existing integration fixtures instead of reproducing implementation
branches in isolated unit tests. These were acceptance targets from the initial audit. C3/C8a evidence now lives
in the linked first-slice report; remaining scenarios still need their own
implementation and validation.

| Scenario | Existing coverage to build on | Added cross-operation assertion |
| --- | --- | --- |
| Emit/batch → fresh read | `test_arrival_emit.py`: emit/sync/current-read and batch-boundary/lookup tests. | Same actual Commit, admitted IDs, declaration interpretation and read prefix across one registry; post-commit projection failure remains distinguishable from no append. |
| Declaration failure → recover → inspect/read/emit | `test_arrival_declarations.py`: interruption, exact suffix, cache drift, granted observer emission. | Public recovered result serializes independently, no invented Commit/cache write, and all subsequent operations use the recovered effective declaration. |
| Concurrent projection advance → read/runtime/declaration prepare | Consumer continuation tests and runtime capture tests; declaration anchor regression. | Every path validates membership and equal-ordinal hash agreement before clamping to H; fabricated evidence refuses before signing/append. A legitimate later projection prefix still works and continuations retain their prior bound/generation rules. |
| Sources → read and retry decision | `test_arrival_sources.py`: unknown, unwitnessed, projection and dispatch outcomes. | Public certainty matches persisted tiers; coordinator ID failure is not collector failure; fact/ID evidence stays paired. No recollection or dispatch replay inferred from a generic category; owned streams close under cancellation/errors without masking primary failures. |
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
restriction. That initial native audit was followed by one user-requested
Fable 5.1 review at low effort. Root then ran six existing targeted maintenance/
aggregate tests (all passed) and disposable synthetic basis/collector probes.
Those probes establish interface behavior, not a reproduced attack against a
live file backend. The [review triage](reviews/consistency-2026-09-06/primary-triage.md)
records accepted findings, rejected suggestions, and the exact validation scope.
The subsequent C3/C8a implementation is recorded in the first-slice report,
including separate implementation reviews and regression results. Later
accepted consistency slices are recorded in their table rows. D0/D2's final
recorded validation is engine **2,611 passed / 1 skipped**, SDK **578 passed**,
custody **81 passed**, sign **40 passed**, and architecture **101 passed**. The
SDK run predates the final custody-only recovery/durability corrections, covered
by the final custody suite. Final Fable-low review and primary triage accepted.

Root's initial scope/link check is recorded in
`/tmp/loops-arrival-consistency-2026-09-06/validation.json`; the review's final
scope check is retained with its triage. No implementation,
test, dependency, live-store, or live-key changes were part of that initial audit
pass. The C3/C8a rows above now link to the separately authorized implementation;
remaining workload conformance, maintenance/transfer completion, adoption and
C9 work remain recommendations or separate roadmap items.
