# C9 migration descriptor publication and adoption boundary

Status: implemented and validated; Fable-low and primary **ACCEPT**, no blockers.

This slice follows the accepted, uncommitted setup/recovery work on
`arrival/finish` at `50e37595`. It leaves that implementation intact. Sol owns
sidecar publication and regressions, Luna owns the migration-to-SDK boundary
workload and validation, Terra owns the explicit adoption design, and root owns
integration, review triage, and handoff.

## Finding and scope

The old sidecar omitted both lineage and role when publishing its descriptor.
More fundamentally, physical Arrival genesis does not supply a declaration
anchor: the current projection licenses `own_lineage` only after consuming an
`_decl.genesis` fact with the physical lineage as its ID. Migration preserves
legacy records, which do not establish that new anchor. This contradicts the
older slice 4 assumption that declaration genesis simply dissolves into mint.

The implemented slice makes descriptor publication explicit and rejects a
vertex changed after its transformation snapshot. It does not add an adoption
ceremony or silently turn the current locator file into canonical meaning.
The companion [adoption design](consistency-c9-migration-adoption-design-2026-09-06.md)
records the next append-forward operation and its identity decisions.

## Implemented publication boundary

- `run_migration` captures and parses one exact byte snapshot before transformation.
- The editor requires that snapshot and the physical lineage, quotes the new
  location safely, and verifies the parsed backend/lineage/authority tuple while
  retaining all non-store AST fields.
- The editor compares the snapshot at entry and immediately before replacement,
  then fsyncs the descriptor directory after replacement.
- Fresh, resumed, and report-verification opens supply explicit role/lineage.
  Registry lineage mismatches retain migration/report-specific refusal types.
- Existing explicit descriptors refuse fresh migration. An explicit resume of
  the exact already-published authority target re-verifies the migration and
  skips descriptor replacement; it still checks the captured descriptor bytes.
  It regenerates/re-signs/replaces the external report, whose tool version can
  differ on a repeated call; report immutability is not promised.

The exported editor's required `lineage` and `expected_original` arguments are
an intentional direct-call compatibility change. `run_migration` keeps its
existing signature and does not create an adoption anchor.

## Contract limits

The migration descriptor's authority role expresses operator intent and is
checked by the registry; it does not create observer authorization or supply a
historized declaration. Public target resolution, structural verification, and
explicit projection sync can succeed. Declaration-dependent reads and writes
must still refuse. Migration report verification checks its signed completion
head against the live target; a later adoption will advance beyond that head.

Input byte checks detect intervening changes at their check points. They do not
provide cross-process exclusion or guarantee a concurrently changing source is
quiescent. Publication uses the existing atomic replacement boundary plus directory fsync.
An error after replacement may leave the new descriptor visible and must not be
interpreted as an unmodified target. No new
recovery intent, live cutover coordinator, or arbitrary power-loss claim is
introduced here. Refusal after staging can leave valid target/report evidence;
it is not a zero-side-effects promise.

All exercised stores and credentials are synthetic and isolated. No user store
has been selected or migrated, and no original/live writer has been touched.

## Validation and review

Baseline migration suite: 69 passed. Publication regressions: full migrate
74 passed, focused sidecar 27 passed. Regression coverage includes exact
fresh/resumed descriptors, already-published resume without replacement, a
changed declaration during transformation, a change during temp-file fsync,
quoted/backslash location spelling, and preexisting authority/replica refusal.
These are in-process seam injections and seeded partial-state tests, not
subprocess-kill or arbitrary power-loss experiments.

The new repository integration test exercises both synthetic JSONL and SQLite
histories through the published descriptor. It keeps SDK dependencies free of
the quarantined migration package. Final combined migration and integration suite: **76 passed** (74 migrate +
2 boundary cases); architecture **101 passed**; legacy CLI migration caller
compatibility **9 passed**. Scoped Ruff and whitespace checks pass. All commands
use isolated state/configuration roots. No SDK runtime production changed in
this slice, and no new quarantine dependency was added to SDK.

The boundary tests compare complete migrated fact/tick envelopes, verify the
external signed report at its completion head, assert exact SDK store/head and
post-sync projection evidence, and require declaration-dependent
summary/facts/ticks/lookup/inspection/edit/emission to refuse with the source,
ledger, and descriptor bytes intact. These use public in-process SDK calls and
injected test credentials; they are not minimal-CLI or subprocess conformance.

Native text logs, commands, statuses, and validated source hashes are archived
in the [review evidence](reviews/consistency-c9-migration-publication-final-2026-09-06/validation-evidence).
Fixture stores and private keys are excluded. Fable 5.1 LOW and primary verdicts:
**ACCEPT**, no implementation or design blockers. The frozen packet is
226,316 bytes, SHA-256
`50cb3e69f5e351bc72414cf03edd76db6b66983045fd87fba015a36083742eac`.
All frozen sources matched before triage. Only maintained documentation was
clarified afterward; production/tests remained unchanged. See the
[primary triage](reviews/consistency-c9-migration-publication-final-2026-09-06/primary-triage.md)
for observations and deferred work.
