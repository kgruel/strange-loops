# Arrival SDK read and transfer contract audit — 2026-09-06

## Scope and contract baseline

This is a read-only audit of the current SDK surfaces for reads, declaration
inspection, search, aggregate composition, verification, export, projection
maintenance, search-index maintenance, and restore-forward. It does not reopen
the six fixes already closed by the 2026-09-06 correctness pass.

The comparison baseline is `docs/architecture/arrival/backend-contract.html`
§§02–08 and §11:

- a descriptor selects the adapter and states role/lineage intent; the adapter
  establishes actual identity from genesis;
- a read captures a full head `H`, and projected answers identify the verified
  represented prefix `P` plus the derived-view generation;
- ordinary SDK reads require `CURRENT`, so missing or behind projections refuse
  without materialization or repair;
- `Full` verification covers grammar, density, lineage, and the hash chain, and
  neither verification nor query reads repair custody or projections;
- exact export and replication are bounded by captured full heads, and an
  uncertain or post-commit result must retain reconciliation evidence.

One subtle mutation applies to almost every descriptor-first operation:
`BackendRegistry.open()` returns an `AttestedLedger`. Its constructor compares
the presented head and may write an earned first-contact/advance entry and
location binding to the **external witness journal**
(`arrival_head_seam.py:AttestedLedger.__init__`, lines 1620–1708). It does not
mutate the ledger or projection. A refusal or degradation **inside that
constructor** writes no witness entry (lines 1657–1679; 1440–1446). Once the
constructor succeeds, however, a later snapshot, query, or declaration refusal
can follow an already-earned witness advance. The matrix calls this “open
witness.”

## Matrix

| SDK entrypoint | Identity and declaration authority | H / P / generation and concurrency | Mutations | Return and failure guarantees | Resource ownership | Assessment |
|---|---|---|---|---|---|---|
| `read_summary` | Explicit descriptor and genesis establish the store. Single-store fields use the effective declaration folded from `_decl.*` rows in the same snapshot. A descriptor-bearing root changes to aggregate composition only when that bounded declaration says so (`sdk/read.py:read_summary`, 528–589). | One `CURRENT` capture. Result carries `ReadBasis(H, P, generation)`. A projection observed ahead of H is clamped to H in the basis (`engine/arrival_consumer.py:open_read`, 112–218). | Open witness only. No projection repair. | `ReadSummary` keeps `read_path`, descriptor, basis, declaration status and counts (`sdk/types.py`, 169–199). Missing/behind projection refuses. | `_open_arrival_read` closes snapshot, query, and ledger in `finally` (`sdk/read.py`, 94–114). | Intended and coherent for single stores. Aggregate arm follows the vector rules below. |
| `read_facts` | Same descriptor/effective-declaration authority; internal rows require an explicit flag. | One `CURRENT` capture. Pages are hard row bounds, and `Continuation` binds H, P, request, cursor and generation; resume revalidates head membership and generation (`sdk/read.py:read_facts`, 714–948; `arrival_consumer.py`, 67–85, 140–215). | Open witness only. | `FactPageResult` retains basis even for empty pages; process serialization deliberately omits the in-memory continuation token while reporting `has_continuation` (`sdk/types.py`, 202–226). | Context-owned and closed. | Intended. Tests: `test_arrival_read.py:test_descriptor_reads_share_typed_basis_and_close`, `test_arrival_page_dict_does_not_serialize_engine_continuation`, `test_sdk_arrival_fact_pagination_hard_bounds_packed_batch`. |
| `read_state` | Folds user facts with the effective declaration from the same snapshot, not the current locator file (`sdk/read.py:read_state`, 949–1067). | One `CURRENT` basis for a single store. Aggregate state has member bases instead of one synthetic H. | Open witness only. | `FoldStateResult` reports declaration generation and sections; no partial state on projection/declaration refusal (`sdk/types.py`, 229–246). | Context-owned and closed. | Intended. Test: `test_arrival_read.py:test_arrival_state_uses_snapshot_declaration_not_current_file`. |
| `read_ticks` | Explicit descriptor/genesis; ticks come from the bounded projection. | One `CURRENT` basis; chronological projected rows bounded by H (`sdk/read.py:read_ticks`, 1069–1125). | Open witness only. | Uniform `TickReadResult`; empty results retain basis (`sdk/types.py`, 249–260). | Context-owned and closed. | Intended single-store surface. Descriptor aggregates are explicitly outside this entrypoint’s current member semantics. |
| `read_fact_by_id` | Explicit descriptor/genesis. Internal declaration facts remain hidden on the public default (`sdk/read.py:read_fact_by_id`, 1127–1182). | One `CURRENT` basis. Exact match wins; literal arbitrary-string prefix lookup can refuse ambiguity. | Open witness only. | `FactLookupResult.fact=None` still carries basis (`sdk/types.py`, 263–280). | Context-owned and closed. | Intended. Tests: `test_arrival_read.py:test_arrival_fact_lookup_keeps_internal_namespace_hidden`, `test_sdk_arrival_fact_lookup_accepts_literal_arbitrary_id_prefixes`. |
| `resolve_entity` | Single-store descriptor and snapshot declaration. Resolution is latest receipt-order fact with exact top-level key type/value (`sdk/read.py:resolve_entity`, 1356–1461). | One `CURRENT` basis. Concurrent later appends are excluded by H. | Open witness only. | `EntityResolutionResult` preserves address, miss, descriptor and basis (`sdk/types.py`, 729–742). | Context-owned and closed. | **Concrete interface inconsistency:** there is no `registry=` parameter and Arrival always uses built-ins (line 1393), unlike the other supported descriptor reads. This prevents an injected/opaque backend from using the same SDK operation. Test coverage establishes capture semantics but not registry injection: `test_arrival_emit.py:test_arrival_resolve_entity_stays_at_captured_head_during_concurrent_append`. |
| `read_timeline` | Single-store facts/ticks share one snapshot; aggregate topology uses captured member declarations. Timeline is explicitly an event-time lens, with receipt coordinates as single-store ties (`sdk/read.py:read_timeline`, 1464–1576). | Single store: one `CURRENT` basis. Aggregate: sequential member basis vector; no common H. | Open witness for every descriptor member. | `TimelineResult` reports total/truncation/order; aggregate evidence is attached (`sdk/types.py`, 844–875). | Single and aggregate context managers close all retained handles. | **Concrete interface inconsistency:** no `registry=` parameter; both single and aggregate arms force built-ins (lines 1493–1515). Legitimate difference: event-time ordering is a lens and is not receipt/fold order. |
| `inspect_declaration` | Local locator bytes provide residence and a local fingerprint; all declared kinds/observers/cadence/strict fields come from the store’s effective snapshot declaration (`sdk/declare.py:inspect_declaration`, 659–716). | One `CURRENT` basis. Later declaration appends are excluded from the captured inspection. | Open witness only; missing/behind projection is not repaired. | `DeclarationInspectionResult` carries local/effective fingerprints and drift (`sdk/types.py`, 961–987). | `_open_arrival_read` context closes all resources. | **Two contract decisions:** (1) no `registry=` parameter, so custom adapters cannot be inspected; (2) it calls `_arrival_declaration(... allow_aggregate=False)` (lines 684–686), so an Arrival aggregate declaration is refused even though this structural DTO has `is_aggregate` and legacy inspection supports aggregates. The second looks unnecessarily narrower than summary/state/timeline, but should be decided explicitly. Tests pin bounded drift/current refusal, not these two cases (`test_arrival_inspect.py`, 121–214). |
| `search_facts` | Descriptor/genesis plus same-snapshot effective declaration determine the canonical search field spec and its hash (`sdk/read.py:search_facts`, 1185–1258). | One `CURRENT` read basis. Search additionally requires exact FTS coverage for the requested field hash and reports `ranking_through`; later projected matches remain outside captured H. | Open witness only. Search never creates FTS coverage. | `SearchResult` carries basis, fields hash, ranking and ranking head. `SearchStale`/contract failures are normalized to SDK errors (`sdk/read.py`, 1259–1263; `sdk/types.py`, 762–793). | Context-owned and closed. | Intended single-store surface. Tests: `test_arrival_search.py:test_arrival_search_requires_current_coverage_and_returns_basis_json`, `test_arrival_search_captured_snapshot_excludes_later_projected_match`. |
| Aggregate `read_summary`, `read_state`, `read_timeline` | Topology is taken from each descriptor node’s bounded effective declaration; storeless roots use frozen local bytes. Members are occurrence identities, not deduplicated by lineage/path. Each member records descriptor declaration identity and local definition hash (`engine/arrival_aggregate.py:capture_aggregate`, 261–330; `sdk/aggregate.py:AggregateRead.member_evidence`, 157–207). | Members are captured sequentially and each retains its own `ReadBasis`; there is deliberately no fabricated cross-store H/P/generation. Top-level `basis` and `store` are `None`. | Open witness independently for each member. No stores or projections are changed. | Results carry `aggregate_members` and `aggregate_definitions`. Mixed implicit storage with descriptor members refuses instead of falling into legacy readers. | `AggregateCapture.close` closes every node in reverse order and continues after close errors (`engine/arrival_aggregate.py`, 168–218); SDK context owns it (`sdk/aggregate.py`, 370–388). | Legitimate difference. Test: `test_arrival_aggregate.py:test_two_arrival_members_compose_summary_state_timeline_and_basis`, lines 91–123. Other read/search/entity aggregate semantics remain intentionally unsupported rather than silently partial. |
| `verify_target` | Descriptor/genesis and ledger membership; it does not consult declaration rows or open a `QuerySnapshot` (`sdk/verify.py:verify_target`, 47–94). Registry attestation still probes the query watermark and refuses foreign/ahead projection evidence before it can write an earned witness (`arrival_head_seam.py:_projection`, 1506–1566). Authority/Replica/Archive operation permission is enforced by the scoped ledger contract. | Captures H from attested open. Optional `through` must be same-lineage, at/below H, hash-resolved, then `Full` verified (`sdk/verify.py:_verified_prefix`, 26–44). Concurrent later append is outside the result. It returns no P/generation claim. | Open witness may change. `verify(Full)` itself changes neither ledger, projection nor backend head metadata. | `VerifyResult` explicitly claims grammar/density/lineage/hash-chain and excludes signatures, external-key trust and projection (`sdk/types.py`, 902–915). Failures normalize to SDK taxonomy. | Query and ledger close quietly in `finally`. | Intended custody-only result difference, with projection-watermark gating at attestation. Tests: all four tests in `sdk/tests/test_verify.py`, especially `test_verify_target_stays_at_captured_prefix_after_later_append`. |
| `export_target` | Explicit Authority/Replica descriptor; no declaration or query-snapshot requirement. Its ordinary registry attestation still probes and gates suspicious projection watermark evidence. Codec must be advertised (`engine/arrival_transfer.py:open_export`, 99–125). | Captures source H; selected head is H or an exact fully verified member prefix. Stream stays bounded while concurrent appends occur. It returns no P/generation claim. | Open witness plus creation/publication of the destination artifact; source ledger/projection unchanged. | Complete temp file is flushed/fsynced, hard-linked without replacement, then directory-fsynced. Source failure never publishes a truncated artifact. `ExportPublicationError` distinguishes not-published from visible artifact with durability unknown (`sdk/transfer.py:export_target`, 61–155). | `CapturedExport` owns record iterator, query and ledger and closes on drain/context exit (`engine/arrival_transfer.py`, 58–96); SDK removes temp in `finally`. | Intended custody-only export after projection-watermark attestation. Tests: `test_arrival_export.py`, especially exact-prefix, late-source-failure, and directory-sync-failure cases. |
| `sync_target` (Arrival) | Explicit Authority/Replica descriptor. Ledger identity is attested and target is fully verified before a private registered projection maintainer is opened (`engine/arrival_maintenance.py:sync_projection`, 178–218). | Captures H and targets H. Existing P at/above target is validated and never rewound. Concurrent append cannot enlarge target; concurrent maintenance may produce a newer actual P, reported with generation `None` if the bounded snapshot cannot identify that newer view (lines 220–282). | Open witness plus explicit transactional projection catch-up. No ledger mutation; rebuild is refused. | `SyncResult` exposes captured, target, before/after P, generation and changed/rebuilt (`sdk/read.py:sync_target`, 1793–1835). Engine failure retains target, prior P and observed-after/unknown (`arrival_maintenance.py`, 90–111, 283–294). | Maintainer, query and ledger close in `finally`. | **Concrete failure-taxonomy inconsistency:** `sync_target` does not call `normalize_exception`, so `ProjectionSyncError` escapes even though `sdk.errors.normalize_exception` explicitly maps it to `ProjectionOutcomeUnknown` (`sdk/errors.py`, 292–342). `sync_search_index`, verify and transfer do normalize. Also the docstring’s “basis-bearing” wording is imprecise: the result carries head/generation fields, not a `ReadBasis`. |
| `sync_search_index` | First `CURRENT` read captures the effective declaration/spec; a second registry-owned coordinator open fully verifies that exact first H and requires a current base projection (`sdk/read.py:sync_search_index`, 1742–1785; `engine/arrival_search.py:sync_search_index`, 141–187). | Result intentionally exposes both first `basis.captured_head`, second `coordinator_captured_head`, and fixed `target`; a concurrent append may make coordinator H newer without changing the target corpus. Search coverage has its own head, fields hash and schema. | Two open-witness opportunities plus explicit full-prefix FTS replacement/build. Ledger and base projection unchanged. | `SearchIndexResult` retains both captures and before/after coverage. Failure reports target, fields hash, prior and observed coverage as projection-unknown after normalization (`sdk/types.py`, 796–825; `arrival_search.py`, 76–94, 188–203). | First read context closes; engine closes snapshot, maintainer, query and ledger in `finally`. | Legitimate dual-capture difference. Test: `test_arrival_search.py:test_search_maintenance_keeps_first_declaration_capture_when_reopen_is_later`, 200–220. |
| `restore_forward` | Both endpoints require explicit transfer-capable descriptors. Source H is fully verified; receiver must be an exact older prefix of the selected source. Receiver projection rows and declaration anchor are audited against its actual custody prefix before and after replication (`sdk/transfer.py:restore_forward`, 184–218; `engine/arrival_restore.py:_restore_forward`, 229–322). | Source captured H and selected prefix are fixed. Receiver `before` is fully verified, suffix replication is one full-head CAS, and receiver is recaptured/audited afterward. Races refuse or become explicit incomplete/unknown outcomes. | Source open witness. Receiver ledger exact-next replication; on success receiver witness and binding advance. Receiver projection is **not** caught up or rebuilt. | Success returns source captured H, receiver before/after, and shared `Commit` or `None` for no-op. An unexpected replicate failure is `RestoreForwardUnknown(before,target)`; a failure after known commit is `RestoreForwardIncomplete(commit,cause)`, normalized to distinct SDK uncertain/committed-incomplete errors (`arrival_restore.py`, 49–67, 294–321). | All four source/receiver ledger/query handles close in `finally`; SDK exposes no raw custody handle. | Intended transfer difference. Tests: `sdk/tests/test_arrival_restore.py`; engine race, unknown, witness, projection-fork and closure cases in `engine/tests/test_arrival_restore.py`, 56–540. |

## Cross-surface findings

### Concrete inconsistencies

1. **Registry injection is missing from `resolve_entity`, `read_timeline`, and
   `inspect_declaration`.** Each is an Arrival-supported descriptor operation,
   but each hardcodes the built-in registry. The same opaque/custom backend can
   be read through summary/facts/state/ticks/lookup/search and then become
   unreachable through these adjacent operations. Adding the optional keyword
   and threading it to `_open_arrival_read`/`open_aggregate_read` is the smallest
   consistent contract change.

2. **Exception normalization is uneven across supported public entrypoints.**
   Search, search maintenance, verification, export, and restore normalize
   engine failures. Ordinary summary/facts/state/ticks/lookup/entity/timeline
   reads and Arrival inspection generally let engine refusals escape. The
   strongest concrete counterexample is `sync_target`: the SDK already defines
   an explicit `ProjectionSyncError -> ProjectionOutcomeUnknown` mapping, but
   the entrypoint does not invoke it. Define whether all SDK Arrival operations
   promise the process-boundary taxonomy; if they do, apply normalization around
   each public Arrival branch without relabeling interruption/cancellation.

3. **Arrival aggregate declaration inspection is narrower than its result
   contract suggests.** Structural inspection does not require composing member
   data, yet `_arrival_declaration` is called with its single-store aggregate
   guard. Either pass `allow_aggregate=True` and report the effective topology,
   or document/remove the currently unreachable Arrival `is_aggregate=True`
   case. This needs an explicit product decision rather than inference.

### Legitimate differences

- Aggregate results must carry a member basis vector. A synthetic aggregate
  head would erase concurrency and occurrence identity.
- Verification and export return no `P` or view generation because they do not
  consume a query snapshot. Their registry open still checks projection
  watermark evidence. Search has both ordinary query basis and independent FTS
  coverage because ranking depends on a declaration-derived corpus.
- A descriptor-first “read” can update the external witness journal on an
  accepted first contact or observed advance. It still must not repair the
  ledger/projection, and current implementations preserve that separation.
- Restore has commit/unknown/incomplete outcomes because it mutates receiver
  custody. Projection/search sync failures describe possibly changed derived
  state and must not be called custody commits.

### Challenge to identity decision D6

`identity-decisions-2026-09-06.md` D6 is sound in requiring evidence and
actions to remain separate, but “one outcome vocabulary” needs a narrower
definition before it becomes an implementation rule. These operations have
different durable objects: custody records, projection rows, FTS coverage, an
export artifact, and the external witness journal. One flat status enum would
collapse distinctions D6 otherwise preserves. A common **certainty/action
axis** (`refused`, `unchanged`, `changed-known`, `outcome-unknown`,
`known-incomplete`) can coexist with operation-specific evidence fields.

D6 also names witness state as evidence, while current successful SDK results
do not expose whether attested open wrote a first-contact/advance witness entry.
That omission is uniform, but it means the proposed “consistently named and
serialized” rule is not yet true. Decide explicitly whether witness changes are
internal safety bookkeeping or public result evidence. If public, add a small
serialized attestation outcome rather than treating every read as mutation-free;
if internal, narrow D6 so it does not promise that field.

## Validation

Focused current suites were run from the shared worktree:

```text
uv run --package sdk pytest -q \
  libs/sdk/tests/test_arrival_read.py \
  libs/sdk/tests/test_arrival_aggregate.py \
  libs/sdk/tests/test_arrival_inspect.py \
  libs/sdk/tests/test_arrival_search.py \
  libs/sdk/tests/test_verify.py \
  libs/sdk/tests/test_arrival_export.py \
  libs/sdk/tests/test_arrival_restore.py

56 passed in 1.08s
```

The passing suites establish the documented current behavior; they do not
erase the three interface/failure inconsistencies above, which currently lack
targeted regressions.
