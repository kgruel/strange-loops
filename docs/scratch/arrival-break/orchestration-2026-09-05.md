## September 7: Atlas greenfield CLI guide tested and accepted

Checkpoint **d4e5792d** committed both prior accepted slices (setup/recovery and
migration descriptor publication). Nothing pushed. The subsequent user request
for a focused greenfield how-to is complete as uncommitted documentation only:
[guide](../../guides/atlas-greenfield-cli.md), linked from apps/loops-min/README.md,
plus [native replay record](atlas-greenfield-guide-2026-09-07.md) and review evidence.
No runtime fixes were needed.

Root authored the guide, Terra audited Atlas's generated configuration contract,
Sol reviewed the CLI/instructions, Luna executed its six Bash blocks as a script
from ~/Code/gruel.network/docs/atlas, and root checked exact receipt/data/export
evidence. Fresh isolated UV environment and roots; **14 successful CLI calls**.
The example captures the complete photograph graph as a fact, then folds notes
by subject while retaining both question/follow-up payloads in history. Exact
init1 → declaration2 → atomic batch3 → follow-up4 commit continuity, per-item
signed/stored/witnessed evidence, final read/verify/sync/export head agreement,
and byte-identical captured export all passed. Existing Atlas browser, generated
inputs and stores were untouched by this task; no gruel code was committed or
pushed. A later concurrent edit to scripts/generate-docs.py was left alone.

Fable-low initially requested script-vs-interactive instruction clarity; fixed
in prose without changing executed commands. Its second claim that declaration
head/phase fields were missing was contradicted by native output; Fable withdrew
it on correction. Final Fable-low and primary **ACCEPT**, no blockers. Current
six Bash blocks still match the native script exactly. The guide correctly limits
verification, export, recovery examples and future Atlas integration claims.
Private keys, stores, complete fixture receipts and virtual environments are not
in the repository; only selected text evidence is archived. No jobs remain.

Next: checkpoint the guide when requested. The remaining runtime implementation
work is still the reviewed append-forward declaration adoption ceremony and
recovery, then mapped SDK integration and a representative-copy migration
rehearsal. Fresh greenfield init already supplies the declaration anchor; the
how-to does not depend on that future adoption path.

Earlier entries below preserve their status at the time of writing.

## September 7: checkpoint setup/recovery and migration publication

This checkpoint includes both accepted slices below: SDK-owned credential
lifecycle outcomes/minimal-CLI setup and recovery, and explicit migration
descriptor publication with its reviewed adoption design. Production/test hashes
still match their accepted review packets; no tests were repeated for this
checkpoint-only change. Nothing pushed.

The next user-directed task is a focused, tested greenfield loops-min how-to for
`~/Code/gruel.network/docs/atlas`. Fresh initialization already establishes the
declaration anchor; existing-store adoption remains the next implementation
slice after that documentation exercise. Preserve the existing atlas/homelab
stores while exercising a separate fresh store.

Earlier entries below preserve their status at the time of writing.

## September 6: C9 migration publication accepted; explicit adoption next

The setup/recovery slice below remains intact and uncommitted on `arrival/finish`
in `loops-wt/arrival-finish` at `50e37595`. This subsequent publication slice is
also **uncommitted**; nothing pushed. Sol implemented sidecar hardening, Luna
owned the repository integration boundary, Terra drafted/reviewed adoption
identity decisions, and root integrated evidence, Fable-low review and triage.
No real user store, credentials, or live writers were touched. A representative
store has not been selected; no real-copy rehearsal has run.

The old sidecar did not publish lineage/role and did not create the current
runtime's declaration anchor. The first gap is now fixed: published descriptors
name File + physical lineage + authority role. One exact vertex byte snapshot
feeds transform and publication checks, including a second check immediately
before replacement; paths are safely quoted and parsed claims verified. The
descriptor directory is fsynced after replacement. Internal fresh/resume/report
opens pin lineage/role and preserve typed mismatch refusals. Existing descriptors
refuse except exact explicit already-published authority resume, which re-verifies
and skips descriptor replacement but **regenerates/re-signs/replaces the report**.
The exported editor now requires `lineage` and `expected_original`; the ordinary
run_migration signature is unchanged. Previous sidecar descriptors missing claims
are deliberately not silently upgraded.

The central remaining gap is explicit declaration adoption. Physical Arrival
mint does not provide an `_decl.genesis` fact whose ID equals the new lineage.
Historical declaration facts stay evidence; the SDK will not substitute the
locator as canonical meaning. Synthetic JSONL and SQLite workflows prove public
resolution/Full verification/sync succeed, while summary/facts/ticks/lookup/
inspection/edit/emission refuse the missing anchor without changing source,
ledger or descriptor. The future adoption must append forward from a selected
head using an explicitly reviewed snapshot and mapped captured-key proof;
existing-anchor/ID/current-lineage-overlay collisions refuse. Separate FACT and
ARRIVAL signatures and durable planned-draft recovery are required. Registry
signatures must verify in ARRIVAL_DOMAIN; the current production legacy wrapper
already uses that domain. See the adoption design for the finite worklist.

Validation: combined migration + repository boundary **76 passed** (74 + 2),
architecture **101**, legacy migration CLI **9**, scoped Ruff/whitespace pass.
No SDK runtime production changed in this slice. In-process seam failures and
seeded partial-state tests do not claim subprocess crashes. Byte checks require
quiescent inputs and are not CAS. An error after rename can leave the descriptor
visible; no durable multi-artifact cutover or power-loss guarantee is claimed.
Native logs/statuses/hashes are archived without fixture stores/private keys.
Fable 5.1 LOW and primary verdicts **ACCEPT**, no blockers. Frozen sources matched
before minor maintained documentation clarifications; production/tests are still
exactly the reviewed versions. No jobs or reviews remain running.

Next: checkpoint both accepted uncommitted slices when requested. Then implement
the shared declaration-anchor builder and explicit adoption preparation/intent/
apply/recovery, followed by SDK mapped binding integration and a copy-rehearsal
orchestrator. Do not treat current `loops store migrate` as a complete adoption
workflow. Historical report verification through selected S, report signing
policy/provenance, live cutover coordination, source CLI transition and legacy
retirement remain explicit separate work.

See [publication report](consistency-c9-migration-publication-2026-09-06.md),
[adoption design](consistency-c9-migration-adoption-design-2026-09-06.md), and
[review triage](reviews/consistency-c9-migration-publication-final-2026-09-06/primary-triage.md).

Earlier entries below preserve their status at the time of writing.

## September 6: C9 setup/recovery accepted; checkpoint and migration adoption next

The C9 setup/recovery slice is complete on `arrival/finish` in
`loops-wt/arrival-finish`, based on `50e37595`. Changes are **uncommitted**;
nothing pushed. Sol implemented CLI commands and boundary tests, Terra owned SDK
lifecycle outcomes and regressions, Luna owned process initialization conformance
and suite validation, and root integrated process binding tests, installed wheels,
review triage and evidence. No live stores or credentials were touched.

`loops-min` now adds `init-recover TARGET` plus `credential-create`,
`credential-recover`, `credential-bind-existing-ref`, and `credential-import-legacy`.
Initialization recovery reads its reserved intent without credentials or scaffold
overrides. Success removes the intent; repeated recovery refuses without mutation.
Binding commands use exact root/namespace/observer/token via public SDK methods;
receipt selection remains a writer concern. SDK result DTOs retain former public
attributes but change concrete result type; dedicated lifecycle errors replace raw
custody errors for SDK callers. Binding incomplete outcomes use CLI6 with token,
known key_ref/phase or explicitly unknown phase, never an invented Arrival Commit.
Conflict/recovery-required use CLI4, which is not a zero-effects guarantee.
Inherited mapped resolution and optional unsigned policy are unchanged.

Fable-low initially found one real blocker: raw custody TypeError from malformed
JSON lost request evidence as CLI70. Terra added it to the existing narrow
OSError/ValueError incomplete fallback. Actual malformed pending/intent records,
post-marker TypeError recovery, and an actual CLI failure are covered. A native
in-memory negative control restores only the old catch tuple: three TypeError
regressions fail while OSError passes. Corrected Fable-low and primary verdicts
are **ACCEPT**, no remaining blockers. Both review packets remain immutable and
sources matched closure; only maintained status/handoff changed afterward.

Final corrected validation: **SDK599**, **CLI30**, **architecture101**,
**custody binding/recovery31**, focused SDK60; scoped Ruff and whitespace pass.
The architecture/custody runs precede the narrow TypeError correction; SDK/CLI
and installed modular wheels were rerun afterward. Installed console binding
create/replay/recover/reuse → init → emit → declaration → read → verify passes
outside checkout without legacy loops or Painted; four production hashes match.
Only explicit text logs/scripts/status are archived, never fixtures or keys.
No running tests, agents or reviews remain.

Next: checkpoint this slice when requested, then reconcile migration sidecar
publication with current descriptor adoption before rehearsing on a selected
representative store copy. The old sidecar store-clause editor writes location/
backend without the explicit role required by the current SDK resolver; the old
wrapper is not yet a complete current adoption workflow. Keep original stores
and live writers untouched during the copy rehearsal. Source execution is the
next substantial CLI transition; deliberate legacy retirement remains open.
No migration implementation or rehearsal started in this slice. See the
[setup/recovery report](consistency-c9-setup-2026-09-06.md).

Earlier entries below preserve their status at the time of writing.

## September 6: C9 first writer transition complete; setup/recovery next

Checkpoint `f45f1f03` contains the accepted captured-transfer SDK workload.
This subsequent C9 slice is complete on `arrival/finish` in
`loops-wt/arrival-finish`, based on that checkpoint, and is included in this
checkpoint; nothing pushed. Sol implemented the client and boundary tests, Luna added
process conformance and validated suites, Terra inventoried authority paths
and fixed the residence mismatch, and root integrated SDK input normalization,
wheel validation and review triage.

`loops-min` now exposes `init`, `emit`, `emit-batch`, `declaration`, and
`declaration-recover`. Writers require explicit mapped credential root,
namespace and receipt observer. Init forces Arrival File; emission uses public
SDK descriptor classification and one SDK write. The mapped SDK guard prevents
legacy fallback even after a descriptor replacement. The precheck does not pin
a different valid Arrival descriptor across the later SDK parse; no stronger
identity continuity is claimed. Recovery accepts an intent without credentials.
Strict JSON and finite CLI timestamps are transport validation; semantic input,
admission, signing, custody outcomes and serialization stay in the SDK.

Two real integration failures were corrected: SDK batch mapping conversions
now report InvalidEmissionRequest before target resolution instead of raw
Python errors; declaration residence comparison uses the same File-location
rule as descriptor construction, allowing unchanged absolute symlink paths.
Relative and opaque residence behavior remains as defined by those resolvers.

Mapped selection does not impose mandatory signatures. A missing optional
binding can produce an unsigned observation without minting keys; a present
unauthorized key refuses against captured authorization. Mapped init requires
a founding binding. Tests distinguish these cases and retain exact Commit,
complete read rows, projection heads and committed/unknown error evidence.
Boundary injection tests are not subprocess-crash claims; the prior SDK
conformance provides actual declaration interruption/recovery coverage.

Validation: final CLI **20 passed** /7.45s, full SDK **590 passed** /32.93s,
architecture **101 passed** /7.83s, engine declaration custody **14 passed**
/0.15s. Scoped Ruff and whitespace pass. A fresh modular-wheel installation
without legacy loops or Painted passes init → emit → declaration → read →
verify outside the checkout. Exact source hashes and native logs are archived
without fixture stores or keys. Fable 5.1 LOW and primary verdicts: **ACCEPT**, no blockers. Frozen sources
matched at closure; afterward only optional documentation clarifications and
maintained status/handoff changed. No jobs remain.

See the [C9 report](consistency-c9-transition-2026-09-06.md) and its authority
inventory. **C9 retirement remains open:** no legacy runtime path was deleted.
Next bounded work is process initialization recovery and SDK-owned serializable
credential-lifecycle outcomes before adding binding commands. Source execution
is the next larger caller transition. Inventory named old-command consumers
before removing wrappers/entry points, generic legacy SDK arms, suffix paths
or JsonlStore; reanchor has no Arrival successor and is slated for removal.
Projection rebuild, empty-receiver import, foreign admission, descriptor
adoption and live migration remain separate. No next slice began here.

Earlier entries below preserve their status at the time of writing.

## September 6: captured transfer conformance complete; C9 transition next

The fourth agreed public SDK workload-conformance slice is complete on
`arrival/finish` in `loops-wt/arrival-finish`, based on `3152e810` and included in this
checkpoint; nothing pushed. Sol implemented the
workflow, Terra audited contracts/guidance, Luna validated suites, and root
tightened byte/row evidence and triaged the frozen Fable-low review. No
production change was needed.

Mapped initialization and public export establish an initial exact copy;
a replica descriptor is explicit fixture setup because public empty-receiver
import is still pending. The receiver first syncs that initial prefix. Source
emission then creates a selected head and advances again. Historical export
after that advance reports distinct captured and selected heads; the bytes
exactly match the retained selected source and exclude the later observation.

An old selected-head restore refuses with HeadRollback without changing the
receiver ledger or descriptor. Fresh restore uses the live source descriptor
and appends through the locally witnessed head. It preserves the entire prior
prefix and receiver role. Full verification succeeds while CURRENT read still
refuses ProjectionBehind; explicit sync reports the initial projected head
and advances it to the restored head. Complete internal/domain reads match
source and receiver, including unchanged prior declaration rows. Repeated
restore is a no-op with no invented Commit. Export is not an import API or
a way to lower the witness floor.

Fable 5.1 LOW and primary verdicts: **ACCEPT**, no blockers or source
corrections. All frozen sources matched at closure; only maintained
status/handoff prose changed afterward. No jobs remain.
Native validation: focused transfer/export/restore **16 passed** /0.49s;
full SDK **583 passed** /20.96s; architecture **101 passed** /5.67s; engine
transfer/restore **55 passed** /0.38s. Scoped Ruff and whitespace pass.
Every test process isolates XDG state/config and LOOPS_HOME; explicit logs
are archived without stores/keys. Test SHA-256:
`5103a21f0bf0cabb65b3e3a3b3d95426619ec8f0f1022b6958f205fd58746d83`.
See the [report](sdk-conformance-captured-transfer-2026-09-06.md).

**Next bounded step:** C9 transition inventory and first CLI slice selection,
using the established delegation/review pattern. Compare supported public SDK
operations with `apps/loops-min` commands and legacy callers, then choose the
smallest process workflow that can use the proven SDK contracts. The minimal
client still reserves init/emit/emit-batch/declaration as unavailable despite
those SDK contracts now existing. Keep serialization and outcome semantics in
the SDK; retire old authority paths only with surviving consumers covered.
No C9 implementation began here. Larger projection preserve/rebuild recovery,
empty-receiver exact import, foreign admission, descriptor adoption and live
adoption remain separate work. This completes the four agreed conformance
workloads, not every scenario on the consistency matrix or the full roadmap.

Earlier entries below preserve their status at the time of writing.

## September 6: source failure conformance complete; captured transfer next

The third public SDK workload-conformance slice is complete on `arrival/finish`
in `loops-wt/arrival-finish`, based on `d75aae9e`, and included in this
checkpoint; nothing pushed. No production change was needed. Sol built
the workflow, Terra audited contracts/guidance, Luna validated suites, and root
tightened causal/persisted-evidence assertions and triaged the frozen Fable-low
review. The main checkout is clean and no jobs remain.

The mapped strict workflow installs an elapsed upstream source and a triggered
downstream source through public initialization/declaration editing. A forced
first invocation commits both tiers while the downstream reports SourceError,
either before yielding or after one observation. Public reads account for the
exact receipt-order IDs, returned/persisted bodies and error lifecycle evidence.
Tier commit predecessors, capture/projection coordinates and bounded Full
verification align. Controlled lifecycle times keep cadence deterministic.

A fresh non-forced invocation with a reconstructed mapped provider skips the
upstream from its persisted success and runs only the downstream from its
persisted trigger. All previously read rows remain unchanged. Before-yield
failure leaves one downstream observation after the successful retry;
after-yield failure leaves two logically identical observations with distinct
fact IDs. This is fresh collection, not a resume token or automatic semantic
deduplication. External effects remain a collector/application concern. The
README now makes source-error durability conditional on the actual outcome.

Fable 5.1 LOW and primary verdicts: **ACCEPT**, no blockers or review corrections.
Final focused SDK **28 passed** /0.99s; full SDK **582 passed** /23.30s;
architecture **101 passed** /6.79s; engine source/coordinator regressions
**30 passed** /0.78s. Scoped Ruff and whitespace checks pass. Every test process
isolated XDG state/config and `LOOPS_HOME`; no live stores/keys were used.
The accepted test SHA-256 is
`ac1513bd080f907e3f7722602f9a520475f9e315b9612abe152048363f27f48e`.
Only status/handoff prose changed after review. See the
[report](sdk-conformance-source-resumption-2026-09-06.md) and its final triage.

**Next bounded slice:** captured-prefix export → restore forward → verify →
explicitly sync → read, using the established Sol/Terra/Luna implementation and
Fable-low final-review pattern. Start from existing public SDK transfer/restore
tests and contracts; distinguish retained selected prefix from later source
advance and receiver custody from its projection. Source unknown-append,
known-uncommitted, collection interruption, projection and dispatch outcomes
retain their existing separate tests; this completed workload covers durable
source errors. C9 SDK/minimal-CLI transition and legacy retirement, plus larger
maintenance/transfer/adoption work, remain separate. Resume after the user's
compaction; no next slice began here.

Earlier entries below preserve their status at the time of writing.

## September 6: declaration recovery conformance complete; source tiers next

The second public SDK workload-conformance slice is complete and checkpointed
on `arrival/finish` in `loops-wt/arrival-finish`, based on `2d4d2d0a`. No
production change was needed. Sol implemented the isolated mapped workflow,
Terra audited contracts/guidance, Luna validated suites, and root tightened
semantic controls and triaged two frozen Fable 5.1 LOW reviews.

The workflow starts strict: `note` refuses before declaration. A public edit
adds that kind and deterministically interrupts after append. Its committed
head and public intent are retained while the old cache and stale projection
remain. Inspection refuses without repairing; another edit refuses on
ProjectionBehind before custody entry. Public recovery, with mapped resolution
and legacy credential acquisition poisoned, publishes the declaration without
advancing history. It retains the original basis and exact fact IDs; fresh
inspection and a complete internal fact list agree. Repeating the proposal is
a no-op. A reconstructed mapped provider then signs a successful `note` write,
and its commit, read/projection basis and bounded Full verification align.

Initial and follow-up Fable-low/primary verdicts are **ACCEPT**, no blockers.
Optional refinements added explicit hook firing, exact one-record advancement,
complete projected fact IDs and no-op head. Final test SHA-256:
`75260f0bdaad5a140f61bd04203934e33c7a63b0926ca87f28ae81515b8a4563`.
Full SDK **580 passed** /21.79s; architecture **101 passed** /6.20s before only
those assertion refinements. Final focused **49 passed** /1.28s, Ruff and
whitespace checks pass. All test processes isolated XDG state/config and
LOOPS_HOME. No live stores or keys were used; nothing pushed and no pending jobs.

The [report](sdk-conformance-declaration-recovery-2026-09-06.md) links native
logs and final triage. This is after-append exception conformance, not a
process/power-loss test, every recovery phase, or restore-forward. Resume after
the user’s compaction. **Next bounded slice:** run sources with partial failure,
inspect persisted tiers, determine what can safely resume, using the established
Sol/Terra/Luna and Fable-low pattern. Then captured-prefix export → restore
forward → verify → explicit sync → read. C9 transition/retirement and larger
maintenance/transfer/adoption work remain separate. No next slice began here.

Earlier entries below preserve their status at the time of writing.

## September 6: two-observer SDK conformance checkpoint; declaration recovery next

The first public SDK workload-conformance slice is complete on `arrival/finish`
in `loops-wt/arrival-finish`, based on D0/D2 checkpoint `a36487dc`. This checkpoint
contains the accepted tests, guidance and review evidence; nothing pushed.
No production change was needed. Sol added the
executable lifecycle, Terra audited relocation and updated SDK guidance, Luna
validated the SDK/architecture suites, and root independently reproduced and
triaged the adversarial review finding.

The flow prepares mapped Alice/Bob bindings, initializes Arrival, grants Bob's
explicit public key, emits a mixed-author batch, and matches commit/read/Full
prefix evidence. It moves a byte-identical descriptor retaining an absolute
store location, reconstructs the provider, and continues writing as Bob with
the same keys and history. Refusal controls cover ungranted Bob, wrong-namespace
Alice, and a case-distinct undeclared Alice. This is a fact-read and verification
workflow; it does not claim every SDK read surface or relative-location moves.

Fable-low initially returned REVISE: a generic credential refusal could let the
wrong-namespace test pass on provider failure. Root reproduced that false
positive. The corrected test checks the exact captured-authorization refusal,
request and key evidence; a write-time broken resolver now fails the test.
Focused follow-up Fable-low and primary verdicts are **ACCEPT**, no blockers.
All code/test hashes match the accepted packet. No jobs remain.

Validation: full SDK **579 passed** /17.53s; architecture **101 passed** /6.02s
before assertion-only review corrections. Final focused mapped/workload suite
**13 passed** /1.09s and Ruff passed after those corrections. Every test process
isolated XDG state/config and `LOOPS_HOME`; no live stores or keys were used.
Review packets, original REVISE, correction probes and final acceptance remain
in the [workload report](sdk-conformance-two-observer-2026-09-06.md).

**Next bounded slice:** interrupt a declaration edit, recover, inspect, and
continue writing through public SDK operations, using Sol/Terra/Luna and
Fable-low review. Follow with partial source tiers and captured-prefix export,
restore-forward, verify, explicit sync and read. These are conformance
prerequisites; C9 SDK/minimal-CLI transition and legacy retirement remain
separate, alongside the larger maintenance/transfer/adoption roadmap. Do not
automatically migrate live stores. Resume the next slice after the user's
compaction; no declaration-recovery implementation began in this checkpoint.

Earlier entries below preserve their status at the time of writing.

## September 6: D0/D2 checkpoint; resume with public SDK workload conformance

This checkpoint contains the accepted D0/D2 implementation, recovery/durability
corrections, native validation, and all Fable-low review/primary-triage artifacts.
The working branch is `arrival/finish` in `loops-wt/arrival-finish`; its parent is
`39bf05d7`. No push or live-store/key migration is part of this checkpoint.

**Next after compaction:** use the established Sol/Terra/Luna delegation and
Fable-low final review pattern for a bounded public SDK workload-conformance
slice. Begin with an isolated two-observer lifecycle: prepare mapped bindings,
initialize a lineage, introduce the second observer, emit a mixed-author batch,
read and verify, then move the vertex descriptor and repeat credential selection
and an authorized write. Exercise public SDK calls and reuse existing integration
fixtures. Preserve exact observer labels, explicit custody namespace, independent
captured authorization, domain separation, and honest outcome evidence. This is
the next agreed direction; no conformance implementation began before compaction.

Follow with declaration interruption/recovery, partial source tiers, and captured
export/restore/sync/read workflows as bounded slices. The larger maintenance,
transfer, descriptor adoption and C9 transition work remains as described in the
completion worklist. The default legacy provider is still supported; mapped
credentials remain opt-in. All tests must keep isolated XDG state/config and
LOOPS_HOME. No real credentials or live stores are required for this next slice.

D0/D2 evidence: engine 2,611 passed / 1 skipped; SDK 578 passed; final custody
81 passed; signing 40 passed; architecture 101 passed. SDK validation predates
only the last custody recovery/durability corrections, covered by the final
custody suite. Final Fable-low and primary verdicts ACCEPT; no jobs remain.
Checkpoint whitespace checks pass for source, tests and maintained docs. Frozen
review packets/raw logs retain their original whitespace and hashes; the staged
whole-tree check reports those archival bytes rather than rewriting evidence.
See [implementation](consistency-d0-d2-2026-09-06.md) and
[final triage](reviews/consistency-d0-d2-durability-followup-2026-09-06/primary-triage.md).

Earlier entries below preserve their status at the time of writing.

## September 6: D0/D2 complete and accepted; ready to checkpoint

D0/D2 is complete in `loops-wt/arrival-finish` on `arrival/finish`, based on
`39bf05d7`, and remains uncommitted. The opt-in mapped provider selects keys by
explicit namespace and exact observer, with domain/purpose requests separate
from engine-owned captured authorization. Runtime, batch, source-tier and
declaration writes verify mapped public evidence after capture. Initialization
loads pre-created bindings; creation/import/reuse/recovery are explicit custody
operations. Default legacy callers remain supported without automatic migration.

Sol implemented engine integration, Terra implemented custody/SDK and recovery,
Luna covered public SDK flows, and root integrated validation and independent
probes. Design Fable-low returned REVISE; its corrections were incorporated.
The first broad implementation ACCEPT was overridden by two root recovery
reproductions. Focused recovery REVISE exposed a fresh-token bypass, then ACCEPT
confirmed its fix. Root's final directory inspection exposed parent-entry and
linked-binding sync gaps. The durability review returned REVISE for the remaining
imported-key branch; the last focused Fable-low review and primary triage now
both **ACCEPT**, with no outstanding blockers or review jobs.

Measured validation: engine **2,611 passed / 1 skipped**, SDK **578 passed**,
final custody **81 passed**, sign **40 passed**, architecture **101 passed**.
The SDK run predates the last custody-only recovery/durability corrections,
covered by the final full custody suite. Scoped Ruff and diff checks pass.
Tests use isolated state/config/Loops roots. No real credentials or live stores
were migrated; nothing was committed or pushed, and the main checkout is clean.

See the [D0/D2 report](consistency-d0-d2-2026-09-06.md),
[validation report](consistency-d0-d2-validation-2026-09-06.md), and
[final review triage](reviews/consistency-d0-d2-durability-followup-2026-09-06/primary-triage.md).
Checkpoint when requested; next roadmap work is workload conformance, explicit
maintenance/transfer completion and adoption, followed by C9 once its SDK/CLI
retirement conditions are met. Earlier entries below preserve historical status.

## September 6: C7 resolver continuation complete; handoff to D0 → D2

C7 is checkpointed as `f5563d2f` (`feat(arrival): inspect bounded aggregate
declarations`). The user then authorized the small aggregate-read resolver
continuation before compaction. This follow-up checkpoint contains the bridge
simplification, public regressions, native validation and Fable-low acceptance.

Summary/state/timeline now use the explicit aggregate descriptor opt-in rather
than catching refusal and reparsing. Tests replace the locator with another
valid descriptor during the target parser and retain the original residence,
lineage and effective plain-root results. An in-memory pre-fix function probe
fails all 3 by opening the replacement missing residence; current code passes.
The earlier storeless predicate and later aggregate planner remain separate
observations. No claim of an entire read using one filesystem snapshot is made.

Validation: focused surrounding tests **65 passed**, full SDK **562 passed**,
architecture **101 passed**, scoped Ruff clean. After a test-only refinement
making the replacement syntactically valid, all **3** regressions and scoped
lint passed again; production was unchanged. All continuation validation used
process-level temporary state/config/Loops home paths. The inherited suite is
not assumed isolated just because the new test module has an autouse fixture.

Fable 5.1 LOW returned ACCEPT, no blockers. Root corrected an over-broad reviewer
claim that downstream aggregate execution never rereads the locator; the
accepted guarantee is limited to the descriptor bridge. No post-review code
changes or pending jobs. Reports:
[continuation](consistency-c7-followup-2026-09-06.md),
[validation](consistency-c7-followup-validation-2026-09-06.md),
[review triage](reviews/consistency-c7-followup-2026-09-06/primary-triage.md).

**Next after compaction: D0 design → D2 implementation/compatibility.** Start
with [identity decisions D0/D2](identity-decisions-2026-09-06.md). D0 defines
provider-owned explicit custody namespace + exact observer + signing domain,
separate from captured-lineage/H/successor verification context. D2 persists
verifiable bindings, preserves existing flat/nested keys and ambiguity refusals,
and specifies concurrent creation/recovery. C4's key-dir refusal is already
implemented; older recommendation language in D2 is historical. No credentials,
keys, live stores, or D0/D2 code were changed in this continuation. Nothing pushed.

The established Sol/Terra/Luna delegation and Fable review pattern continues;
C6's HIGH design review was explicitly requested for C6, not a standing HIGH
requirement. Do not start D0/D2 until the user resumes after compaction.

Earlier entries below retain historical status.

## September 6: C7 checkpoint; aggregate-resolver continuation next

The user requested checkpointing C7, then finishing the small aggregate-read
resolver continuation before compacting for D0 → D2. This checkpoint contains
C7 production/tests, validation, Fable-low acceptance and complete triage.
The continuation has not begun in this commit. Nothing pushed.

Next continuation: reuse the explicit aggregate descriptor opt-in in
summary/state/timeline resolution, replacing the catch-and-reparse bridge.
Test replacement during parsing and preserve role/default single-store guards.
Use the established delegation and Fable-low review pattern. D0/D2 starts only
after the user's planned compaction.

Earlier entries below retain their historical status.

## September 6: C7 complete and accepted; ready to checkpoint

C7 bounded aggregate declaration inspection is complete on `arrival/finish`,
based on C6 `1c37ca65`. Sol implemented shared parsed-root resolution, Terra
inspection/DTOs and integration tests, Luna independent acceptance/validation,
and root reconciled the contract and adversarial findings. Fable 5.1 LOW
returned ACCEPT, no blockers; all four optional notes are triaged.

Descriptor-backed inspection captures only the root CURRENT H/P/G and reports
unexpanded local/effective topology. Storeless aggregates carry local-frozen
semantic evidence and no custody basis. No members are resolved or opened.
Native review fixed a file-replacement classification race, independently
detached local/effective lists, and preserved legacy stored-root and positional
DTO compatibility. Default single-store restrictions remain.

Final SDK **559 passed**, architecture **101 passed**, scoped Ruff passes.
Production remains identical to Fable's accepted packet. Two post-review drift
assertions passed the 5 focused contract tests and scoped lint; the external
review predates those assertions. Reports:
[C7](consistency-c7-2026-09-06.md),
[validation](consistency-c7-validation-2026-09-06.md),
[review triage](reviews/consistency-c7-implementation-2026-09-06/primary-triage.md).

Early independent tests omitted state isolation and created four synthetic
witness journals/four binding rows under the default user state directory.
The validation report identifies them; shared witness history was preserved.
The test module now isolates state with an autouse fixture. No Arrival
operation was directed at a real project store. No review/test jobs remain.

C7 is uncommitted; nothing pushed. Next: checkpoint when requested, then D0
credential request design and D2 persisted binding/compatibility. The Fable
notes record a smaller follow-up to simplify the older aggregate-read resolver
with the new opt-in and concurrent-replacement tests. C9 remains the later
client/legacy transition.

Earlier entries below retain their historical status.

## September 6: C6 checkpoint; handoff to C7

The user requested a C6 checkpoint before compaction. This commit contains C6
production, tests, design decisions, validation, and all frozen Fable review
and primary-triage evidence. C3 remains its immediate predecessor `ef8b21b2`.
No C7 implementation has begun. Nothing pushed or applied to live stores.

Next: **C7 bounded aggregate inspection**, using the established Sol/Terra/Luna
implementation and Fable review pattern. Start from the C7 row in the
[consistency matrix](consistency-contract-matrix-2026-09-06.md). Address both
local aggregate descriptor resolution and the single-store inspection guard;
report bounded effective-root topology without inventing a global head or
opening members for it. Specify storeless-root evidence, preserve descriptor
role checks, and test both directions of local/effective topology disagreement.
D0/D2 credential binding and C9 remain separate follow-on work.

C6 accepted production hashes still match Fable's reviewed code. The sole
post-review code-tree addition is the inline-parameter SDK test, validated by
6 focused / 546 full SDK tests. Engine remains 2,597 passed / 1 skipped;
architecture 101 passed. Final evidence is retained with the C6 report.
No review or validation jobs remain.

Earlier entries below retain their historical status.

## September 6: C6 complete and accepted; C3 checkpoint retained

C6 is complete with Sol/Terra/Luna implementation and native validation. Two
Fable 5.1 high-effort design reviews preceded implementation; the final
Fable-low implementation review returned **ACCEPT**, no blockers. All six
optional notes are triaged. A post-review SDK test verifies inline generated
parameters across preview, signed edit and later emission; production remains
byte-identical to the accepted external review.

See the [C6 report](consistency-c6-2026-09-06.md),
[validation](consistency-c6-validation-2026-09-06.md), and
[implementation review triage](reviews/consistency-c6-implementation-2026-09-06/primary-triage.md).
Final engine **2,597 passed / 1 skipped**, SDK **546 passed**, architecture
**101 passed**. Scoped Ruff passes; broad compiler lint reproduces 57 baseline
findings. Captured validation/review hashes and the additional test are retained.
No review or validation jobs remain.

Ordinary same-name edits inherit boundary edges. Whole-loop retirement and
recreation cannot consume old owned ticks; ambiguous vertex roles are checked
only for a target that consumes them. Historical generated names require
literal or verified pinned evidence. Typed refusals retain basis and C2 effect
proof, with declaration IDs only when a relevant row can be established.

C3 remains checkpointed at `ef8b21b2`; C6 is uncommitted on `arrival/finish`.
Nothing pushed or applied to live stores/keys. Next bounded candidate is C7
aggregate inspection; D0/D2 credentials, explicit restart/carry and the later
C9 SDK/CLI transition remain separate. Review follow-ups also record the
existing resolver's pre-genesis overlay policy and possible imported vertex
singleton validation without changing read compatibility in C6.

Prior entries below retain their historical checkpoint and review status.

## September 6: C3 checkpointed; C6 design accepted and implementation started

C3 continuation and its retained validation/review evidence are checkpointed
at `ef8b21b2` (`fix(arrival): validate continuation snapshot custody`) following
the user's explicit checkpoint request during C6 design. Nothing pushed.

The user authorized C6 with Sol/Terra/Luna and Fable 5.1 high effort on the
design before implementation. Two high reviews completed. Root accepted the
[revised boundary continuity design](consistency-c6-boundary-design-2026-09-06.md)
after native/source/test-backed [review triage](reviews/consistency-c6-design-2026-09-06/primary-triage.md).
Both raw external verdicts remain REVISE: the first produced accepted design
corrections; the second resolved them and raised a missing-pin-gate claim that
source and existing tests disproved. This is primary acceptance after triage,
not an assertion of an external ACCEPT verdict.

In-place boundary edits inherit recorded consumption. The guard refuses
relevant tick-bearing retirement/recreation, historically ambiguous roles, and
unprovable generated membership. A target without the ambiguous vertex-boundary
consumer may run. Verified historical parameter bytes establish declared rows;
environment values do not. D0/D2 credentials and explicit restart/carry remain
separate. Root asked an optional inherit-versus-strict-refusal preference; no
answer arrived, so implementation uses the stated recommended inherit policy.

Sol owns engine implementation and integration tests, Terra SDK integration
and real acceptance, Luna pure-history tests and independent audit/validation,
and root documentation/integration/review triage. C6 implementation is now
in progress; no production/test changes preceded design triage. After focused
and full validation, the implementation gets the established Fable-low review.
The design packets and accepted snapshots remain frozen with their review.
Prior entries below retain their historical checkpoint status.

## September 6: C5 checkpointed; C3 continuation complete and accepted

C5 is checkpointed at `bacaeb96`. The C3 continuation follow-up is complete
using Sol/Terra/Luna and root, with Fable 5.1 low-effort acceptance and no
blockers. Resumed snapshots now use common custody completion while preserving
original token H/P, generation checks and valid projection advancement.

See the [implementation report](consistency-c3-continuation-2026-09-06.md),
[validation](consistency-c3-continuation-validation-2026-09-06.md), and
[review triage](reviews/consistency-c3-continuation-2026-09-06/primary-triage.md).
Final engine 2,568 passed / 1 skipped, SDK 540 passed, architecture 101 passed;
scoped Ruff clean. Production/test hashes match validation and review. No
review or validation jobs remain. The two optional review notes are triaged.

C3 continuation changes remain uncommitted on `arrival/finish`; nothing pushed
or applied to live stores. Remaining consistency work includes C6/D5 boundary
continuity and D0 credential request design, C7 bounded aggregate inspection,
and the later C9 SDK/CLI cut. C3 no longer has an implementation follow-up.
The optional intermediate/regressed-watermark test coverage remains recorded
in its review triage.

The entries below retain their historical checkpoint status.

## September 6: C4 checkpointed; C5 complete and accepted

C4 is checkpointed at `79696a72`. C5 is implemented using Sol/Terra/Luna and
root, with initial and follow-up Fable 5.1 low-effort reviews both accepting.
The shared current-name reservation covers effective Arrival runtime captures,
declared/template loop names, implicit `cite`, detached planning, proposed
declarations and new initialization. SDK scaffold conflicts refuse before key
creation, and declaration preview uses the signed-preparation refusal family.

See the [C5 report](consistency-c5-2026-09-06.md),
[validation](consistency-c5-validation-2026-09-06.md), and
[review triage](reviews/consistency-c5-2026-09-06/primary-triage.md).
Final engine 2,562 passed / 1 skipped, SDK 540 passed, architecture 101 passed;
scoped Ruff clean. Engine bytes match the full engine run; the two-file SDK
review correction passed full SDK/architecture reruns and the focused follow-up.
No reviews or validation jobs remain.

Fact-only folds, raw evidence, declaration inspection and exact export remain
available for ambiguous histories. A tick-free configuration can be corrected
by signed append-forward declaration edit, preserving the old byte prefix.
Already-recorded ambiguous tick roles remain unresolved D5/C6 continuity work;
C5's current-name predicate does not establish historical roles. Existing
reserved recovery semantics remain intact.

C5 remains uncommitted on `arrival/finish`. Main is clean; nothing pushed or
applied to live stores. Remaining consistency work includes C3 continuation
completion, C6/D0 credential request and boundary continuity design, C7 bounded
aggregate inspection, and the later C9 SDK/CLI cut.

## September 6: C4 complete and accepted

C4 is complete using Sol/Terra/Luna and root. The SDK custody provider now
refuses every non-None `key_dir` at construction with `SdkValueError`; the
default and explicit-None paths retain existing credential resolution. The
compatibility change is documented. See the
[C4 report](consistency-c4-2026-09-06.md),
[validation](consistency-c4-validation-2026-09-06.md), and
[Fable-low triage](reviews/consistency-c4-2026-09-06/primary-triage.md).

One Fable 5.1 low-effort review accepted with no blockers. All three optional
notes are adjudicated. Production, tests and README match the reviewed bytes;
final SDK 528 passed, architecture 101 passed, scoped Ruff clean. No jobs or
reviews remain. C2 was checkpointed at `831698ff`; C4 remains uncommitted on
`arrival/finish`. Main is clean; nothing pushed or applied to live stores.

Next bounded candidate: C5, refusing same-named Arrival loops and their vertex
during supported runtime/planning and proposed declaration changes, including
passive/count/reset/boundary cases while preserving evidence reads/export.
Credential request scope and persisted observer/key mappings remain D0/D2
design work; C4 only makes the unsupported override explicit.

## September 6 checkpoint: C2 implementation complete and accepted

C2 is implemented using Sol/Terra/Luna and root. Arrival projection/search
maintenance errors carry explicit mutation-attempt evidence, declaration
preparation retains its proven custody non-entry and behind-projection heads,
and the SDK adds bounded causal diagnostics while preserving v1 errors and
existing phases. Arrival `sync_target` now uses the maintenance normalization
boundary. See the [C2 report](consistency-c2-2026-09-06.md),
[validation](consistency-c2-validation-2026-09-06.md), and
[review triage](reviews/consistency-c2-2026-09-06/primary-triage.md).

Two Fable 5.1 low-effort reviews completed. The initial review found an
absent-versus-null context issue and two serializer refinements, all corrected.
Its speculative preparation-helper reuse concern was disproved by the full
call graph; the follow-up accepted that rebuttal and the final source. One
optional captured-head enrichment on other declaration-refusal branches is
recorded as future work. No reviews or validation jobs remain.

Final validation on unchanged production/test bytes: engine 2,550 passed / 1
skipped, SDK 525 passed, architecture 101 passed, scoped Ruff clean. The C8b
implementation and C2 design were checkpointed at `8a045f1f`; this C2
implementation remains uncommitted on `arrival/finish`. Main is clean. Nothing
pushed or applied to live stores. The next bounded consistency candidate is C4:
refuse a configured credential `key_dir` override until an explicit mapping is
supported, instead of silently ignoring it.

## September 6 checkpoint: C8b complete; C2 design accepted

The C8b collection slice is implemented using Sol/Terra/Luna and root, with
three Fable 5.1 low-effort reviews including one combined follow-up. All
findings are triaged and no reviews remain. See the
[C8b report](consistency-c8b-2026-09-06.md),
[C2 evidence design](consistency-c2-evidence-design-2026-09-06.md), and
[review triage](reviews/consistency-c8b-c2-2026-09-06/primary-triage.md).

Owned iterator cleanup, paired partial collection evidence, coordinator failure
classification and earlier durable tiers now survive the SDK boundary. C2 is
an accepted design, not a normalization implementation. The next bounded step
is maintenance/search evidence and cause serialization, followed by Arrival
`sync_target` normalization using those proofs.

Validation: engine 2,540 passed/1 skipped, SDK 509, architecture 101; final
explicit-cause preservation additionally passed 30 engine source tests. Scoped
Ruff passes. Production matches the accepted follow-up packet. Prior Arrival
work is committed at `cfb26920`; this C8b/C2 pass remains uncommitted on
`arrival/finish`. Main is clean; nothing pushed or applied to live stores.

## September 6 checkpoint: C1 registry consistency accepted

C1 is complete using Sol/Terra/Luna and one Fable 5.1 low-effort review.
Entity resolution, timeline and declaration inspection accept optional
registry injection; timeline retains the captured root and uses the supplied
registry for all supported member opens. See the
[C1 report](consistency-c1-2026-09-06.md) and
[review triage](reviews/consistency-c1-2026-09-06/primary-triage.md).

Validation: SDK 504 passed, architecture 101, scoped Ruff passed. The final
C1 test file passed 10 cases after three review-driven file-backend cases
were added; the full suite count predates that test-only addition. Fable
accepted production code unchanged; root resolved all four low findings.
No reviews remain. Changes remain uncommitted in `arrival/finish`. C2 evidence
design, C4 credential configuration, C8b collector ownership and the other
matrix items remain explicit follow-ups.

## September 6 checkpoint: first consistency implementation accepted

C3 and C8a are complete in the Arrival worktree using the authorized
Sol/Terra/Luna pattern. Fresh reads, runtime capture and declaration preparation
share custody completion before bounded clamping; initializer propagation keeps
identity, cause and existing intent-path diagnostics. See the
[slice report](consistency-slice1-2026-09-06.md) and
[review triage](reviews/consistency-slice1-2026-09-06/primary-triage.md).

Both Fable 5.1 low-effort reviews accepted. Root's independent review found and
corrected a lost SDK error detail; Fable test gaps led to a consumer
wrong-coordinate case and a real file-backed capture/advance interleaving across
all three operations. Final engine 2,528 passed/1 skipped; SDK 497;
architecture 101. Scoped Ruff passes apart from the confirmed pre-slice
head-seam docstring E501. No review jobs remain.

C1 registry injection is the next independent implementation slice. C2 needs
phase/cause/effect design; continuation snapshot completion, C8b collector
ownership, and identity decisions remain explicit follow-ups. Changes are
uncommitted in `arrival/finish`; main checkout and live state are untouched.

## September 6 checkpoint: Fable-low consistency review triaged

One user-requested Fable 5.1 review at low effort completed on frozen contract
matrix/identity recommendations plus selected source. Root adjudicated all six
findings; [primary triage](reviews/consistency-2026-09-06/primary-triage.md)
records accepted refinements, rejected aggregate-routing/equality/identity
suggestions, source evidence and disposable probes. Six targeted existing
engine/SDK tests passed. No code or live-state changes occurred.

The revised first correctness slice is C3 full-head/basis consistency including
same-height hash disagreement, plus C8a unchanged exception propagation. C1
registry injection can proceed independently. C2 needs phase/cause/effect
evidence before wider normalization; C8b separates collector errors from ID
bookkeeping and specifies stream cleanup. D0 names credential request scope
before persisted key mapping, and D4 now recommends an initial all-loop
vertex-name reservation. Updated recommendations remain proposals, not landed
implementation. Fable's reviewed copies and raw output are preserved; root's
subsequent edits do not represent a second Fable approval. No review jobs remain.

## September 6 checkpoint: consistency contracts and identity recommendations

The user authorized the contract matrix plus identity decisions using the
existing Sol/Terra/Luna delegation pattern. Read-only audits and root synthesis
are complete in [the consistency matrix](consistency-contract-matrix-2026-09-06.md)
and [identity decisions](identity-decisions-2026-09-06.md), with three linked
agent audits. The matrix distinguishes existing guarantees, source-confirmed
inconsistencies, hypotheses needing focused tests, and proposed semantic rules.

Recommended first implementation slice: SDK registry injection, public outcome
normalization, and custody membership validation of declaration preparation's
observed projection watermark. Follow with explicit credential configuration,
boundary collision validation, and separately specified key-binding/continuity
work. Existing vertex rename refusal and per-occurrence aggregate evidence stay
in place. These are recommendations; no consistency code fixes landed in this
documentation pass.

Sol ran 56 existing focused SDK tests successfully. Root checked all 985
non-documentation files against the start-of-pass hashes: no drift; local
document links and diff whitespace checks passed. Main checkout remains clean.
No external reviewer was run and no review jobs are pending. Earlier broader
completion and review checkpoints below retain their historical scope.

## September 6 checkpoint: remediation integrated

Sol/Terra/Luna/root remediated the six reviewed behaviors and follow-up defects.
Three low-effort Fable reviews completed; no review jobs remain. Engine 2,510
passed/1 skipped; SDK 494, sign 40, custody 50, architecture 101, minimal CLI 8,
migrate 69 passed. See `remediation-2026-09-06.md` and
`reviews/remediation-2026-09-06/primary-triage.md`. Changes remain uncommitted;
main and live stores are untouched. Local boundary-name ambiguity and encoded
custody path portability are separate design follow-ups.

## September 6 checkpoint: Fable follow-up complete

The three previously outstanding Fable stages and one focused correctness
follow-up completed at low effort. Root triage and independent reproductions
are in `reviews/fable-followup-2026-09-06/primary-triage.md`. No review jobs
remain running. New follow-ups cover observer key aliasing/mint-load agreement,
literal fact-ID prefix lookup, boundary origin identity, and two result-reporting
semantics. This was a review pass; no production code changed. Historical queue
entries below retain their original timestamps/status.

## Correctness pass checkpoint

The five reproduced failures now have production corrections and regressions.
See `correctness-pass-2026-09-05.md` for exact scope, period semantics, validation,
and remaining projection-recovery design. Root integrated checks: engine 2,501
passed/1 skipped; SDK 486; migrate 69; architecture 101; minimal CLI 8. Gemini
3.8 Flash High review 1 completed and its findings were addressed. Final combined
review 2 completed with no actionable findings; root independently reran all
six adversarial probes and corrected the declaration follow-up selection (5 passed). No Claude calls, production commits, or live-store changes.

Earlier checkpoints below are historical; five-open triage is superseded by
this implementation checkpoint, and this bounded correctness review is accepted.

# Arrival completion orchestration

Working branch: `arrival/finish`, based on `d904ccba`.
Implementation checkout: `/Users/kaygee/Code/loops-wt/arrival-finish`.

The [completion worklist](completion-worklist-2026-09-05.md) defines the
remaining work. This log records assignments and acceptance evidence, not
new protocol requirements.

## Working arrangement

The primary conversation owns scope, architectural judgment, acceptance and
discussion with the user. The user requested Sol/Terra/Luna implementation
agents and adversarial cross-model reviews through the `claude` CLI using
Fable 5.1. The locally configured explicit model is
`claude-fable-5-1[1m]`; reviews record the returned model metadata when available.

Agents receive bounded assignments and distinct file ownership. Completed
stages receive targeted validation followed by a Fable review. Findings are
triaged against the ratified protocol and reproducible behavior, corrected
where warranted, and rechecked before acceptance. Review prompts and findings
are retained with enough scope information to distinguish code review from
execution evidence.

Live migration, release and publishing are separate from implementation in
this isolated checkout. No agent is assigned live-store writes.

## Initial assignments

| Agent | Assignment | Ownership |
| --- | --- | --- |
| Sol (`descriptor_stage`) | Complete descriptor parsing, resolution and registry enforcement | Descriptor implementation and related tests |
| Terra (`query_design`) | Propose the smallest coherent consumer query/open contract from actual SDK needs | `query-consumer-design-2026-09-05.md` only |
| Luna (`stage_validation`) | Independent baseline checks and adversarial descriptor cases | Read-only |
| Primary | Review setup, decisions, stage acceptance and orchestration log | This log and review artifacts |

## Stage status

### Latest checkpoint

Primary triaged the ten completed Fable reviews at the user's request before
choosing next steps. Five failures were reproduced on disposable stores:
restore/projected-fork disagreement, SDK declaration recovery result crash,
local/effective aggregate root omission, repeated recorded vertex boundary,
and missing runtime declaration-anchor guard on boundary-only writes.
All remain open; no production fixes were made during triage. Several packet
visibility findings were dismissed against the actual dependency code.
See [primary triage](reviews/scheduled-2026-09-05/primary-triage.md), which
links the saved reproduction evidence. The review queue is quota-stopped,
with verification/pagination, custody observer guard and export outstanding.

Latest scheduling update: user changed remaining Fable reviews to **low**.
Restore-forward completed at high effort; the runner's false model rejection
was corrected after inspecting mixed Fable/auxiliary Haiku usage. The other
twelve reviews resumed sequentially at low effort, starting with initializer.
See the scheduled status file for live progress; findings are not yet accepted.

User scheduled all queued Fable reviews for September 5 at 21:22:11 CDT,
with `--effort high`. A verified one-shot local launchd job will execute
thirteen refreshed static review packets sequentially, stopping on quota or
execution failure. See [schedule](reviews/scheduled-fable-2026-09-05.md) and
`reviews/scheduled-2026-09-05/status.json`. The initial high-effort schedule is superseded by the low-effort resume above.

All three requested implementation agents stopped with Codex usage-limit
errors (reported reset September 11, 2026, 14:06). Primary took over their
unfinished edits. Claude/Fable separately remains limited until September 5,
21:20 CDT. No account or credential switching was attempted. Newer stages
remain locally reviewed and explicitly pending cross-model review.

Current local stages:

- Source engine/SDK: captured deterministic tiers and explicit collected,
  committed, unknown and dispatch outcomes.
- Aggregate engine/SDK: structural member selection controls fold ordering
  before row filters; implicit storage refuses; AST evidence is detached;
  effective topology can reuse the captured root; same-lineage occurrences
  and own-overlay shadowing survive.
- Declaration engine/SDK: exact cache splice/current semantic guard, safe
  publication/recovery, retained actual Commit values, bounded serialization
  and consistent v2 Arrival preview outcomes.
- Neutral credentials and file-projection schema: moved implementations and
  updated owning-module tests, with temporary legacy reexports. New schema
  module style debt was cleaned up; affected coordinate tests passed again.
- Exact export engine/SDK/minimal CLI: closeable captured byte streams and exclusive,
  fsynced artifact publication; late failure never publishes a partial file.
  The manifest is returned in the SDK result. File adapter projection naming
  now keeps arbitrary/.db ledger names distinct from their SQLite sidecars.
- Initializer additional keys: founding signatures introduce declared keys
  before declaration genesis in one atomic append. Atomic limits and invalid
  keys refuse before mint. Recovery verifies every reserved bootstrap record.
  Real SDK emission by the introduced observer verifies both signer domains.

- Restore-forward engine/SDK/minimal CLI: user-approved explicit procedure;
  pure proposed-head comparison, full receiver-prefix proof and atomic CAS;
  post-commit re-comparison, witness receipt, typed unknown/incomplete outcomes.
  Ordinary open still refuses rollback. See `restore-forward-stage-2026-09-05.md`.

Latest checks: full engine **2,479 passed, one skipped**; full SDK **478 passed**;
migration **69 passed**; full architecture **101 passed**. All **8 minimal CLI
tests** also pass, including its built-wheel smoke test.
Focused changed-source Ruff and diff whitespace checks pass. Main checkout is clean; implementation remains
uncommitted in this isolated worktree.

Transfer testing exposed two real integration gaps, documented in
`transfer-boundary-findings-2026-09-05.md`. Ordinary attestation refuses a
receiver below a witnessed head, including a legitimate older exact copy.
Also `replicate(None, records)` is not exclusive creation: the file primitive
still requires an existing genesis. A draft coordinator assuming otherwise
failed real tests and was removed from shipped source; it survives only as
explicitly incomplete scratch in `/tmp/loops-arrival-review`. No fake genesis
Commit, mint re-signing, raw-store fallback or witness reset was introduced.
The user approved explicit restore-forward, now implemented and locally
validated. Its source and receiver keep ordinary descriptor roles; it grants
no reusable un-attested custody handle and never resets the witness.

Remaining: empty-receiver exact import/bootstrap, foreign
admission, descriptor adoption, richer SDK initialization/default cut, legacy
authority deletion, minimal CLI writers, wheel/conformance/performance checks
and pending Fable reviews. No live migration, release, commit or push occurred.

### Stage evidence

- Parser correction WP4-F3: accepted after prior validation and
  [Fable review](reviews/parser-fable-2026-09-05.md); no blocking findings.
- Descriptor completion: accepted by primary after Sol implementation/Fable
  triage and Luna's final independent audit. Agent reports
  721 language, 2,316 engine (one skipped), 69 migration and 101 architecture
  checks passed. Review artifact records focused post-review validation;
  the agent's final report additionally records the final full engine run.
- Consumer query/open contract: stage 2A engine snapshots, file adapter and
  consumer opener accepted after implementation review corrections. Final
  checks: 11 query tests, 215 relevant engine/SDK tests and 101 architecture
  tests (overlapping sets).
- SDK read integration: stage 2B accepted after Fable follow-up approval and
  Luna's real temporary file-backed store acceptance. Sol reports 350 SDK
  tests, 81 engine consumer/contract/registry and 101 architecture checks
  passed. Legacy and aggregate paths remain explicitly transitional; unsupported
  explicit/nested/effective aggregate reads refuse before legacy fallback.
- Resource lifetime: complete; both wrappers forward optional adapter close.
  Luna's final checks: 721 language, 150 registry/contract/head-seam and 101
  architecture tests; registry/head-seam type checks and diff check passed.
- Runtime write design: reviewed by primary and Fable, with fresh local
  signing/chain behavior requiring source-backed correction before extraction.
- Open-path follow-up: stage 2C accepted after Fable triage and primary's
  custom-provider namespace finding. Registration-supplied binding policy
  preserves the opener tuple, historical file bindings and live file alias/
  replacement checks. Non-file keys are backend-namespaced and independent
  of filesystem/cwd interpretation. Invalid custom provider identities refuse
  before opening or witnessing. Final focused checks: 161 pass, type and diff
  checks pass. Legacy direct file-shaped seam callers remain transitional.
- Runtime 3A: accepted after source-backed Fable dispositions. Terra implemented
  the bounded ordinary-fact writer with a
  generated boundary tick, CURRENT snapshot admission/planning and one
  full-head CAS append. Fresh signing/chain behavior is source-checked;
  admission transfer semantics are not substituted for local authorship.
  Same-snapshot hydration, derived admission/custodian, refused-preview evidence
  and unknown-commit regressions now pass. Equal existing observations are
  recognized before new-fact observer admission. Final review corrections
  restore vertex-tick period context and refuse combine before materialization.
  Latest runtime checks: 20 passed; final exact focused-suite recheck confirmed
  225 passed after removal of a redundant helper test.
- Projection maintenance 3M: accepted after Fable triage and primary's final
  no-op generation correction. Sol implemented explicit attested catch-up for
  absent/behind projections. No rebuild capability yet, no read-time repair,
  and no rewind of a projection already beyond requested H. Maintenance
  reports observed prefix separately from a runtime's durable commit.
  Agent reports 136 relevant engine, 351 SDK and 101 architecture checks
  passed. Final maintenance checks after primary's correction: 16 passed,
  Ruff/type checks clean. When a concurrent projection advance exceeds the
  captured bound, report the actual prefix with unknown generation, including
  the early no-op branch. See the projection-maintenance review receipt.
- Runtime acceptance: Luna's temporary real-ledger crypto/CAS audit passed;
  Terra added hydration and unknown-outcome tests afterward.
  Primary's subsequent full engine run passed: 2,371 passed, one skipped in
  62.43 seconds (`uv run --package engine pytest libs/engine/tests -q`).
  The run overlapped final preparation-regression additions; Terra's focused
  latest tests remain the evidence for those additions.
- Minimal CLI 4A: accepted after Fable supplement and SDK error-classification
  follow-up. Six subprocess/packaging tests, 368 SDK tests, 101 architecture
  checks and clean-venv wheel smoke passed (overlapping SDK stages). Diagnostic
  refusal, admission, unknown append, unwitnessed commit, postcommit projection
  failure and projection-maintenance uncertainty retain distinct SDK outcomes.
  Declaration inspection remains unavailable because the SDK implementation
  still follows legacy resolution.
- Source execution remains a subsequent bounded slice. Terra's revised design
  is accepted: fixed initial cadence/source inputs, deterministic collection
  order, tier commits, next-tier recapture with unchanged declarations, and
  one attempted postcommit dispatch without an invented delivery guarantee.
- SDK ordinary emission 3E: accepted after Fable supplement and source-backed
  dispositions; final focused checks 39 passed, preceding full SDK 373 passed,
  scoped Ruff/type checks passed. Preview, dry run and emission preserve
  captured policy and deterministic-ID retry behavior; postcommit/unknown
  outcomes retain evidence rather than becoming ordinary refusal.
- Batch runtime 3B: accepted after Sol completion, real attested prepare/append
  tests, Fable review and source-backed dispositions. Focused checks 45 passed;
  full engine 2,396 passed, one skipped; full SDK 384 passed; Rule 18 35 passed.
  Real tests verify packed-record limits, multiple signed tick windows,
  duplicate handling and uncertainty identity. Sol now wires SDK emit_batch
  to that contract with a uniform serializable batch result.
- Initializer 3C1: Luna implementing fresh signed genesis/declaration bootstrap
  and durable-intent recovery through registry custody, then existing SDK
  `init_vertex`. The accepted proposal and primary's initialization handoff
  define this slice. Declaration edits and CLI init wiring follow acceptance.
  Primary's latest full architecture check is green: 101 passed. Initializer
  acceptance remains pending its input-coherence, signature-injection,
  custom-location recovery and committed-incomplete reporting fixes.
- Signer integration correction: locally accepted after distinct Arrival
  credentials and real default SDK initialization → ordinary → packed-batch
  verification. Inner FACT and outer ARRIVAL signatures verify only under
  their intended domains; absent Arrival credentials do not reuse FACT.
  Final checks reported: 86 focused, 2,404 engine (one skipped), 408 SDK,
  35 Rule18; scoped Ruff/type checks green. Fable supplement remains queued.
- Declaration inspection: locally accepted after snapshot-bound effective
  fields, residence-excluded local drift fingerprints, JSON serialization,
  captured-head concurrency and absent/behind no-repair checks. SDK 408,
  CLI six and architecture 101 passed. Fable packet is queued.
- Current handoffs: Sol implements immutable runtime capture and
  batch-from-capture with pending-boundary planning; Terra implements full
  prefix verification through the SDK/CLI contract. Luna designs declaration
  edits, with one root-confirmed initializer follow-up first: complete custom
  credentials skipped domain verifiers and accepted a wrong-domain inner
  genesis signature. Shared verifiers and focused SDK input/recovery tests
  are required before initializer acceptance.
- Entity lookup: accepted after Fable dispositions. Uniform SDK wrapper retains
  the queried address, descriptor and read basis, including misses; Arrival
  exact top-level matching follows captured receipt order. Real concurrency
  injection confirms a later append/projection advance cannot leak into H.
  Final SDK 384 and CLI six tests passed. Full architecture run had two
  initializer-owned failures, assigned to Luna; no global green claim yet.
- Reviewer availability: Claude reports a session limit until 21:20 on
  2026-09-05 America/Chicago (verified at 18:00). Batch and entity Fable reviews
  completed before the limit; initializer review did not produce findings.
  Further Fable calls are queued until reset; no credential/account switching.
  Implementation and local validation continue. Unreviewed stages remain
  explicitly pending cross-model review.
- Timeline: Terra implementing the accepted single-store timestamp-lens read
  with one snapshot, descriptor/basis and a uniform result. Search and
  aggregates remain design work. Future search must account for BM25's corpus
  statistics: filtering future rows from matches alone does not make rank
  relative to the captured prefix.
- Later stages: pending the preceding contracts and implementation.

## Decisions

- Integration audit reopened the ordinary/batch signing gate: real default SDK
  init → emit produced a correct inner FACT signature but an outer envelope
  signed under FACT rather than ARRIVAL. Batch packing had the same defect.
  Terra reproduced both with temporary custody keys and explicit domain
  verification. Sol owns the narrow correction: a distinct optional
  `WriteCredentials.arrival_signer`, supplied by custody and used only for
  outer fact/batch envelopes. No fallback to the fact signer; absent outer
  signing remains an unsigned ordinary envelope under the existing policy.
  Acceptance requires real default SDK init → ordinary → batch verification.
- SDK batch local validation reached 403 passing SDK tests before the signing
  repair, with 55 focused runtime/batch/maintenance checks and 35 Rule18 checks.
  These are overlapping checks, not additive totals. Fable is still queued.
- Terra's timestamp timeline has local acceptance; the next bounded assignment
  is descriptor-first declaration inspection, in sections separate from
  Luna's initializer. The declaration edit implementation handoff is recorded
  in `declaration-edit-handoff-2026-09-05.md`.

- Explicit roles must be checked against adapter capabilities and must
  constrain mutations through the opened handle. Adapter capability alone
  does not establish authority over an instance.
- Descriptor-stage integration preserves `role=None` for existing callers;
  omission is transitional debt, not evidence of authority designation. The
  new supported SDK path will require explicit designation for authority
  operations, and migration/bootstrap callers will be made explicit there.
  Read-only opens need no implicit grant of mutation authority.
- A lineage declared before genesis is a pin on later initialization. Opening
  an empty artifact must not make it possible to initialize another lineage
  through the same handle.
- Authority transfer and new query/witness declaration grammar are not
  introduced as incidental consequences of descriptor parsing.
- Query DTOs live in engine; SDK owns target, declaration/fold, aggregate
  interpretation and serialization. Reads never materialize or repair a
  projection; missing/behind projections refuse current reads and require
  explicit maintenance. The registry already attests, so consumer opens must
  not wrap the ledger a second time.
- A projection advancing after head capture is normal when custody proves its
  membership. Rows remain bounded to the captured prefix. Cursors also bind
  the derived-view generation; matching ledger membership is insufficient for
  resuming an incompatible view.
- Aggregate bases are keyed by member identity, retaining same-lineage members
  with different declarations or prefixes. Deduplication remains aggregate
  semantics rather than backend policy.
- Keep one public SDK `read_*` family. Migrate results to consistent typed
  wrappers carrying the basis, including ticks and fact-by-id (a missing fact
  still has a read basis). Transitional legacy branches use the same result
  shape with an explicitly absent Arrival basis. Do not create a permanent
  `read_arrival_*` family to avoid the intended SDK API cut. Outgoing CLI
  callsites affected by return-type changes are recorded for later retirement
  or migration; target-dependent return types are not accepted.
- Runtime design corrections: the licensed declaration genesis FACT ID equals
  the physical Arrival lineage; distinct record roles do not imply distinct
  identity values. Mixed-observer input can use separate drafts in a single
  append if the backend's atomic limits permit it. Append refusal tests must
  distinguish legitimate open-time attestation from mutation by the refused
  append. Source execution follows the first ordinary-fact slice.
- Query review judgment: a blanket refusal of continuation after custody
  advances was rejected and removed. Resumptions verify token membership and
  preserve their original basis while later appends may exist. Physical
  Arrival lineage must match the supported projection's own declaration
  marker/genesis fact ID; historical SQLite identity distinctions do not
  excuse a mismatched Arrival projection.
- Runtime extraction requires the neutral row DTOs to retain existing wire
  evidence: exact payload text and inner signatures, plus tick-chain fields.
  Terra owns the narrow DTO/FileQuery extension before handing FileQuery to
  projection maintenance work. Decoded payload convenience is not a substitute
  for the original signed text, and absent evidence must not be fabricated.
- Runtime CURRENT-state judgment: a caller-supplied mutable Vertex plus a
  claimed basis is insufficient. The supported write factory reconstructs a
  detached runtime from the same snapshot's effective declarations, facts and
  tick/period/window context. Hydration does not append or fire boundaries.
  Low-level caller-responsible planning helpers are not the supported
  coherence guarantee.

## Orchestration handoff

After the initial assignments finished, the next stage had not started until
the user requested status. Stages 2A/2B are now assigned and running; the
primary remains responsible for advancing completed handoffs. An agent being
finished is not evidence that the overall completion worklist is finished.

## Stage 2 pre-review checkpoint

Both engine snapshots and SDK single-store reads are implemented and entering
Fable review. Sol reports 334 SDK tests and 101 architecture checks passed;
Terra reports 72 focused engine tests, 167 projection/head-seam/contract/
registry checks, 33 SDK read/state tests and 101 architecture checks passed.
These sets overlap and must not be summed as unique tests.

Known performance limitation: the file snapshot hashes all bounded facts and
ticks, schema and declaration identity when establishing view generation.
Opening a resumed page is therefore O(prefix); this is not a claim of cheap
pagination or metadata-only validation. Performance acceptance remains ahead.
