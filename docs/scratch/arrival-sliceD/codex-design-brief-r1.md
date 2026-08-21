# Codex review brief — slice D design proposal (r1, sol LOW)

Repo: this checkout, branch `feat/arrival-libs` @ c5e684fa. **Review-only: do
not modify any file.** Your target is a DESIGN DOCUMENT, not a diff:
`docs/scratch/arrival-sliceD/design-proposal.md`. It proposes slice D of the
arrival substrate migration and is awaiting ratification. Your job is to break
it before implementation starts.

## Context you should read first

- The proposal itself (the review target).
- The ruled contract it implements: quoted verbatim in the proposal's
  "The contract" section (plan:arrival-libs-slice-D).
- Design artifacts: `docs/scratch/arrival-branch-review/design-artifacts/`
  (1-the-arrival-substrate.md §3/§9, 3-the-arrival-plan.md §3D).
- The findings that motivated the slice: CX-DC-01/02/03 in
  `docs/scratch/arrival-branch-review/codex-r3-stdout.log`.
- Source under `libs/engine/src/engine/` and `libs/store/src/store/` wherever
  the proposal cites it. **Primary-source every load-bearing claim you rely
  on; the proposal's citations are claims, not authority.**

## What to attack

1. **The four "already true" claims** (proposal §"Four things that are already
   true"). Each removes designed work; a false one silently under-scopes the
   slice. Verify against source: (a) no persisted witness positions anywhere
   (is the in-memory-only claim actually exhaustive — checkpoints, caches,
   sidecar files, apps/?); (b) signed tick bytes contain no rowid ANYWHERE
   (including legacy jsonl_store paths and verification-side re-derivation);
   (c) audit_derived_log's set-membership semantics actually match what the
   plan means by "jsonl comparison becomes set-membership"; (d) the
   _suffix_unindexed dissolution argument — does walk_marked's anchor check
   really cover the threat _suffix_unindexed covered?
2. **D0**: the (arrival_ordinal, arrival_seq) projection columns and legacy
   backfill option (a) (`arrival_ordinal = rowid`). Attack: mixed stores,
   partially-migrated indexes, the monotonic-assignment rule for plain
   SqliteStore.append, uniqueness/NULL constraints, and whether the
   "identical row set and order" equivalence in D2 actually holds in
   mixed-id-era stores.
3. **D2 backward verifiability**: the claim that re-keyed window selection
   enumerates the same rows in the same order as rowid selection for every
   existing store. Construct a counterexample if one exists (out-of-order
   admission, merge-admitted records, batch records, re-derived indexes).
4. **D1**: the new WitnessPosition model — the empty-prefix sentinel change
   (0 → -1), the arrival_lineage="" spelling for legacy/storeless, the
   same-path replacement guard, and whether the verbatim-survival criteria
   (WitnessAggregateUnsupported, A10) genuinely survive as claimed.
5. **D3**: the per-check disposition table — does any legacy detection
   capability silently disappear (things _check_offset/_check_last_line
   caught that no new check catches)? Is the L1 cheapness fence
   (no ArrivalLog.read/walk on L1) actually achievable with walk_marked?
6. **D4 arm 1**: source-side verification at admission — is the dependency
   claim right (no libs/sign import needed)? Does verify_authorship's
   key-resolution-from-source-log actually cover merge's admission set, or
   can records enter admission that authorship verification never sees?
7. **Gate coverage**: does the G-* list actually pin every decision? Name
   any decision with no gate item, and any gate item that cannot fail.
8. **Contract conformance**: anything in the proposal that contradicts the
   quoted ruled scope, the done-criteria (preflight untouched; verbatim
   survivals; federated-read vs admission), or the arc's scope law
   (apps/ diff-empty) beyond the flagged open questions.

## Do not re-report (settled rulings)

- The arrival substrate direction itself, slices 0+A-C, and their ruled
  deviations (envelope, stored ordinals, `at`, shared batch ordinals, ts
  envelope key, ordering-only checkpoint dispatch).
- CX-BR-01/03 fixes (a95c8f2b, 45fc6fd5) — already re-verified in r2.
- The eight open questions the proposal itself flags — those are already in
  front of Kyle; only report on them if a recommendation is factually wrong.

## Verdict format

Findings as `DP-r1-NN` with severity (MAJOR / minor / note), the proposal
section attacked, file:line evidence, and a one-line fix direction. Then a
per-decision verdict table (D0-D4, gate plan): SOUND / UNSOUND / SOUND-WITH-
CHANGES. Close with an overall RATIFIABLE / NOT-RATIFIABLE-AS-WRITTEN call.
Deliver everything in one response.
