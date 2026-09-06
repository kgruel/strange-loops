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
