# S2 GATE — independent verification of slice/s2-plan-apply-recovery

Gate target: `e6afc07f` (merge-base includes `debb2e6e` — confirmed ancestor).
Contracts: LIBS_CHANGES.md P0.2 ("one declaration-update orchestration API") +
P0.3 ("recoverable file/store declaration synchronization"), plus the ratified
S1a encoding. The impl report was treated as a target, not an authority: all
oracle claims re-run from scratch with an independent driver (80 counted
checks plus targeted probes for deviation 5, unsigned-refusal, and AST-only
recovery; both backends).

## Verdict table

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Suites | **PASS** | engine 1402 passed / 1 skipped; store 111 passed; loops 2521 passed / 1 xfailed; root 59 passed — exact match with the impl report, re-run on the committed tree. |
| 2 | End-to-end, own driver, both backends | **PASS** | Genesis plan→apply then one edit ceremony covering add+modify+retire (3 changes). Verified through `resolve_declaration_documents` (not the API's return): resolved projection fingerprint == independently computed projection of the proposed source, both backends. No `*.tmp` residue in the vertex directory after any ceremony. `audit_deep` green after every JSONL ceremony. Log grammar read from raw bytes: genesis = exactly one plain `_decl.genesis` fact line, no batch; 3-change edit = exactly one `"t":"batch"` line with 3 inner rows (S1b grammar holds). |
| 3 | Stale / concurrency | **PASS** | Two plans, first applies, second apply → typed `stale`; JSONL log sha256 byte-identical across the refused apply; `.vertex` bytes untouched; no intent residue. Genesis flavor: second genesis apply → `stale` ("lineage opened since plan" via `GenesisExists`), no residue. Both backends. |
| 4 | Interrupt / recover | **PASS** | Injected raising `write_file` → typed `needs-recovery`, durable intent left at the sibling path. Recover → `safe-to-finish`, `finished=True`, file completed atomically, intent cleared, `audit_deep` green. Second recover → `already-applied` no-op. Corrupt intent JSON → `IntentCorrupt` raised, intent file NOT deleted, nothing else touched. Index-loss path verified end-to-end myself: delete `.db` in the needs-recovery state → recover rebuilds the index from the log and raises `UnadoptedLineage` (the S1b marker is never inferred from a rebuild); `adopt_lineage()` then recover → `safe-to-finish` finished, file matches the proposal, audit green. Also verified the two extra recovery classes: `not-applied` (intent durable, store never committed → intent discarded) and `conflict` (another writer landed → intent AND file byte-identical afterward). |
| 5 | Claim check: "ratified S3 CredentialProvider" | **PASS with correction** | The slice reference is **confabulated; the mechanism is sound.** `CredentialProvider` is real — `libs/engine/src/engine/handle.py:172`, introduced 2026-07-17 in commit `d22f614d` ("VertexHandle **S3** — write-through, operation-fresh credentials"), i.e. the *VertexHandle arc's* S3, not this wave's S3 (admission policy). The report's phrasing borrows the wrong "S3". DAG claim holds: `ceremony.py` imports only `engine.*`/`lang`/`atoms`; root `tests/test_architecture.py` (59 passed) enforces no engine→custody. Signing equivalence verified empirically: signatures are minted *inside* `absorb_genesis`/`absorb_edit` over `_fact_commitment_hash(kind, ts, observer, origin, payload_text)` — the final persisted payload; my driver recomputed every persisted `_decl.*` signature from the log bytes and matched byte-for-byte. The CLI's `_absorb_*` passes `fact_signer=fact_signer_for(target_path)` into the same absorb functions (`apps/loops/src/loops/commands/store.py:1174,1360`) — the paths are equivalent per the ratified proposal. |
| 6 | Intent placement + pending semantics | **PASS with findings** | Sibling `<name>.vertex.intent` confirmed. Pending intent blocks plan (`applicable=False`, typed reason) AND apply (`pending-intent`). Intent is durable bytes: written tempfile+fsync+rename before any mutation; survives process death (needs-recovery state carries it). Recover after a completed ceremony removes it; verified. Collision probe: two vertexes (`x.vertex`, `y.vertex`) sharing one directory get distinct intent files and do NOT cross-block — verified live. Two findings: (a) **no parent-directory fsync** after the rename in `_atomic_write` — but `JsonlStore` never dir-fsyncs either, so the "JsonlStore durability discipline" claim is accurate as stated; shared, pre-existing limitation, not a FAIL. (b) **TOCTOU on the pending gate**: `apply` checks `pending.exists()` then writes the intent via rename (not `O_EXCL`); two racing applies can both pass the gate — the store CAS keeps data safe (loser gets `stale` inside the transaction), but the loser's intent write can clobber the winner's intent evidence in the race window. Scoped: the "blocks" claim holds for sequential use; the concurrent-evidence edge is unpinned. Recommend `O_EXCL` intent creation in a follow-up. |
| 7 | Deviations 1–5 | **PASS with one wording correction** | (1) `not-applied` class: real and reachable — verified (intent written, store untouched → intent discarded). (2) Index-loss adoption: verified end-to-end (item 4). (3) AST-only plans: `proposed_text=None`, apply `file_written=False`; interrupted AST-only recovery → `safe-to-finish` with `finished=False`, intent retained, disclosed reason — verified both backends. (4) CLI untouched: `git diff --stat debb2e6e..HEAD` touches ONLY `engine/` + scratch docs — zero `apps/loops` files, so goldens cannot have moved; loops suite 2521 passed unchanged. (5) **Wording inaccurate, behavior sound**: a store with genesis rows and no marker does NOT "plan as genesis" — a fresh `plan` over it RAISES `UnadoptedLineage` (propagated from `declaration_generation`, `declaration.py:353`). The refuse-at-apply path is real but only reachable with a preview captured pre-genesis (race construction): apply then returns `refused` ("no own_lineage marker — identity cannot be inferred"), no intent residue — verified on both backends by stripping `store_meta.own_lineage` after plan. Fail-closed either way; the report's sentence overstates plan's tolerance. |
| 8 | API surface | **PASS** | `engine/__init__.py` exports all 9 names (3 functions + `intent_path_for` + 3 result types + `CeremonyError` + `IntentCorrupt`), lazy-import wired. All three result dataclasses `frozen=True`; `preview.changes`/`documents` are tuples (Change is a NamedTuple). Vocabulary closed as documented: apply returns exactly {applied, noop, stale, pending-intent, refused, needs-recovery} (all six observed); recover returns exactly {already-applied, safe-to-finish, not-applied, conflict} (all four observed). Two disclosed edges: `safe-to-finish` with `finished=False` (AST-only — deviation 3, honest half-state) and **plan/recover can raise `DeclarationResolutionError` subclasses** (`UnadoptedLineage`) and parse/validation errors — exceptions, not typed results, consistent with "malformed input raises" but worth a docstring note since `UnadoptedLineage` is an *environmental* state, not malformed input. Minor: `preview.generation` is a plain mutable dict inside a frozen dataclass — cosmetic. |

## Overall: **PASS**

Every P0.2/P0.3 contract behavior verified independently on both backends.
Findings for the wave ledger (none blocking):

1. Impl-report provenance error: "ratified S3 CredentialProvider" cites the
   wrong S3 — it is the prior VertexHandle-arc S3 (`d22f614d`), not this
   wave's admission-policy S3. Mechanism verified sound and CLI-equivalent.
2. Deviation-5 wording: fresh plan over an unadopted-with-genesis store
   raises `UnadoptedLineage`; only a pre-genesis-captured preview reaches the
   typed apply refusal.
3. Pending-intent gate TOCTOU (intent written by rename after an exists()
   check) — winner's intent evidence clobbable in a concurrent-apply race;
   store data safe via CAS. Suggest `O_EXCL`.
4. No parent-dir fsync after intent/file rename — matches JsonlStore's
   existing discipline; shared limitation, disclosed.

Gate driver: 80 counted checks plus targeted probes, both backends, all substantive checks
green (the single driver "failure" was the deviation-5 construction that
produced finding 2). Suites re-run exactly match the impl report.
