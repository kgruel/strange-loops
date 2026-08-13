# Loops libraries: proposed changes for CLI v2

Audience: loops library agent  
Basis: review of `libs/` public behavior only  
Goal: make a small, honest CLI possible without duplicating substrate policy in an app.

## Priority legend

- **P0** blocks a required CLI capability or risks incorrect persistence.
- **P1** is needed for a robust first complete CLI.
- **P2** improves consistency, performance, or future interfaces.

## P0: support declaration ceremonies in JSONL-canonical stores

### Problem

`JsonlStore.absorb_genesis()` and `JsonlStore.absorb_edit()` currently refuse. Consequently, a CLI cannot persistently add a kind to an adopted JSONL-canonical vertex even though ordinary fact emission works.

The hard part is transactional ordering: declaration operations perform compare-and-swap checks and may roll back, while JSONL canonical writes require the durable log line to precede visibility in the SQLite index.

### Requested library outcome

Design and implement canonical-log-safe equivalents for:

```python
store.absorb_genesis(...)
store.absorb_edit(..., expected_head=...)
```

Required properties:

- All declaration rows in one edit ceremony remain atomic as an ontology transition.
- Every row shares one effective timestamp.
- Stale `expected_head` refuses without leaving canonical log artifacts.
- Signatures cover the final persisted payload.
- Recovery after interruption cannot expose a partial ceremony.
- The SQLite index remains a pure derivation of the canonical log.
- Python and Go conformance behavior remains aligned.

Likely prerequisite: represent a multi-row declaration ceremony as one canonical batch/envelope record or add a prepare/commit encoding that replay treats atomically.

### Acceptance tests

- Genesis succeeds against a new `.jsonl` canonical store.
- Adding, modifying, and retiring kinds round-trip through declaration resolution.
- A stale edit leaves both log and index byte/row equivalent to their pre-call state.
- Failures injected before append, after append, and before index commit recover without partial ontology.
- `audit_deep` passes after each successful ceremony.

## P0: provide one declaration-update orchestration API

### Problem

An app currently has to assemble a protocol-sensitive sequence itself:

1. load/parse a proposed declaration;
2. resolve current declaration documents;
3. capture the declaration head;
4. call `vertex_to_documents`;
5. call `diff_documents`;
6. open the correct canonical store with signing;
7. call `absorb_edit(expected_head=...)`;
8. reconcile the `.vertex` ingress/cache file.

This spreads lineage, residence, signature, and concurrency policy into every client.

### Requested library outcome

Add a high-level operation resembling:

```python
preview = plan_declaration_update(vertex_path, proposed_ast)
result = apply_declaration_update(
    preview,
    observer=observer,
    credentials=credentials,
)
```

`preview` should expose:

- current declaration status and generation;
- canonical store mode;
- subject-granular changes;
- captured declaration head;
- whether the file or store is authoritative;
- whether the backend can apply the update.

`apply` should validate that the preview is still current and either complete atomically or return a typed recovery state. The store-backed declaration remains authoritative after genesis.

This API should own protocol rules; file-cache replacement may stay app-injected if the library does not want filesystem presentation policy.

## P0: define recoverable file/store declaration synchronization

### Problem

There is no transaction spanning the authoritative store declaration and the `.vertex` ingress/cache file. A process can die after one changes and before the other does.

### Requested library outcome

Choose and document a recovery protocol. Recommended shape:

- Store-first after genesis.
- Durable intent containing vertex path, old/new declaration generations, proposed document projection, and store declaration head.
- Idempotent `recover_declaration_update(intent)`.
- Atomic file replacement after store success.
- Clear detection of `already-applied`, `safe-to-finish`, and `conflict` states.

If this belongs above `libs/`, expose enough typed generation/head data that an app can implement it without querying private store fields.

## P1: add bounded, cursor-bearing generic fact queries

### Problem

`StoreReader` can query intervals and recent facts for one kind, but lacks an efficient generic query for the latest facts across all kinds. A generic CLI cannot safely implement `read --facts --limit 20` without reading an arbitrarily large interval and sorting it itself.

### Requested API

```python
reader.query_facts(
    *,
    limit: int = 100,
    before: FactCursor | None = None,
    after: FactCursor | None = None,
    kind: str | None = None,
    observer: str | None = None,
    include_internal: bool = False,
    order: Literal["newest", "oldest"] = "newest",
) -> FactPage
```

The cursor should preserve the store's actual ordering contract and avoid using IDs as if they were witness positions. Return `items`, `next`, and truncation information from one consistent read snapshot.

Add vertex-aware composition for combine/discover targets where a meaningful aggregate cursor can be defined; otherwise return a typed unsupported result rather than invent a global order.

## P1: expose persisted signature state in write receipts

### Problem

`Receipt`/`ReceiveResult` reports the fact ID, storage, tick, and state change, but not whether the persisted fact received a signature. A CLI cannot honestly print `signed: true|false` merely by checking whether local keys exist: a per-observer signer may return `None`, and the committed row is the authority.

### Requested outcome

Extend the result with persisted attestation metadata, for example:

```python
FactAttestation(signed: bool, observer: str, signature_present: bool)
```

If a tick fired, expose the corresponding tick-chain/signature status as well. Populate this from the committed row or the write operation's actual result, not from configuration inference.

## P1: resolve declared observer admission policy at the engine boundary

### Problem

The declaration carries `ObserverDecl.grant.potential`, while `Vertex.receive()` only enforces a `Grant` supplied by its caller. Every writing client can accidentally omit the declared policy and thereby write facts the declaration says that observer may not emit.

### Requested outcome

Provide one of:

- `VertexProgram.receive_as(fact)` / `VertexHandle.receive_as(fact)` that resolves the observer declaration and applies its grant automatically; or
- a public `grant_for_observer(ast, observer)` helper plus an explicit engine mode that requires declared-policy evaluation.

Specify behavior for:

- no observers block;
- unknown observer;
- declared observer without a grant;
- declared observer with a potential set;
- aggregate vertices.

The safe client API should make bypassing declared admission policy explicit.

## P1: either enforce `strict` or narrow its documented meaning

### Problem

`VertexFile.strict` is parsed, historized, and returned by declaration resolution, but the runtime receive path does not use it to reject undeclared kinds. A CLI cannot explain `strict` accurately as an emission policy.

### Requested outcome

Decide the contract and cover it in engine tests:

- If strict means declared-kind admission, enforce it before storage with a typed rejection.
- If strict has another meaning, name and implement that meaning.
- If it is reserved metadata, document it as inactive and prevent clients from presenting it as enforcement.

Preserve the useful non-strict behavior in which undeclared facts are stored, appear in raw reads, and later become folded when their kind is declared.

## P1: promote generic KDL vertex mutation into a public API

### Problem

`kdl_insert_child` and `kdl_remove_child` exist in `lang.population` and are tested against loop-kind edits, but are not exported from `lang`. Insertion also assumes the parent block exists; a CLI adding the first kind needs to create `loops {}` safely.

### Requested API

```python
add_vertex_kind(text: str, kind: str, definition: LoopDef) -> str
edit_vertex_kind(text: str, kind: str, definition: LoopDef) -> str
remove_vertex_kind(text: str, kind: str) -> str
```

Required properties:

- Preserve unrelated comments, whitespace, and ordering.
- Handle absent, multiline, and single-line `loops` blocks.
- Quote/escape kind names correctly or reject names the KDL grammar cannot represent safely.
- Parse and validate the result before return.
- Round-trip insert/remove to byte-identical original text where possible.
- Expose a supported `LoopDef`-to-KDL serializer rather than relying on engine builder internals.

## P1: expose a supported target/store probe

### Problem

Every client must currently repeat suffix checks and residence logic to explain whether a target is a vertex, JSONL canonical log, derived index, or SQLite canonical store. Opening the wrong sibling for writing is a correctness error.

### Requested API

```python
probe_target(path: Path) -> TargetInfo
```

Suggested fields:

```text
target_type
canonical_mode
canonical_path
index_path
exists
index_current
declaration_status
writable
reason
```

Detection should use file content where appropriate, not only filename suffixes, while never turning a read probe into store creation or repair unless explicitly requested.

## P1: make canonical agreement a first-class read preflight

### Problem

The JSONL documentation says the cheap `audit_agreement` gate should precede every store read verb, but the primitive lives in `engine.canonical_audit` and is not part of a unified target-open result. A new app can easily materialize/repair before auditing and erase useful evidence.

### Requested outcome

Expose an explicit read preparation API that distinguishes:

```text
audit-only
audit-then-open
recover-then-open
```

Never silently conflate verification with repair. Return typed agreement/recovery information that a CLI can render and map to exit codes.

## P2: centralize lifecycle visibility projection

### Problem

`FoldSection` carries lifecycle metadata, but the documented default hide of inactive entities currently belongs to a presentation layer rather than the typed engine fold itself. A second CLI can easily disagree on which items constitute the default view.

### Requested outcome

Add a portable projection helper, for example:

```python
project_fold_visibility(fold, *, include_inactive=False) -> FoldState
```

Keep the raw fold accessible. Define missing lifecycle fields as fail-open, preserve inbound/edge calculations, and return counts that disclose how many items were hidden.

## P2: add a complete result codec for public dataclasses

### Problem

`FoldState`, `FoldItem`, ticks, receipts, witness positions, declaration generations, audit reports, and store maintenance results do not share one documented JSON encoding. Each client can create subtly incompatible output.

### Requested outcome

Provide stable `to_dict()` or codec functions for public result types, including:

- RFC 3339 versus epoch-time policy;
- mappings and immutable proxy handling;
- schema/version identifiers where interchange is intended;
- explicit omission/null rules;
- address and edge encoding.

This need not dictate human rendering.

## P2: add a read coordinator for search coverage and fallback

### Problem

Correct search requires checking `vertex_search_coverage`, respecting declaration generation, querying only trustworthy kinds, and falling back or failing closed for missing/stale coverage. That orchestration is easy for separate clients to get wrong.

### Requested outcome

Add a read-only coordinator returning hits plus provenance:

```python
SearchResult(
    hits=...,
    mode="fts" | "scan" | "mixed",
    stale_kinds=...,
    generation=...,
    truncated=...,
)
```

It must never trigger reindexing. Reindex remains an explicit mutation.

## P2: define maintenance support by canonical backend

### Problem

`libs/store` maintenance operations are primarily SQLite-shaped, while a `.jsonl` store treats that SQLite file as derived. Direct maintenance against the index can create out-of-band rows or changes that the canonical log cannot explain.

### Requested outcome

For every public maintenance operation, publish and enforce a backend matrix:

| Operation | SQLite canonical | JSONL canonical |
|---|---|---|
| slice | supported | define canonical output |
| merge/receive | supported | append/rewrite ceremony required |
| compact | supported | define log/index behavior |
| rebirth | supported | define canonical target behavior |
| export/rebuild | supported | clarify direction and authority |

APIs should take canonical locators or a `TargetInfo`, not an ambiguous sibling `.db` path.

## Suggested implementation order

1. JSONL declaration ceremony design and conformance tests.
2. High-level declaration plan/apply/recover API.
3. Bounded generic fact query.
4. Persisted attestation data in receipts.
5. Observer-policy resolution and a decision on `strict`.
6. Public vertex KDL mutation/serialization API.
7. Target probe plus canonical audit/open modes.
8. Lifecycle projection, common codecs, and search coordination.
9. Canonical-backend maintenance matrix and missing implementations.

## Definition of success

The library work is complete when a client can:

1. resolve any supported target without guessing authority;
2. inspect it with bounded queries;
3. emit through a vertex with declared policy and real attestation results;
4. add a kind to either canonical backend with atomic, recoverable declaration semantics;
5. render fold state, search results, and maintenance outcomes without recreating substrate rules.
