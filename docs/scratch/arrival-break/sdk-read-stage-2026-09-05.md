# Arrival completion stage 2B — SDK read integration

Date: 2026-09-05  
Status: implementation and adversarial review complete

## Result

The existing SDK read names now recognize an explicit Arrival descriptor
before legacy target probing. A supported descriptor must declare its backend
and instance role. Its store location remains an opaque string until the named
adapter receives it. The SDK opens the engine read coordinator with
`ProjectionRequirement.CURRENT`, returns the registry-attested basis and store
identity, and closes every opened snapshot on success or refusal.

`read_summary`, `read_facts`, `read_state`, `read_ticks`, and
`read_fact_by_id` have one result shape per function across both paths. Arrival
results carry `read_path="arrival"`, `ReadBasis`, and `StoreDescriptorInfo`;
legacy results carry the same wrapper with `read_path="legacy"` and
`basis=None`. Missing fact lookup still returns a basis-bearing result with
`fact=None`.

State reconstruction resolves declaration documents and user facts from one
bounded query snapshot. The current vertex file supplies residence only. The
resolver retains own-lineage selection, ignores foreign declaration genesis
rows, preserves the unhistorized floor, and refuses an effective aggregate.
Non-state operations use a bounded-prefix `_decl` subtree query to enforce the
same single-store declaration shape without scanning user facts. A resumed
fact page uses only the continuation-bound request.

Arrival continuations stay in-process. `FactPageResult.as_dict()` redacts the
engine value and exposes `has_continuation` rather than emitting an unprotected
wire token. Descriptor-backed aggregates, recursively nested descriptor
members, and unsupported descriptor operations refuse before any legacy
SQLite/index path opens. Reads do not materialize, repair, or advance a
projection.

## Public SDK changes

- Added `resolve_arrival_target`, `ArrivalTarget`, and
  `StoreDescriptorInfo`.
- Upgraded summary, fact-page, and fold-state schemas to v2 with read basis
  fields.
- Added `TickReadResult` and `FactLookupResult`; legacy tick/list and
  fact/dict-or-None callers now consume `.items` and `.fact` respectively.
- Added optional registry injection to the five supported read operations for
  adapter composition and deterministic tests.
- Kept search, entity resolution, timeline, and synchronization explicit:
  they currently raise `TargetUnsupported` for Arrival descriptors rather than
  fall through to legacy storage.

## Acceptance coverage

Tests cover opaque non-file locations, lack of suffix inference, explicit
roles, a common current read basis, exact close behavior, continuation reuse
against a request-enforcing adapter, safe continuation serialization,
same-snapshot declaration folding after the locator file changes, effective
aggregate refusal, recursive descriptor-member refusal, and unsupported
operation refusal.

Validation at handoff:

- SDK suite: **350 passed**
- Final Arrival SDK file: **21 passed**
- Engine Arrival consumer + contract + registry: **81 passed**
- Architecture: **101 passed**
- SDK Ruff, changed-module `ty check`, and `git diff --check`: passed

Claude Fable 5.1 first found a continuation contract defect, then approved the
corrected cut twice, including a final supplement containing the complete new
test file and FileQuery implementation. The review receipt is
`reviews/sdk-read-fable-2026-09-05.md`.

## Caller inventory and remaining integration

Repository-wide Python callsite inspection found chaos tests and the benchmark
characterizer using summary/page fields that remain present. No production
callsite consumes the changed tick or fact-lookup return shape. The functions
named `read_facts` and `read_ticks` in the migration package are separate
module-local legacy readers.

Aggregate Arrival reads remain pending until member-identity and member-basis
semantics land. Search, entity resolution, timelines, and explicit projection
maintenance need their own basis-bearing or maintenance contracts. The
transitional engine allowance for descriptors with `role=None` also remains;
this SDK boundary does not treat omission as Authority. Full-fidelity SDK
access to exact stored payload text, inner signatures, and tick-chain evidence
is also deferred to the stage 4 API design; the engine snapshot retains that
evidence for runtime and maintenance without changing the existing convenience
views.
