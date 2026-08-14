# S2 — Implementation report: declaration-update orchestration (P0.2 + P0.3)

Branch: `slice/s2-plan-apply-recovery` (based on `libs-handoff-wave` @ debb2e6e, post-S1b/S5/S6/S7)
Worktree: `.claude/worktrees/agent-a349d8dff41d6e809`
Contract: LIBS_CHANGES.md "P0: provide one declaration-update orchestration
API" + "P0: define recoverable file/store declaration synchronization",
built on the merged S1b ceremony machinery.

## What landed

`libs/engine/src/engine/ceremony.py` (+ exports in `engine/__init__.py`),
oracle in `libs/engine/tests/test_ceremony_orchestration.py`.

- **`plan_declaration_update(vertex_path, proposed_ast=None, *,
  proposed_text=None)`** → frozen `DeclarationUpdatePreview` exposing:
  declaration status + generation (via `declaration_generation`), canonical
  mode/paths (via `probe_target` + residence — no re-spelled residence
  logic), subject-granular changes (`vertex_to_documents` +
  `diff_documents`), captured declaration head (`store.declaration_head()`,
  token-before-fold-head ordering preserved from the CLI so concurrency
  fails conservative), file-vs-store authority, backend applicability, and
  any pending intent. Proposal is validated (`validate_vertex`) before
  anything — invalid declarations never enter the lineage.
- **`apply_declaration_update(preview, *, observer, credentials=None,
  write_file=None)`** — owns the 8-step protocol. Sequence: durable intent →
  S1b store ceremony (`absorb_genesis` / `absorb_edit(expected_head=…)`,
  which holds CAS + sign-final-payload + append in ONE transaction) → file
  replace → intent removal. Typed results: `applied` / `noop` / `stale`
  (reusing `StaleDeclarationHead` semantics; genesis-mode stale =
  `GenesisExists`) / `refused` / `pending-intent` / `needs-recovery`.
  Signing rides the ratified S3 `CredentialProvider` shape.
- **File-cache replacement** — the recommended store-first shape shipped as
  the default: atomic (tempfile + fsync + rename) replace of the `.vertex`
  with the proposed source text, byte-preserving the author's presentation.
  The step is injectable (`write_file=`), which doubles as the oracle-3 kill
  seam.
- **`recover_declaration_update(intent_path)`** — idempotent, classifies
  from fingerprint evidence, never guesses: store projection == proposed →
  `already-applied` (file matches) or `safe-to-finish` (completes the file
  replace, clears the intent); == pre-ceremony state → `not-applied`
  (intent void, discarded); anything else → `conflict` (intent AND file
  left untouched). Second recover after a finish is an `already-applied`
  no-op. Corrupt intent → `IntentCorrupt`, refuses loudly, nothing deleted.

## Design decisions (judgment fences exercised)

- **Free functions, not VertexHandle methods.** VertexHandle is a held
  live read/receive session (lock, cursors, snapshots); a declaration
  ceremony is a one-shot operation keyed on a vertex path. `open_vertex`
  is the composition precedent for path-keyed free functions in
  `engine.handle`; `ceremony.py` follows it.
  (decision:architecture/ceremony-orchestration-free-functions)
- **Intent placement: sibling `<name>.vertex.intent`.** (a) the vertex path
  is the one handle plan, apply, and recover all share; (b) a
  JSONL-canonical store has TWO adjacent artifacts (log + index) with no
  single obvious slot; (c) the store locator is exactly what a ceremony may
  be mid-edit on — the file being reconciled is the stable coordinate.
  Survives process death; discoverable via `intent_path_for(vertex_path)`.
  Pending intent blocks new plan/apply (typed) — that is what makes
  `conflict` non-lossy.
- **Order-independent fingerprints.** Applied-detection hashes documents
  sorted by `(kind, subject)`. Deliberately NOT `declaration_generation`'s
  review fingerprint (order-sensitive, same-source comparator): the file
  projects documents in declaration order while the store fold appends
  added subjects, so an order-sensitive hash would misclassify a committed
  ceremony as `conflict` after a mid-file add.

## Deviations / findings

1. **Fourth recovery class `not-applied`** (extension of the task's three):
   store-first ordering makes "intent durable, store never committed"
   reachable; folding it into `conflict` or `safe-to-finish` would be a
   guess. (observation:implementation/s2-recovery-not-applied-class)
2. **Index-loss recovery requires explicit adoption.** A rebuilt index has
   no `own_lineage` marker (S1b anti-hijack ratchet — identity adopted,
   never inferred), so recovery over a lost index surfaces
   `UnadoptedLineage`; `adopt_lineage()` then recover completes. Pinned in
   `test_recover_after_index_loss_classifies_from_the_log`. Not a blocker —
   the honest behavior given the ratchet.
   (observation:implementation/s2-index-loss-recovery-needs-adoption)
3. **AST-only plans** (no `proposed_text`) mark the default file step
   unavailable; a `safe-to-finish` over such an intent reports
   `finished=False` with a disclosed reason rather than inventing KDL text
   — presentation policy stays app-injected, per the contract's option.
4. **CLI not migrated.** `apps/loops` `_absorb_*` still assembles the
   protocol itself (its output is golden-locked); migrating it onto this
   API is the intended forcing-consumer follow-up slice — sequenced scope,
   not dropped scope. The loops suite passes untouched.
5. Unadopted-store edge: a store with genesis rows but no marker plans as
   `genesis` mode and refuses at apply (`AmbiguousGenesis` → `refused`,
   adopt first) — plan never infers identity.

## Oracle results (all as real tests; 29 passed, 1 skipped)

Parametrized over BOTH backends (`jsonl` / `sqlite` canonical) throughout:

| # | Contract | Tests | Result |
|---|----------|-------|--------|
| 1 | end-to-end plan→apply: genesis, then add/modify/retire through declaration resolution; `.vertex` replaced atomically; store authoritative | `test_plan_exposes_genesis_shape`, `test_genesis_plan_apply_end_to_end`, `test_edit_plan_apply_add_modify_retire`, `test_unchanged_file_is_a_noop`, `test_unsigned_apply_refuses_and_leaves_no_intent` | pass |
| 2 | stale preview refuses: log byte-identical, file untouched, no intent residue (edit CAS + genesis `GenesisExists`) | `test_stale_preview_refuses_log_byte_identical_file_untouched`, `test_stale_genesis_preview_refuses` | pass |
| 3 | interrupt-then-recover idempotence: kill between store commit and file replace (injected raising `write_file`), recover = safe-to-finish + completes, second recover = already-applied no-op; concurrent-writer conflict clobbers nothing; void-intent not-applied; pending-intent blocks; corrupt intent refuses | `test_interrupt_then_recover_safe_to_finish_then_noop`, `test_recover_conflict_leaves_everything_untouched`, `test_recover_not_applied_discards_void_intent` (+ genesis flavor), `test_pending_intent_blocks_plan_and_apply`, `test_corrupt_intent_refuses_loudly`, `test_recover_after_index_loss_classifies_from_the_log` | pass |
| 4 | `audit_deep` passes after every ceremony | asserted in every JSONL-path test above | pass |

## Gates

- `uv run --package engine pytest libs/engine/tests` — **1402 passed, 1
  skipped, 0 failed** on the committed tree. (The 4
  `test_topology.py::TestTopologyCacheResolution` failures the S1b report
  pinned as pre-existing turned out to be a stale-install artifact — they
  pass here after a workspace reinstall.)
- `uv run --package store pytest libs/store/tests` — 111 passed (untouched).
- `uv run --package loops pytest apps/loops/tests` — 2521 passed, 1 xfailed.
- root `uv run pytest tests` (architecture DAG) — 59 passed.
- `ruff check` over all touched files — clean.
