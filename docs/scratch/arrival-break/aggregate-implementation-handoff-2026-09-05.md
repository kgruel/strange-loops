# Aggregate capture implementation handoff

Status: primary's bounded follow-up for the agent finishing SDK search. This
expands the aggregate section of `remaining-reads-design-2026-09-05.md`; no
aggregate implementation is claimed yet.

## Existing meaning to preserve

`lang.ast.CombineEntry` retains name and optional alias. The loader forbids
combine plus a store, but discover may coexist with an own store. Member
declarations are observations when a member has an Arrival descriptor;
storeless composition declarations remain local file definitions and need
honest file fingerprints rather than invented custody heads.

Legacy `vertex_reader._combined_read` folds a UNION ALL, without lineage or
fact-ID deduplication. It defaults multi-store folds to `ByKey("ts")`, using
`atoms.ordering.totalize` and `resolve_key_field` for strict key semantics.
`_collect_source_specs` supplies child specs and parent specs override them.
`vertex_read` separately overlays own-store knowledge for a discover vertex
with a store. These are distinct composition semantics, not consequences of
sharing an SQLite connection. Source inventory must resolve inherited-spec
conflicts before implementing composition.

## First stage: capture only

Add an engine-owned, closeable aggregate capture coordinator. Accept an
already-resolved composition plan containing occurrence identities, locators,
and descriptors. Keep filesystem/name discovery and SDK result serialization
outside the ledger adapter. SDK planning may use existing `resolve_vertex`
and the existing LOOPS_HOME resolution convention, but must not call
`resolved_index`, legacy probe, or StoreReader for descriptor members.

An occurrence identity includes its path through composition entries (ordinal
and alias/name), resolved vertex locator and declaration identity. It is not
the lineage or resolved store pathname. The same member reached along two
branches, or two different vertices selecting the same physical lineage,
remains two occurrences. Detect cycles with the active recursion stack, not
a global visited set that accidentally deletes repeat occurrences.

For each member call the supported `open_read` and retain its CURRENT
snapshot and complete ReadBasis. Resolve member effective documents from
that same snapshot. Open all members successfully before returning a usable
capture. On any failure close every opened member and produce no partial
aggregate result. Empty discovery is a distinct, recorded empty membership;
an explicitly declared missing member is a refusal, not a successful empty
view. Reads perform no maintenance.

Sequential per-member capture is honest: there is no global instant or common
ordinal. Even two occurrences of the same lineage may capture different
heads. Freeze membership and local definition bytes/fingerprints for the
invocation; do not rediscover between count, data and fold operations. Retain
each member's own definition evidence independently. Include an own-store
member explicitly when the parent discover vertex has a descriptor.

Use an ordered list of member evidence entries in JSON. Encoding a mapping by
lineage loses occurrences, and stringifying a tuple key is not a portable
identity contract. No aggregate cursor, view generation or synthesized head.

Tests: two lineages; two distinct vertices on one lineage; repeated nested
member; true recursion cycle; later append between members; complete close on
second-member refusal; missing/behind projection unchanged; empty discovery
with definition evidence. Do not require or manufacture a single snapshot
across SQLite databases.

## Later composition stage

Implement state, summary and timeline only after capture acceptance. Keep the
existing named ordering rule; member receipt positions are provenance and
cannot be sorted as one cross-store receipt axis. Timestamp views can sort
with record identity and occurrence identity as deterministic ties, retaining
duplicate occurrences. For general `ByKey` reuse the shared strict key
family/type rules; occurrence identity extends only ties between identical
record IDs. Do not silently coerce missing or mixed keys.

Parent fold rules may reinterpret member facts. Preserve child spec inheritance
and parent overrides with explicit member declaration evidence. An own-store
overlay must not be silently changed to another UNION member merely because
the coordinator can expose it that way. Resolve its final semantics against
the existing read contract before wiring it.

Aggregate ranked search, receipt pagination and ambiguous scalar lookup stay
explicitly unsupported until their result/ordering semantics are defined.
Single-store SDK results remain unchanged. The new aggregate variants carry
composition definition evidence and the full list of member bases even for
empty results.
