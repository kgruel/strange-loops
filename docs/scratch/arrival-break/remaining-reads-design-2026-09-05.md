# Remaining SDK reads: timeline, search, aggregates

Status: recommendation only. It describes next bounded slices; no currently
unsupported Arrival operation is implied to exist.

## Timeline: implement next

Keep `read_timeline` a **timestamp lens**, distinct from `read_facts`' receipt
order. For an Arrival descriptor, open one existing `CURRENT` `OpenedRead`,
validate the effective declaration from that snapshot, then obtain all bounded
ordinary facts and ticks from the same `QuerySnapshot`. Filter facts and ticks
by inclusive `start_ts`/`end_ts`, merge them, calculate `total_events` before
`limit`, and cap in the requested direction. No legacy reader, repair, or
second snapshot is allowed.

Event time is the primary sort key. Define deterministic ties with each row's
`(arrival_ordinal, arrival_seq, id)` in the requested direction; this is a
secondary presentation tie-breaker, not a claim that timelines fold by receipt
order. A backdated later receipt therefore appears at its timestamp while it
still folds last. Preserve the existing public start/end, limit, truncation,
and oldest/newest meanings. Add `read_path`, `store`, and `basis` to a v2
`TimelineResult`, and retain them on an empty time window. Existing legacy
results use `read_path="legacy"` and null Arrival evidence.

The first slice has no timeline continuation: a time-sorted cursor needs a
stable cross-type key and generation proof, which has not been designed. Test
backdated receipt behavior, fact/tick equal timestamps, a concurrent append
between capture and snapshot, missing/behind projection refusal, and basis
retention on an empty result.

## Search: typed capability after timeline

Replace `QuerySnapshot.search(request: Mapping[str, Any]) -> tuple[Fact, ...]`
with engine-owned values, for example:

```python
@dataclass(frozen=True)
class SearchRequest:
    query: str
    kind: str | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    limit: int = 50
    include_internal: bool = False

@dataclass(frozen=True)
class SearchMatch:
    fact: Fact
    rank: float | None       # adapter-local; never cross-backend comparable
    snippet: str | None      # untrusted display text

@dataclass(frozen=True)
class SearchPage:
    matches: tuple[SearchMatch, ...]
    total_matches: int
    truncated: bool
    ranking: str             # e.g. "sqlite-fts5-bm25"
```

`NotSupported` remains the honest answer when a backend has no declared search
capability. No ranked continuation belongs in this cut. SDK `SearchResult` v2
wraps the page with `read_path`, descriptor info, and `ReadBasis`; legacy keeps
its current explicit path. The request grammar and rank are adapter-defined,
so the SDK must not claim that SQLite FTS syntax or scores port to DuckDB.

A FileQuery implementation may use FTS5 only inside its already-open read-only
SQLite transaction. Join `facts_fts` to `facts`, require
`facts.arrival_ordinal <= snapshot.bound`, apply kind/internal/time filters in
SQL before `LIMIT`, and use one identical bounded predicate for count and
matches. Row filtering bounds membership, but **does not bound BM25**: later
indexed documents change corpus-wide IDF and average-length inputs even when
their rows are excluded. Therefore a result claiming H-relative ranks requires
an FTS corpus built exactly through H. Otherwise the API must expose a distinct
ranking basis P and say ranks are P-relative, or refuse ranked search. Generate
an FTS5 snippet as display text only.

Current Arrival projection rebuild explicitly drops `facts_fts` and
`fts_state`, and the File snapshot currently refuses search. A separate,
serialized search-maintenance addition must build/update FTS and write
coverage metadata: lineage, covered verified prefix, and a hash of the
**effective bounded declaration's searchable-field specification**. The query
requires exact `P == H` for H-relative BM25. A future separately-labelled
P-relative mode could accept `P >= H` when lineage and field-spec hash match,
but must return P as ranking evidence beside the row `ReadBasis`. A missing,
behind, foreign, declaration-mismatched, or rank-basis-incompatible index
refuses `NotSupported`/a named search-stale refusal. Reads never create,
rebuild, or silently scan payloads to imitate FTS. Tests need index absence,
declaration change, projection ahead of H, bounded concurrent append,
rank-corpus divergence, count/truncation, and raw snippet escaping by the CLI
renderer.

## Aggregates: separate coordinator slice

Aggregate capture is not a common-head operation. Resolve every declared
member occurrence to a `MemberIdentity` containing its composition path/alias
and descriptor/declaration identity; do not key by lineage. Open and retain a
CURRENT snapshot for each member, then compose only after all opens succeed;
on any refusal, close all and return no partial aggregate result. The result
carries `Mapping[MemberIdentity, ReadBasis]`, not one invented aggregate
ordinal, head, cursor, or view generation.

Same physical lineage through different vertices/declarations is supported:
each member retains its own provenance and may have a different represented
prefix. Deduplication is a named aggregate/fold semantic choice above this
coordinator, never a backend optimization. Aggregate timeline can merge by
timestamp with member identity as a tie-breaker; aggregate receipt ordering and
ranked search need declared aggregate semantics and should initially refuse.

## Ordered work

1. Add the basis-bearing single-store Arrival timeline and its real file tests.
2. Add typed search contract/DTOs and FileQuery FTS capability together with
   explicit search maintenance/coverage evidence; do not enable the SDK before
   those tests pass.
3. Add the member-identity aggregate capture coordinator and only operations
   whose cross-member ordering is explicitly defined.
