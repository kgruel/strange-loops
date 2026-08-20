# Arrival substrate — round 3: DESIGN-CONFORMANCE review

You are the cross-family reviewer from rounds 1–2 (receipts in this
directory; r2 CONVERGED). This round is a different axis entirely: not
"is the code correct" but "is the code THE DESIGN". You are handed the four
ratified design artifacts from the 2026-08-17 design sessions and the full
branch diff; your job is a systematic comparison. **Report only — no fixes,
no remediation proposals beyond naming what a divergence is. The arbiter
will discuss the results; nothing gets mitigated out of this round.**

## Inputs

Design artifacts (extracted text, figures elided, in
`docs/scratch/arrival-branch-review/design-artifacts/`):

1. `1-the-arrival-substrate.md` — the model: the collapse, the five laws,
   ordering generalization, custody boundary, transport, shipping plan.
2. `2-the-arrival-log.md` — the artifact: JSONL ruling, line grammar,
   witness position, genesis three movements, observers/keys, revocation,
   membership, ceremonies/CAS (two frozen scopes, `guarded_append`,
   typed heads), integrity posture, migration touchpoints.
3. `3-the-arrival-plan.md` — the ruled implementation plan: wave shape,
   laws of the arc, slices 0+A–D scope and gates, wave 2 + tail, PR #8
   dispositions table.
4. `4-the-migration-sidecar.md` — the frozen migration ceremony spec.

Implementation: `git diff 406cec31...HEAD` on `feat/arrival-libs`
(141 commits — slices 0+A–D through three convergence rounds plus the
whole-branch r1/r2 fixes). Workspace-write: read anything, run anything.

## Scope calibration — what the branch IS and IS NOT

The branch is **Wave 1 only** (Plan §3: slices 0 + A–D, libs-scoped).
The following are DESIGNED-ABSENT and their absence is NOT a finding:
Wave 2 (SDK `ArrivalHead`/`DeclarationHead` types, `guarded_append`
rename, admission-vs-federated-read API verbs), the sidecar itself, the
interleave-uniqueness vector families, the CLI rebuild, live-store
migration, the monotonic-ref git transport, admission signature
verification (slice D names it "new code"; the r1 round dispositioned it
to the SDK wave). Flag one of these ONLY if the branch prematurely
implements it badly or structurally FORECLOSES it.

Also known and receipted (do not re-find): the apps-diff-empty scope law
was DELIBERATELY relaxed by a ratified cut C ruling (apps/ carries the
jsonl-bridge dissolution sweep); the r1/r2 findings and their
dispositions (`decision:design/arrival-branch-r1-rulings`).

## What to actually do

Walk each design document section by section against the code. For every
design commitment that Wave 1 should have discharged, classify:

- **CONFORMS** — implemented as designed (cite file:line; spot-check, don't
  exhaustively re-prove what three review rounds already gated).
- **RULED-DEVIATION** — differs from the artifact text but a ratified
  decision fact licenses it (name the fact; the project store is readable
  via `.loops/data/project.jsonl` if needed, and `docs/scratch/arrival-slice*/design-proposal.md`
  carry the per-cut rulings).
- **SILENT-DIVERGENCE** — the code does something the design forbids or
  specifies differently, with no ruling on record. These are the round's
  product. Evidence bar: file:line plus the design sentence it contradicts.
- **DESIGN-DEBT** — the artifact says something now known false or stale
  (the code is right, the document drifted). Also reportable — the arbiter
  wants to know which of the four documents can still be handed to a cold
  reader.

High-value zones, from the arbiter:

1. **The five laws as implemented** — especially Law 2's "the substrate
   never learns what ts means" against `ordered()`'s ts-column fast path,
   and Law 5's derived-maintenance against the checkpoint dispatch.
2. **The Log's ceremony/CAS section vs the shipped CAS** — two frozen
   scopes, kind-class predicate, `_decl.*` as contract namespace, the
   "position computed, never stored" rule vs the persisted intent record.
3. **Witness position semantics** — "(lineage, ordinal)", per-record
   ordinals, batch contiguous ranges — vs `record_ordinal`/`fact_id` as
   shipped in the CAS token and the arrival head.
4. **Integrity posture** (Log §10) vs shipped seals/window hashes — the
   facts-only windows rule, the interleave-uniqueness statement.
5. **The Plan's slice gates** — each slice's named gate items: were they
   actually discharged the way the plan specifies (e.g. slice 0's
   two-process concurrency gate, slice A's delete-every-projection
   authority test, slice B's real-git-merge proof, slice D's
   shuffled-index audit vectors)? Gate reports are in
   `docs/scratch/arrival-slice*/`.
6. **The PR #8 disposition table** (Plan §6) — every Keep/Rewrite/Discard
   row, verifiable in the diff.

## Verdict format

1. Per-document conformance table: section → classification → evidence
   (one row per design commitment Wave 1 owed; group CONFORMS rows
   tersely, spend your budget on the other three classes).
2. **Findings list**: every SILENT-DIVERGENCE and DESIGN-DEBT item,
   numbered CX-DC-NN, with file:line and the contradicted design sentence.
3. Overall: a one-paragraph answer to "if Kyle hands these four documents
   to a cold reader tomorrow, where will the code make a liar of them?"
