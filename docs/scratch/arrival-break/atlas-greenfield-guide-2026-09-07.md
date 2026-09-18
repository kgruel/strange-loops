# Atlas greenfield CLI guide replay

Status: exact command replay and primary receipt audit PASS; Fable-low and primary **ACCEPT**, no blockers.

Checkpoint `d4e5792d` contains the accepted setup/recovery and migration-publication
work. This subsequent documentation exercise adds a fresh-store how-to in
[the Loops guide](../../guides/atlas-greenfield-cli.md), linked from the minimal
CLI reference. No runtime code changed.

Root wrote the guide, Terra audited the Atlas contract, Sol reviewed the command
surface and wording, and Luna extracted/executed the six Bash blocks in a single
Bash process with cwd `/Users/kaygee/Code/gruel.network/docs/atlas`. Root independently
checked all saved receipts and export bytes afterward. The native guide exit
was **0**, and **14 CLI invocations** produced successful SDK envelopes.

The installation used a fresh UV_PROJECT_ENVIRONMENT and isolated state/config,
credentials, descriptor, Arrival File, projections and outputs under a scratch
root. It installed the modular loops-min/SDK stack without legacy loops or
Painted. The guide uses `uv sync` rather than relying on the worktree's prior
environment. Its lock resolution may update the checkout's ignored uv.lock;
`--frozen` is deliberately not required because that file is not tracked.

## Captured input and results

- Loops checkpoint: `d4e5792d5dacaaf214251b09a7a609e9140b5eaa`.
- Atlas schema 1, photographs/configured, revision `13deac5f206a220fbe79019b121bd38d120cdef33b82d4d450ff8f5d3bce8724`.
- Input byte SHA-256: `5a61c40e7b0c62480fadae44dcdff21305024e022bde2bf1caaf0f3e368cddd5`.
- Captured model: 13 entities, 18 relationships,
  20 source selectors; whole model preserved in folded snapshot.
- Exact executed script SHA-256: `bdcedaf583e0bff24fe457dde222626101312de6d49fcac5a1386b6d759c67bd`.
- Init head ordinal1 → declaration2 → atomic two-item batch3 → follow-up4,
  with exact non-null before/after lineage/hash continuity checked.
- Batch items and follow-up report signed/stored/witnessed; successful projection
  outcomes are retained. Declaration and initialization have their own result
  shapes, not invented uniform signing fields.
- Final state, history, inspection, verify, sync and export name the same head.
- Both note payloads remain in non-truncated history; the subject fold changes
  from question to follow-up. No live backing-storage conclusion was invented.
- Export is byte-identical to the captured ledger: 19082 bytes,
  five wire records, manifest through ordinal4 and exact final record hash.
- Atlas input bytes and gruel.network git status are unchanged. Existing
  untracked `.loops/audit/` and `.loops/homelab-audit.vertex` were left alone.

The guide's later edits only clarified prose and linked this record; its Bash
blocks still match the executed script byte-for-byte. Recovery examples are
non-executed `text` blocks, not claims of interrupted-operation testing. No
browser integration, generated graph update, existing-store migration,
credential transfer, publication or deployment was performed.

## Evidence and review

Only explicitly selected command text, native logs/status, input metadata and
primary audit output are archived in the [review directory](reviews/atlas-greenfield-guide-final-2026-09-07).
Fixture stores, complete receipt directories, private keys and virtual environments
remain outside the repository. A preliminary audit formatter confused Commit
and Head shapes, and a later checker assumed a nonexistent export field; these
were audit-tool errors, not guide failures. The authoritative root checker
asserts the actual before/after and manifest fields and exits zero.

Initial Fable review requested prose revisions. Its execution-mode finding
was accepted: instructions now explicitly save/run the six blocks as one Bash
script, matching the native replay. Its claimed absence of declaration head/
phase was contradicted by the actual receipt; the simpler status/commit wording
was nevertheless adopted. No command bytes changed.

The archived before/after gruel statuses matched during the replay and initial
successful root audit. A later check observed an unrelated concurrent edit to
`scripts/generate-docs.py`; that edit is outside this task and was left alone.
The correction check therefore compares the final guide's command bytes with
the already executed script and retains the original native audit, rather than
claiming the external repository stays globally unchanged afterward.

Fable-low's [correction review](reviews/atlas-greenfield-guide-correction-2026-09-07/correction-findings.md)
accepted the updated instructions and explicitly withdrew the false field-shape
finding. Primary [triage](reviews/atlas-greenfield-guide-correction-2026-09-07/primary-triage.md)
is ACCEPT. Correction sources matched at closure; only maintained status/handoff
changed afterward. The guide and reference link are uncommitted;
`d4e5792d` itself is already committed and has not been pushed.
