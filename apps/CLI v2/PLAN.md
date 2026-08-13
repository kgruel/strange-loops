# Loops CLI v2 plan

Status: design proposal  
Scope: a new CLI derived from the public behavior of `libs/`, without carrying forward the existing CLI's command structure.

Companion documents:

- [`ADDENDUM_ROADMAP.md`](ADDENDUM_ROADMAP.md) explores the longer product direction without expanding the MVP.
- [`LIBS_CHANGES.md`](LIBS_CHANGES.md) is the prioritized library handoff needed to support this plan cleanly.

## Product position

CLI v2 should make the substrate approachable without pretending to understand a user's domain.

A store may describe service dependencies, field research, a personal notebook, or the evolving canon of a novel. The generic CLI therefore begins with facts, kinds, time, observers, and declared folds. It does not assume that `name`, `status`, `title`, or any other payload field has universal meaning.

The governing rule is:

> Default reads report what is present. A vertex declaration supplies meaning. The CLI never guesses domain semantics.

This leads to an intentional asymmetry:

- A bare store is sufficient for inspection.
- A write requires a vertex, because the vertex supplies routing, boundaries, declaration authority, observer policy, canonical-store selection, and signing context.

## Minimum viable command surface

```text
loops read TARGET [options]
loops emit VERTEX KIND --observer NAME --data JSON
loops kind add VERTEX KIND [options]
```

These are the only commands required in the first useful release.

## Target resolution

`TARGET` is resolved by artifact type, not heuristics about directory layout.

| Input | Interpretation | Read path |
|---|---|---|
| `*.vertex` | Declared vertex | `load_declaration`, then vertex-aware APIs |
| `*.jsonl` | JSONL-canonical store | Materialize/catch up sibling SQLite index, then `StoreReader` |
| `*.db`, `*.sqlite` | SQLite-canonical store | `StoreReader` directly |
| Anything else | Unsupported target | Error with accepted forms |

Relative store locators in a vertex are always resolved relative to the vertex file. A sibling `.db` belonging to a canonical `.jsonl` log must never be treated as an independently writable store.

## `loops read`

### Default behavior

With no view option, `read` prints a semantics-neutral inventory:

```text
story.jsonl  ·  jsonl-canonical
facts 421  ·  ticks 8  ·  latest 2026-08-13 14:22:09

kind                 count  earliest              latest
chapter.note           376  2026-01-02 10:14:02   2026-08-13 14:22:09
character.change        45  2026-01-03 08:41:17   2026-08-12 21:07:51
```

This is useful before the CLI knows anything about a kind's fields.

### Initial views

```text
loops read TARGET
loops read TARGET --facts [--kind KIND] [--limit N]
loops read TARGET --facts --since TIME --until TIME [--kind KIND]
loops read TARGET --id FACT_ID_OR_PREFIX [--kind KIND]
loops read VERTEX --state [--kind KIND]
loops read VERTEX --ticks [--name NAME]
```

Rules:

- `--facts` shows raw history and preserves `id`, `kind`, `ts`, `observer`, `origin`, and the complete payload.
- `--state` requires a vertex and renders its typed `FoldState` in declaration order.
- `--id` accepts a full fact ID or an unambiguous prefix.
- `_decl.*` facts are hidden unless `--include-internal` is explicitly supplied.
- `--since` and `--until` are inclusive. Timestamps accept RFC 3339 at the CLI boundary.
- The first release should not fake cursor pagination. `--limit` can support recent facts once the library has a bounded cross-kind query; interval reads can be bounded defensively until then.
- Missing stores return an empty declared state for a vertex, but a directly addressed missing store is an error.

### Output contracts

```text
--format text    Human-readable output; default everywhere
--format json    One stable result document
--format jsonl   One fact or tick per line for streaming views
```

TTY behavior may add color and local-time presentation. Redirected output remains plain but does not silently switch formats. JSON diagnostics go to stderr; stdout contains only the result.

The JSON inventory shape should be versioned from the start:

```json
{
  "schema": "loops.cli/read-summary/v1",
  "target": {"type": "vertex", "path": "/absolute/example.vertex"},
  "store": {"mode": "jsonl-canonical", "canonical": "/absolute/example.jsonl"},
  "facts": {"total": 421, "kinds": {}},
  "ticks": {"total": 8, "names": {}}
}
```

### Read implementation seams

- Bare store inventory and raw facts: `engine.StoreReader`.
- Vertex inventory, facts, ticks, and typed state: `vertex_summary`, `vertex_facts`, `vertex_ticks`, and `vertex_fold`.
- JSONL read resolution: `resolved_index`/`ensure_index`.
- Historical extensions: `resolve_witness_position`, `at=`, and `as_of=`.
- Store declaration provenance: `load_declaration_status` and `declaration_generation`.

## `loops emit`

### Interface

```text
loops emit story.vertex chapter.note \
  --observer kay \
  --data '{"chapter":4,"text":"Mara leaves before dawn."}'

loops emit services.vertex deploy --observer ci --data @deploy.json
loops emit notebook.vertex note --observer kay --data -
```

Options:

```text
--observer NAME     Required authorship identity
--data JSON|@FILE|- Required JSON object payload
--time RFC3339      Observation time; defaults to now
--origin NAME       Optional origin, empty by default
--format text|json  Receipt format
```

Deliberate exclusions from v1:

- No implicit interactive questionnaire.
- No primary `key=value` syntax or type guessing.
- No bare-store writes.
- No `_decl.*` emission through ordinary ingress.
- No conditional/CAS syntax until the engine supports real conditional admission.

### Write path

1. Resolve and validate the vertex.
2. Refuse combine/discover aggregates as write targets; require a concrete member.
3. Parse exactly one JSON object.
4. Construct `Fact.of(kind, observer, origin=..., ts=..., **payload)`.
5. Resolve the observer's declared grant and pass it to the engine when present.
6. Open a `VertexHandle` with a custody-backed, operation-fresh credential provider.
7. Call `VertexHandle.receive()` exactly once.
8. Return a receipt containing the fact ID, stored/rejected state, and any tick.

The engine's committed-error distinction must survive to the process boundary. If the fact committed but tick persistence or reconstruction then failed, output the fact ID, use a distinct nonzero exit, and say explicitly that the fact landed and must not be retried as uncommitted.

The CLI never generates keys as an emission side effect. Missing key material is an honest unsigned era. Key creation belongs to an explicit observer or vertex command later.

### Receipt JSON

```json
{
  "schema": "loops.cli/emit-receipt/v1",
  "id": "01...",
  "stored": true,
  "signed": null,
  "tick": null
}
```

`signed` remains `null` until the library receipt exposes the actual persisted signature state; the CLI must not infer it from the mere presence of local keys.

## `loops kind add`

### Interface and default

```text
loops kind add story.vertex chapter.note
```

The least presumptive useful default is:

```kdl
chapter.note {
  fold {
    items "collect" 100
  }
}
```

A bounded collect preserves a useful recent state without assuming identity, numerical meaning, lifecycle, or vocabulary. The complete fact history remains in the store.

Explicit fold grammar:

```text
--fold TARGET=collect:N
--fold TARGET=by:FIELD
--fold TARGET=latest
--fold TARGET=count
--fold TARGET=sum:FIELD
--fold TARGET=min:FIELD
--fold TARGET=max:FIELD
--fold TARGET=avg:FIELD
--fold TARGET=window:N:FIELD
```

Additional repeatable facets:

```text
--search FIELD
--preview FIELD
--edge FIELD=TARGET_KIND
--lifecycle FIELD=ACTIVE_VALUE[,ACTIVE_VALUE...]
```

`--fold` may be repeated because a kind can have an item fold plus scalar folds.

### Mutation sequence

1. Read the original vertex bytes.
2. Generate only the new kind block.
3. Insert it into `loops {}` while preserving surrounding authorial text. Create a new `loops` block when none exists.
4. Parse and validate the proposed complete document before any persistent change.
5. Refuse an existing kind unless a later `kind edit` command is used.
6. Determine declaration residence:
   - Pre-genesis: the file is authoritative; atomically replace it.
   - Adopted SQLite store: resolve current documents, calculate a subject-granular diff, and apply a signed `absorb_edit` guarded by the captured declaration head.
   - Adopted JSONL store: refuse until the library supports declaration edit ceremonies against the canonical log.
7. For an adopted store, persist an edit-intent record, apply the store edit first, then refresh the `.vertex` ingress/cache file. Clear the intent only after both agree.
8. Report the declaration generation before and after the edit.

Store-first ordering is intentional. After genesis, the store is authoritative; if the process dies before refreshing the file cache, normal reads still use the correct ontology and `vertex recover` can finish the cache refresh.

## Errors and exit status

| Exit | Meaning |
|---:|---|
| 0 | Completed successfully |
| 2 | Invalid invocation, JSON, timestamp, or output format |
| 3 | Missing/unsupported target or ambiguous ID prefix |
| 4 | Validation, policy, admission, or reserved-kind rejection |
| 5 | Conflict, lock, corruption, canonical disagreement, or I/O failure |
| 6 | Fact committed but the compound emit operation failed; do not retry blindly |

Errors should have stable machine codes in JSON, such as `target.unsupported`, `fact.prefix_ambiguous`, `emit.committed_error`, and `declaration.stale_head`.

## Package shape

The requested design folder is named `CLI v2`, but spaces and uppercase letters make it unsuitable as a Python import/package name. When implementation begins, keep planning material here and put importable code in a normalized child such as:

```text
apps/CLI v2/
  PLAN.md
  LIBS_CHANGES.md
  pyproject.toml
  src/loops_cli_v2/
    __init__.py
    main.py
    target.py
    output.py
    commands/
      read.py
      emit.py
      kind.py
```

Use the standard library's `argparse` initially unless a UI framework earns its dependency through concrete needs. Keep command functions callable without a terminal parser so tests and other clients share the same orchestration.

## Delivery phases

### Phase 0: executable skeleton

- Create package and console entry point under a temporary `loops-v2` name.
- Add target resolution and stable error/result envelopes.
- Add golden tests for text, JSON, and JSONL output.

### Phase 1: generic reading

- Implement inventory for vertex, SQLite, and JSONL targets.
- Implement raw interval facts, fact ID lookup, typed state, and ticks.
- Verify `_decl.*` exclusion and explicit inclusion.
- Test against domain-neutral fixtures: infrastructure and narrative data.

### Phase 2: emission

- Implement JSON/file/stdin payload ingestion.
- Compose custody credentials and declared observer grants.
- Use `VertexHandle.receive()` and preserve committed-error semantics.
- Test SQLite- and JSONL-canonical writes, boundaries, unsigned eras, signing, rejection, and aggregates.

### Phase 3: kinds

- Implement fold/facet parsing and KDL generation.
- Implement pre-genesis file edits.
- Implement adopted SQLite declaration edits with stale-head checking and recovery intent.
- Refuse adopted JSONL edits clearly until the library gap is closed.

### Phase 4: operational completion

- Add `vertex validate`, `vertex status`, and `vertex recover`.
- Add `store verify` and explicit FTS reindexing.
- Stabilize shell completions and man-page documentation.

## MVP acceptance criteria

- The existing CLI is not imported or used by CLI v2.
- Every bare store can be inventoried without a domain-specific configuration.
- Reading a JSONL target never mistakes its SQLite index for canonical truth.
- Default reads do not display declaration internals.
- A technical fact and a multi-paragraph narrative fact round-trip without loss.
- Every successful emit returns the exact persisted fact ID.
- No emit path writes `_decl.*` through ordinary ingress.
- A kind can be added before genesis and to an adopted SQLite vertex.
- Historical facts of a newly declared kind appear in the new fold state.
- Adopted JSONL kind edits fail loudly until supported.
- Machine output is stable, versioned, and contains no human diagnostics.

## Complete CLI direction

After the minimum is solid, grow by responsibility rather than accumulating unrelated top-level verbs:

```text
loops read       inventory, facts, state, ticks, search, graph, history, watch
loops emit       one fact, then NDJSON batch ingestion
loops kind       list, show, add, edit, retire
loops vertex     init, validate, status, diff, absorb, recover
loops observer   list, add, grant, keygen, verify
loops source     run, sync, watch
loops store      info, verify, reindex, slice, merge, receive, compact,
                 export, rebuild, rebirth
```

Interactive navigation and a TUI should consume the same versioned result models as the noninteractive CLI, not become a second semantic implementation.
