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
