# Arrival SDK consumer query design

Status: recommendation for completion-worklist item 2; no protocol operation is
ratified by this note.

## Decision

Add one SDK-facing **opened read snapshot** abstraction, not a portable SQL
connection and not another store class.  It is the smallest common surface that
lets the SDK read facts, ticks, folded state, pages, search results, and
single-store summaries without exposing `FileQuery.reader` or SQLite types.
It serves the new headless SDK and minimal CLI first; replacing every old CLI
presentation is an inventory-and-retirement task, not a query compatibility
requirement.

Descriptor resolution also needs an explicit instance role before this path is
called. `READ` is an operation, not a `Profile`: it does **not** assign,
imply, or activate `AUTHORITY`. The descriptor declares the store instance's
custody role; the registry checks that declaration and the adapter's capability
for the requested operation. A read from an authority-designated instance is
still a read-only handle with no append surface. `role=None` remains only for
existing transitional descriptor callers, not the supported new SDK path. The
first file-backed path supports reading an explicitly declared authority or
replica; it does not invent a query-only or archive profile the adapter cannot
honestly advertise.

The important unit is the read *basis*:

```python
@dataclass(frozen=True)
class ReadBasis:
    lineage: str
    captured_head: Head             # custody head captured for this request
    projected_through: Head | None  # prefix represented by the returned rows
    view_generation: str | None     # query/declaration/projection view identity

class QuerySnapshot(Protocol):
    @property
    def represented(self) -> Watermark | None: ...
    @property
    def view_generation(self) -> str | None: ...
    def facts(self, request: FactRequest) -> FactPage: ...
    def ticks(self, request: TickRequest) -> tuple[Tick, ...]: ...
    def summary(self, request: SummaryRequest) -> Summary: ...
    def search(self, request: SearchRequest) -> SearchPage: ...
    def close(self) -> None: ...

class ArrivalQuery(Protocol):
    def open_snapshot(
        self, *, captured_head: Head, requirement: ProjectionRequirement,
        continuation: Continuation | None = None,
    ) -> QuerySnapshot: ...
```

`Fact`, `Tick`, requests, pages, and cursors are engine/SDK value objects,
shaped from the existing SDK result fields rather than `StoreReader` rows.  A
page cursor contains (or is integrity-bound to) lineage, captured-head hash,
represented-prefix hash, order, filters, and the last `(arrival_ordinal,
arrival_seq, id)` key, plus the query/declaration/projection view generation.
`FactRequest.limit` is a hard maximum number of returned fact rows: a packed
Arrival record may span pages, and the full receipt coordinate resumes without
a duplicate or gap. Ledger scan/export and declaration transitions retain their
whole-record atomicity; it is not a presentation-page rule. Offset cursors and
SQLite rowids do not cross this boundary. A cursor is passed
only to `open_snapshot`, whose later `facts` request must match its bound
filter/order. `SearchPage` has no continuation in the first cut: ranked FTS
does not have a portable keyset order. It may report `NotSupported` when the
backend lacks FTS and does not promise SQLite FTS syntax or ranking. The first
cut needs no raw SQL method: backend-specific analyst access remains explicitly
backend-specific.

`ProjectionRequirement` has only `CURRENT` and `ALLOW_BEHIND`.  `CURRENT`
refuses `ProjectionAbsent` or `ProjectionBehind`; `ALLOW_BEHIND` returns rows
only through the represented prefix and makes that prefix visible in every SDK
result.  `CURRENT` should be the public minimal-CLI default.  Diagnostics and
the later Painted client can deliberately choose `ALLOW_BEHIND`.

This keeps two heads distinct. `captured_head` is what custody said existed
when the read started. `projected_through` is what the query state can prove it
represented. The query snapshot only reports its `Watermark`; the private
coordinator completes it to a `Head` with custody and constructs `ReadBasis`.
They are equal for a current read, and never silently substituted for one
another.

## Opening and snapshot algorithm

Put a small coordinator in the SDK/engine consumer seam; neither an adapter nor
`VertexHandle` is allowed to spell this sequence itself.

1. Parse the effective vertex store clause, require its explicit instance
   role, and make its descriptor.  Open through `BackendRegistry` with a
   `READ` operation request.  The registry checks the declared role and query
   capability but never promotes a capable adapter to Authority.  The opener
   only returns handles; it does not recover, rebuild, or materialize.
2. Wrap the ledger in `AttestedLedger(ledger, location=descriptor.location,
   query=query)`.  This compares the actual head with external head memory and
   checks projection-ahead/foreign-lineage evidence before any derived state is
   changed.  Its successful `OpenReport` is retained for diagnostics.
3. Without a continuation, take `H` from a successful
   `OpenReport.comparison.presented`, rather than call `attested.head()` again.
   This is the head the seam just compared, avoids a second full walk in the
   file adapter, and avoids a second-time observation. The new SDK path accepts
   only a `Compared` report; `PreGenesis` and `Indeterminate` refuse. With a
   continuation, first prove its captured-head hash still resolves through
   `attested.head_at()`, then use that token head as `H`; the newly presented
   head may be later. Projection catch-up and rebuild are named maintenance
   operations, never an incidental read.
4. Ask `query.open_snapshot(captured_head=H, ...)` for one backend read
   transaction/version/range. Inside it, the query reports its watermark and
   bounds every row to `H` or an earlier represented prefix. The private
   coordinator resolves the watermark with `attested.head_at()` and builds the
   complete basis; the query object never receives a general ledger handle.
   If a later projection watermark is above `H`, successful `head_at` proves a
   normal post-capture advance, so the snapshot clamps rows and basis to `H`.
   A failed `head_at`, a foreign lineage, or rows beyond the verified bound is
   `ProjectionAheadOfLedger` evidence.
5. Return values plus the basis.  A multi-call SDK operation keeps this one
   snapshot open; a resumed page opens a new snapshot constrained by the token's
   captured and represented heads, and refuses if either prefix is unavailable
   or its view generation changed. Specifically, it validates the token's
   represented-head hash, requires the new watermark to reach that prefix, and
   rejects a changed view generation even if ledger membership still matches.

The file implementation uses one read-only SQLite transaction for watermark,
cursor lookup, and rows, filters by `(arrival_ordinal, arrival_seq)` through
the represented prefix, and closes it with the snapshot.  A direct DuckDB
implementation can use its transaction/version directly and set
`projected_through == captured_head`; it need not make a companion SQLite
projection.  Both satisfy the same result contract.

The existing seam remains valuable at open: `ProjectionAheadOfLedger` is
evidence and refuses. Behind and absent are reported, not reclassified as
head-attestation failure. Query-time `CURRENT` then decides whether those
honest states are usable for a particular consumer. “Read-only” refers to
ledger/projection custody: first contact or advance may still append the
earned external head-attestation journal entry, as `AttestedLedger` already
does by design.

## What the SDK actually needs

| SDK need today | Snapshot operation | Basis rule |
| --- | --- | --- |
| `read_summary` | `summary` | one snapshot covers totals, kind stats, and signature counts |
| `read_facts`, `read_fact_by_id` | `facts` | fact-by-id is a constrained fact request; receipt order and pages are bounded to the represented prefix |
| `read_ticks`, `read_timeline` | `ticks` plus `facts` | both streams share one basis before SDK event-time merge |
| `read_state` | `facts` then existing compiled fold executor | fold result carries the fact snapshot's basis; folds remain vertex/domain logic |
| `search_facts` | `search` | FTS/declaration generation is a separate declared capability; no read rebuilds it |
| `read_facts` continuation | `open_snapshot(..., continuation=...)`, then `facts` | token binds request, both heads, and compatible derived-view generation, not a rowid |
| aggregate vertex | SDK aggregate coordinator, one member snapshot each | output carries `dict[MemberIdentity, ReadBasis]`; no invented common Arrival ordinal or silent same-lineage collapse |

`summary` is a performance shortcut, not an independently authoritative
surface. Entity resolution and folds are SDK/domain composition over facts.
The minimal generic surface also excludes `VertexHandle`'s live
subscription/refresh loop and arbitrary Quack/SQL. The former is a later
consumer session built on repeated captured snapshots; the latter is useful
backend-specific access, but would turn one SQLite projection into a false
portable contract.

## Evidence applied from review

The following corrections are code-backed. `ArrivalLog.head()` exhausts its
verified `walk`, while `OpenReport.comparison` already carries the presented
head; the coordinator therefore reuses the latter. `FileQuery` reports only a
`Watermark`, so the coordinator, rather than the query snapshot, must complete
it through `head_at`. `StoreReader.query_facts` has an SQLite transaction but
does not bind rows to an Arrival head, and the existing FTS path already treats
declaration and index generations as distinct checks. These support the bounded
snapshot and conservative resume-generation rules above.

The suggestion to reject duplicate aggregate lineages is not adopted. Two
vertices can intentionally compose the same evidence under different
declarations or projections. The aggregate coordinator must preserve each
member's identity and basis; whether it deduplicates is aggregate semantics
that belongs above this backend-neutral read contract.

## Integration stages and touchpoints

1. **Contract and file adapter.** Extend
   `libs/engine/src/engine/arrival_contract.py` with the value types,
   `ProjectionRequirement`, `ProjectionBehind`/`ProjectionAbsent`, and the
   `open_snapshot` method.  Move the public row surface off
   `FileQuery.reader` in `arrival_file_backend.py`; implement a private
   SQLite-backed `FileQuerySnapshot`.  Preserve `lineage()` and
   `projected_through()` during the transition because the head seam uses them.
   Add a separate optional projection-maintenance protocol/result rather than
   a mutating `ArrivalQuery` method.

2. **One descriptor-first consumer opener.** Add an SDK/engine helper adjacent
   to `arrival_registry.py` that performs the five steps above, owns close
   ordering, and returns only `(query_snapshot, read_basis, open_report)`.
   It keeps the attested ledger private after using it to establish the basis;
   a read opener must not hand an append-capable `AttestedLedger` to its caller.
   Make its `READ` intent and mandatory descriptor instance role explicit;
   leave `role=None` on the old compatibility resolver only until its callers
   are migrated.
   Use it from `libs/sdk/src/sdk/read.py`; remove `_ensure_reader` and all
   single-store `StoreReader`/`read_preflight(RECOVER_THEN_OPEN)` use there.
   `sdk/target.py` must resolve a vertex descriptor, not publish
   `canonical_mode` or an index path as the public Arrival result.

3. **Vertex consumer.** Rework `handle.py:VertexHandle._open` to obtain its
   read basis before it resolves an index or creates `StoreProbe`.  Its initial
   fold and tick hydration use a snapshot; its refresh captures a new basis and
   publishes it atomically with the reconstructed `VertexSnapshot`.  Do this
   after the headless SDK path works; it is not required to make the first
   minimal CLI useful.

4. **Explicit maintenance and write outcomes.** Keep
   `arrival_projection.rederive_projections` as deliberate existing-state
   rebuild machinery, but place future missing-only materialization/catch-up
   behind an explicit, serialized maintenance protocol with its projection
   write-lock and report its before/after bases. No read-time materialization
   belongs in the first cut. After
   an accepted append, return `Commit` first and a separate
   `ProjectionOutcome` (`level`, `behind`, `failed`, or `not-requested`).  A
   post-commit projection exception therefore yields “committed through H,
   projection failed/behind”, never an append refusal or a rolled-back receipt.
   `verify` remains non-mutating.

5. **Aggregates and richer clients.** Implement the aggregate coordinator in
   SDK after single-store reads.  It combines already-established member
   snapshots and reports a member-identity-to-basis map. Members may represent
   the same lineage through distinct declarations, locations, or prefixes;
   retain each provenance entry and do not silently collapse them. Deduplication
   is an aggregate semantic decision, not descriptor or read-backend behavior.
   Painted can later choose stale-aware rendering and held sessions without
   adding a new backend query contract.

## Decisions for the implementation owner

| Choice | Recommendation | Why it needs an explicit decision |
| --- | --- | --- |
| Instance role versus read access | descriptor must declare the supported instance custody role; opener takes `READ` and exposes no writer | capability says what an adapter can do, not what this store instance is allowed to do |
| Missing or behind projection | refuse current reads; inspect/repair through explicit serialized maintenance | a read must not mutate derived state or race materializers |
| Public DTO placement | engine owns neutral query DTOs; SDK owns target/declaration/fold/aggregate wrappers and serialization | lets a DuckDB adapter implement the contract without importing SDK, while keeping domain rules out of adapters |
| Search fallback | `NotSupported`/capability result, not a ledger scan pretending to be FTS | ranking, grammar, and index freshness are not portable today |
| Cursor after view change | refuse if query, declaration, or projection generation differs | a matching ledger prefix alone does not prove the same derived view; no historical FTS snapshot is established |
| Legacy bare `.jsonl`/`.db` reads | retain only behind an explicit legacy SDK boundary until migration/cutover | descriptor-first Arrival consumers must not revive suffix dispatch as a second authority path |

## Acceptance tests

1. A read opened through a descriptor calls the registry and the attested-head
   seam before any projection materialization, recovery, or `StoreReader`
   construction.  It refuses an absent instance role on the new SDK path and
   returns no append-capable ledger merely because the adapter supports
   Authority. Rollback, same-height fork, replacement, and
   projection-ahead all leave derived state unchanged.
2. A file snapshot with a concurrent append returns only rows at or below its
   basis; its summary, facts, ticks, and continuation page retain the same
   captured and represented heads.  Tampering or deleting a token's bound
   prefix refuses rather than changing pages.
3. An index behind `H` is distinguishable from absent and from divergent:
   `ALLOW_BEHIND` returns rows through `P < H` with both heads; `CURRENT`
   raises `ProjectionBehind`. A projection that has valid custody membership
   beyond the captured `H` is clamped to `H`; a watermark `P > H` that custody
   cannot resolve raises the existing projection-ahead refusal.
4. A read never materializes, catches up, or rebuilds a projection. Explicit
   maintenance runs only after successful head attestation under its declared
   projection write lock; `verify` performs neither action.
5. File and a test direct-query adapter return equal DTOs and bases for the
   same record corpus, including a batch record's deterministic
   `(ordinal, seq)` expansion; no public SDK Arrival path imports
   `StoreReader`, `sqlite3`, `canonical_mode`, or `.reader`.
6. A committed append followed by injected projection catch-up failure returns
   its durable commit/head plus `ProjectionOutcome.failed`; reopening reports
   the resulting behind state and no second append occurs.
7. A resumed fact page verifies captured and represented head hashes, the new
   watermark still reaches the represented prefix, and a matching derived-view
   generation. Rebuild, declaration, or query-generation changes refuse the
   resume even when ledger membership still matches. Search offers no resume.
8. A two-member aggregate reports two member-keyed bases, preserves each
   member's position even when both name one lineage, and cannot manufacture
   one cross-lineage cursor or Arrival ordinal.
