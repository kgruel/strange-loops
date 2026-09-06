# Arrival FTS search implementation design

Status: recommendation only. No Arrival search surface exists yet; this is a
bounded file-adapter plan, not a portable rank contract.

## Decision

Add engine-owned values and change the private `QuerySnapshot.search` spelling
from `Mapping` to:

```python
@dataclass(frozen=True)
class SearchRequest:
    expression: str                 # adapter grammar; file advertises sqlite-fts5
    expected_fields_hash: str       # exact bounded declaration spec the caller used
    kind: str | None = None
    observer: str | None = None
    since: float | None = None
    until: float | None = None
    limit: int = 50                 # hard match-row maximum
    include_internal: bool = False

@dataclass(frozen=True)
class SearchMatch:
    fact: Fact
    rank: float                     # meaningful only with page.ranking
    snippet: str | None             # adapter-produced, untrusted display text

@dataclass(frozen=True)
class SearchPage:
    matches: tuple[SearchMatch, ...]
    total_matches: int
    truncated: bool
    ranking: str                    # first file value: sqlite-fts5-bm25
    ranking_through: Head           # exact corpus whose BM25 statistics were used
    fields_hash: str
```

`SearchPage` is returned only when `ranking_through ==` the opened
`ReadBasis.captured_head`; otherwise `FileQuerySnapshot.search` raises a named
search-stale refusal. This first cut deliberately has no P-relative ranking,
no ranked continuation, and no payload-substring fallback. The file request
accepts FTS5 MATCH grammar; another backend either publishes its own named
grammar/ranking or raises `NotSupported`. Scores never compare across adapters.

`SearchResult` becomes v2 for both paths: `read_path`, `store`, and `basis`;
Arrival additionally reports `ranking`, `ranking_through`, and `fields_hash`.
Legacy retains its current search behavior but reports null Arrival evidence.
The minimal CLI serializes these values and escapes snippets as display text.

## Same-basis declaration and field specification

Search fields are not inferred from a locator file or a legacy reader. A
private `derive_search_spec(effective_ast, declaration_documents, ingress_dir)`
receives the effective AST and documents already assembled by
`_arrival_declaration` from one `OpenedRead` snapshot. Before deriving, it
calls the existing pure `verify_source_pins_from_documents(documents,
ingress_dir)`: this validates template and parameter-file bytes against the
pins in the bounded declaration. It then resolves the declared searchable
fields from that effective AST, canonicalizes a `SearchFieldSpec` (field paths,
text normalization version, template-derived declarations, and relevant pinned
digests), and hashes its canonical JSON. It opens no store and does not
reindex. Unpinned/unreadable/drifted template input refuses; it is never
silently replaced by the live locator content.

The first implementation preserves the established pure field extractor:
dotted mappings, list strings and mapping `text` values, JSON rendering for
mappings, and scalar text conversion. Missing or null paths contribute nothing.
The extraction-version constant is part of the canonical spec hash, so an
intentional semantics change requires explicit rebuild rather than silently
altering the corpus.

## Explicit indexed-maintenance operation

Add an adapter-owned `SearchIndexMaintenance`, registered separately from
projection maintenance:

```python
build(through: Head, spec: SearchFieldSpec) -> SearchIndexBuild
```

`SearchIndexBuild` reports target, coverage before/after, fields hash, SQLite
schema-generation token, and `changed`. `SearchIndexSyncError` retains target,
coverage-before, observed-after, fields hash, and cause; it never claims a
successful index or custody commit.

A private coordinator opens the registry/attested ledger once, captures H from
the successful comparison, validates the requested target as a member prefix,
and opens a CURRENT snapshot at that target. The supported consumer derives and
pin-checks the effective spec from its already bounded declaration documents,
then passes that same H/spec to the coordinator. The coordinator never parses a
locator or reads a live template file. The File maintainer rechecks H against
the log before its serialized build.
The public maintenance entry may be `sync_search_index(target)`; it is distinct
from `sync_projection` and does not change its meaning. Reads only call
`search`; they never invoke this coordinator.

For File, `build` takes `BEGIN IMMEDIATE`, rechecks the projection watermark and
its exact H hash, then builds a separate FTS5 corpus from facts through H using
only the spec's fields. It atomically replaces `arrival_facts_fts` and
`arrival_fts_state`
with lineage, H ordinal/hash, fields hash, grammar/ranking versions, and schema
generation. Rebuilding the whole exact prefix per advance is intentionally the
first-cut cost: BM25 document count, average length, and IDF then describe H,
not a later corpus. A later append makes the index stale until explicit build.

Source check: current `FileProjectionMaintenance.catch_up` invokes
`_ensure_index_schema`, which creates base projection schema but does not itself
create or drop FTS; `rederive_projections` explicitly drops the Arrival search
tables and coverage state. The search owner must ensure any projection rebuild deletes search
coverage in the same transaction. It must not let a base-schema migration or
rebuild leave old FTS metadata usable.

## Read algorithm and races

`search_facts` opens one ordinary CURRENT `OpenedRead`, resolves effective
declaration/spec once, and calls snapshot search in that same SQLite read
transaction. The adapter compares `arrival_fts_state` lineage, full H hash, fields
hash, grammar/ranking versions, and schema token before executing MATCH. It
joins the FTS row to bounded `facts`, applies kind/observer/time/internal
filters, calculates count and `LIMIT + 1` from the same transaction, and uses
FTS5 `bm25`/`snippet`. Both returned rows and rank corpus are exactly H.

A projection advance after capture may be visible as a larger watermark but is
clamped by the existing opener; its FTS coverage cannot satisfy H unless it is
exactly H, so it refuses rather than leaking future rank statistics. A concurrent
search rebuild is serialized; an already-open SQLite snapshot is coherent, and
a later open sees either complete old or complete new metadata. FTS DDL changes
SQLite `schema_version`; the existing fact-page `view_generation` includes it,
so a fact continuation reopened after a search rebuild refuses as a changed
view rather than assuming compatibility. This conservative invalidation is
required even though fact rows did not change.

Tests should prove exact-H rank divergence from a future document, absent/stale/
foreign/spec-mismatched coverage refusal without writes, pinned-template drift,
count/truncation, filters, concurrent append/build behavior, rebuild
invalidation of a fact cursor, transactional failed-build identity, and snippet
rendering. Aggregate Arrival search remains explicitly unsupported.
