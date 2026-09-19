# Loops legacy-store copy rehearsal

Implementation baseline: `381f121d` on `arrival/finish`.
Live source: `/Users/kaygee/Code/loops/.loops/data/project.jsonl`.
Private working artifacts: `/Users/kaygee/Code/loops-rehearsals/loops-20260918-171627`.
No store payloads or private credentials are committed with this report.

## Snapshot and initial refusal

The active declaration names JSONL as canonical; the sibling SQLite file is a
derived index. Copied the 204,426,871-byte JSONL source and exact vertex, checked
source hashes before and after copying, and relocated only the copied vertex's
store residence. The isolated existing self key's public half matches `project`.

Original source SHA-256:
`1baa08419b856a52692100d8ea670a12482d80f95ce8a8d3193f194ac4c5347e`

Original vertex SHA-256:
`3a2264100e1e17174f883970290bd8a314ca91eca0d36d4ec53fc11ffbf8479b`

Census: 4,478 flat JSONL rows, 4,357 facts, 121 ticks, no batches or duplicate
IDs. All fact IDs are canonical ULIDs; no `_decl.*` collision exists.
1,267 facts carry signatures; 3,090 are unsigned.

The first ordinary inventory refused before creating a target: 982 unsigned
facts have an empty observer. This is the intended existing refusal boundary,
not an Arrival parser defect. Full refusal and affected-row evidence remain
in the private artifact directory.

## Explicitly authorized preparation

The user selected an audited `legacy/unattributed` mapping. A separate preparation
step creates a new input, changes only the empty observer on unsigned flat facts,
and records per-row coordinates/IDs and original/prepared line hashes. Original
archive bytes remain intact; no core migration or Arrival wire rule is weakened.
The placeholder denotes unknown historical attribution; it is not a recovered
author identity, gets no signing key, and the affected facts remain unsigned.

The subsequent migration report certifies the **prepared input**. The separate
preparation manifest links it to the original archive and is not misrepresented
as part of the existing signed migration-report contract.

## Execution

Preparation passed seven focused tests and independent whole-file comparison:
982 rows differ only in the observer field semantically (JSON serialization of
affected lines may change); 3,496 lines are byte-identical. Standard prepared
inventory passes. Prepared SHA-256:
`e90c51f0929f2cfdb2d46c636845eb57b366e5432bf5c734f6b88619c5215933`

Preparation-manifest SHA-256:
`d6db177325ba4a50539504efb834dfce8310082d2a34c6446c465ebf82b748ca`

The isolated runner passed two synthetic tests. On the real prepared copy:

- Migration completed with no dropped units, at ordinal 4,483.
- Signed report verified at S; descriptor names the minted lineage and authority.
- Adoption appended the exact declaration anchor at ordinal 4,484 and published.
- Ordinary reads report 4,357 facts and 121 ticks, declaration status `store`,
  and the adoption head as read basis.
- First rehearsal-only `log` emit refused before attempting custody:
  `BoundaryContinuityConflict: vertex-period tick predates declaration genesis`.
  The cited historical tick is at ordinal 2,307; declaration adoption is at 4,484.
  Physical custody still ends at the declaration anchor. A repeat diagnostic
  confirmed the same typed preappend refusal.

This exposes a real-store boundary-history compatibility gap not covered by
the synthetic migration tick named `heartbeat`. The copied source is unchanged;
no live store or descriptor has been modified. Boundary semantics and isolated
recovery proof are under investigation; this is not a successful end-to-end
write/export rehearsal yet.

## Boundary-policy finding

Independent engine/design review confirms the write refusal is intentional:
`consistency-c6-boundary-design-2026-09-06.md` explicitly refuses consumed owned
ticks before own declaration genesis. Old ticks remain reset/count/period edges;
silently skipping the guard would consume unproven history, while filtering the
ticks could change state. No core boundary check was weakened.

The user was asked whether to design an explicit reviewed legacy-continuity
bridge, start a new boundary epoch with a defined initial state, or defer write
policy and finish this as a read/export rehearsal. Decision pending.

Full verification and exact bounded export at adopted head A succeeded. Export
is 205,671,254 bytes, SHA-256
`5c19381fffa4d4f23471e622a03773a82119f23d53f4b0470b8bfc56b2cad86b`.
Both the migration prefix and signed report remain byte-identical after adoption
and refused write attempts. This is evidence of successful read/export migration,
not authorization for a live cutover or proof that ordinary writes are ready.

## Harness isolation correction

Review caught a parent-process `read_summary` before setting isolated state in
the recovery harness. The first synthetic test had created one default-state
head journal plus one binding entry for test-only lineage
`01M2VA910YMYV5SY1W5FVTHY28`, both pointing solely to its pytest temporary fork.
These are synthetic witness metadata, not a real store or credential change.
They were retained rather than rewriting the shared append-only binding journal.
The parent now sets isolated environment before SDK access; a regression checks
that intentionally supplied outside state/configuration directories stay absent.
The real-store recovery run was withheld until this was corrected.

## Completed recovery and validation

Both real-source forks passed: a child exits at `after-intent` or `after-append`,
then recovery runs with its copied mapped credentials moved offline and provider
access disabled. Each recovers the exact reserved anchor once at S+1 (ordinal
4,484), retains `Commit(S,A)`, reports current summary basis, and leaves the
migration prefix unchanged. A second recovery refuses with no byte changes.
Each fork first synchronizes at S and proves that declaration-dependent reads
refuse specifically because no declaration has been adopted.

Final validation: **126 repository tests passed** (excluding chaos), including
11 new focused preparation/runner/recovery tests. Ruff and whitespace checks
pass. Luna's independent review found no remaining tool blockers after isolation,
projection, timeout and artifact-documentation corrections. No engine or SDK
runtime semantics changed in this rehearsal.

Final hash checks prove that the live source, live vertex, original snapshot
and prepared copy remain unchanged. No push, merge, live migration or release.
The harness isolation correction above is the sole recorded default-state
side effect and concerns only a synthetic test lineage.

**Outcome:** preparation, migration, adoption, reads, exact export, and credential-
free crash recovery pass on the loops copy. Ordinary writes are intentionally
refused by C6; this store is not ready for live writable cutover. The boundary
policy choice remains pending.

[Machine-readable evidence and commands](reviews/loops-rehearsal-2026-09-18/evidence.json),
[recovery evidence](reviews/loops-rehearsal-2026-09-18/recovery-evidence.json), and
[preservation checks](reviews/loops-rehearsal-2026-09-18/preservation-check.json)
contain metadata only; source payloads, per-row audit details and private keys
remain in the private rehearsal directory.

## Subsequent user decision

The user selected a new boundary epoch at adoption. Its initial state and
compatibility contract are defined in the
[fresh runtime epoch design](adoption-fresh-runtime-epoch-design-2026-09-18.md).
The strict run above remains immutable evidence. A separate copied descriptor,
migration and explicit fresh adoption will exercise the selected behavior.

## Fresh epoch rehearsal

The explicit fresh implementation is checkpointed at `72faf1d5`; subsequent
review corrections retain strict hydration compatibility and strengthen the
rehearsal assertions. A new isolated migration/adoption completed using the same
audited prepared input, with zero dropped units. Its lineage is
`01M2VCBPYRT63W2FKA54PVKP7D`, selected S=4,483, and adoption A=4,484.

At A, all 4,357 historical facts and 121 ticks remain queryable. The runner
asserts their per-kind/count agreement with inventory, the signed fresh epoch,
and exact equality of current fold sections with the declaration's zero-input
initial values. Initial state sections SHA-256:
`3491b909f8bf4c11c8fc8d8d241ca0bb60801eb6d0b21304ea8693093b6a8c36`.

One explicitly labeled rehearsal-only `seal` fact then committed with a new tick,
ending at ordinal 4,486. The emitted fact was reread from physical custody,
matched to the returned commit, and verified in both signature domains. Full
verification passed. Exact export contains 205,673,522 bytes, SHA-256
`73b678adb57c28869d8a7482e6a244280ec7e32a2474a2d6ad5f909a712df5d8`.
The migrated prefix and signed report remain unchanged.

The first fresh attempt adopted and read successfully but refused the seal before
append because the harness omitted the receipt observer. That copy and its
unchanged-custody evidence are retained. The harness now binds the selected
observer for receipts, with a subprocess fact-plus-tick regression. The successful
run uses a separate descriptor and output directory.

[Fresh run evidence](reviews/loops-fresh-rehearsal-2026-09-18/evidence.json) and
[preservation checks](reviews/loops-fresh-rehearsal-2026-09-18/preservation-check.json)
contain metadata only. Crash recovery and deep-audit follow-up are recorded below. The original strict run remains unchanged historical evidence.

### Fresh recovery and historical commitment limitation

Both fresh recovery forks passed actual process termination after intent and
after append. With copied credentials offline, each recovered the reserved fresh
anchor exactly once at S+1; second recovery refused without changing bytes. See
[recovery evidence](reviews/loops-fresh-rehearsal-2026-09-18/recovery-evidence.json).

Post-write reads report 4,358 user facts and 122 ticks. The full physical/index
comparison passes. The deeper historical tick-window audit **does not pass**:
39 old window commitments no longer match the prepared facts. A complete
read-only comparison established:

- The retained original archive passes all 121 historical tick-chain checks.
- The authorized mapping changes exactly 982 fact hashes because observer is
  part of the hashed fact. IDs/order/payloads are preserved; all tick rows are
  unchanged.
- Those changes affect 39 historical windows. Each passes against the original
  facts and fails against the prepared facts.
- Migration preserves all prepared fact hashes and all 121 old tick rows.
  Its computed historical windows match the prepared input exactly.
- The newly emitted tick passes its chain/window checks.

This is an audited transformation consequence, not a fresh-epoch reset of custody
or an existing defect in the original archive. The signed migration report
certifies the prepared input; it does not make the original window commitments
valid over changed facts. No tick commitment or historical signature was
rewritten. The original archive and separate mapping manifest remain necessary
provenance. See [full comparison](reviews/loops-fresh-rehearsal-2026-09-18/window-diagnostic.json)
and [deep-audit result](reviews/loops-fresh-rehearsal-2026-09-18/postcheck.json).

**Current outcome:** fresh adoption, initial state, writes, exact export and
credential-free recovery work on the loops copy. A clean historical tick audit
is not achieved after the approved observer mapping. Before live cutover, an
explicit policy/tooling decision is still needed for representing and verifying
these transformed historical commitments. Do not label this rehearsal an
unqualified historical-integrity pass. Live source and vertex remain unchanged;
no push, merge, release or live cutover occurred.

The supplementary [tick attestation](reviews/loops-fresh-rehearsal-2026-09-18/tick-attestation.json)
verifies the actual new tick's inner TICK signature and physical predecessor.
Tick envelopes intentionally have no outer Arrival signature. This was a
read-only check of the original commit range, with unchanged full-store SHA-256.
Because the original returned tick Commit record was not saved, the retrospective
artifact leaves that equality field null; new `--expect-tick` runs check it in
process. The complete chain comparison independently verifies the new window.

Final review: Fable accepted the core corrections in its second pass. Its final
focused call hit the CLI session limit; Luna independently closed the remaining
tick-attestation finding with no P1/P2 blocker. Final tests: engine 2,650 passed,
1 skipped; repository 132 passed; CLI absorb 23 passed; earlier full SDK 614 and
lang 721 passed. Scoped lint and whitespace checks pass. The final third-call
[review receipt and closure](reviews/fresh-epoch-fable-r3-2026-09-18/primary-triage.md)
distinguish actual review coverage from the refused invocation.

## Accepted transformed-history verification

The user accepted the historical review meaning of the preserved boundaries with
an audited observer mapping and requested provenance-aware verification. The new
read-only `scripts/verify_legacy_provenance.py` proves the complete relationship
using independently reviewed original/manifest hashes and migration head S.
It does not change the normal deep audit or rewrite any commitment.

The loops-copy rerun passed with status
`preserved-boundaries-with-audited-transformation`:

- All 4,478 source rows are accounted for: 982 mapped facts and 3,496 byte-identical
  rows. IDs, payloads, order, and all historical tick fields are preserved.
- The original 121-tick chain passes. Exactly 39 historical windows are explained
  by the mapping; 82 still match unchanged.
- Arrival preserves all prepared rows in order through S=4483, behind six
  signature-verified protocol metadata records. The full record hash chain
  passes through the same final head at ordinal 4486.
- The post-migration tick passes predecessor/cursor/window checks. The verifier
  has no historical-first-ten diagnostic cutoff or broad exception rule.
- Substituting a wrong reviewed manifest hash or wrong S record hash refuses
  with no success output. All four inputs and the live source/vertex remain
  byte-identical.

The signed migration report was separately reverified under the reviewed public
key, and its source hash and S match the pinned evidence. The provenance result
itself deliberately does not claim to authenticate every historical author or
reverify the migration report signature.

[Verification evidence](reviews/loops-provenance-rehearsal-2026-09-18/evidence.json),
[report attestation](reviews/loops-provenance-rehearsal-2026-09-18/migration-report-attestation.json),
and [preservation checks](reviews/loops-provenance-rehearsal-2026-09-18/preservation-check.json)
record metadata only. The [cutover plan](loops-live-cutover-plan-2026-09-18.md)
prepares the remaining publication and writer-handoff work; it does not execute
a live switch. This provenance pass resolves the accepted historical-commitment
interpretation, while preserving the standard audit's distinct result.

Final provenance review: Fable returned **ACCEPT**, no P1/P2 blockers, after
correcting receipt scope, historical unchained handling and targeted refusal
coverage. Final repository validation is **163 passed**, including **31 provenance
cases**. The [acceptance receipt](reviews/legacy-provenance-fable-r3-2026-09-18/primary-triage.md)
records scope and remaining cutover preparation. No live switch occurred.
