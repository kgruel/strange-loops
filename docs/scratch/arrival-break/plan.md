# Arrival backend-neutral break — implementation plan

## Context

Last session ratified the Sol architecture suite (`docs/architecture/arrival/`, five HTML docs) as the backend-neutral 1.0 full-break target: arrival is a **protocol** (one ordered, verifiable history per lineage, one authoritative append head), not a mandatory file — a `.arrival` file is one backend. Anchors: `decision:design/arrival-backend-neutral-protocol` (parent ruling + deletion list), `decision:design/arrival-wire-v1-seam-triage` (drop `body.t`, re-spell tick observer, keep dual signature), `decision:design/arrival-suite-review-dispositions` (witness minimum, counts optional, head-attestation naming, descriptor-in-`.vertex`, DuckDB-as-example). MERGE and ADOPT are ruled separable. This plan sequences the break end-to-end: merge the converged branch, execute the triage, extract the backend contract, build the witness minimum and migration sidecar, delete the legacy modes, adopt `.arrival` for live stores.

**Load-bearing state** (verified this session):

- `feat/arrival-libs` is 252 ahead / 0 behind main, local-only. Zero `.arrival` stores exist anywhere (verified in the triage fact) — envelope changes are still free.
- Every live store is jsonl-canonical (production shape per engine CLAUDE.md): `~/.config/loops/*` vertices and the git-tracked repo store `.loops/data/project.jsonl`.
- **Release constraint**: Kyle's daily `sl` is the PyPI install (0.11.0), so merging the deletion wave breaks nothing day-to-day; the cost lands at release. Consequence: **1.0 cannot ship until every live store is migrated**, and mid-arc the repo-dev runtime cannot read unmigrated stores. This is what makes the late deletion wave safe.

## Vehicle

impl-pipeline (design-fact-as-contract, per-slice empirical gates, cross-family sol-HIGH review to convergence, simplify pass). **First act after plan approval: emit the design fact** (`design:arrival-break-implementation`) binding the four decisions + suite as the contract — plan mode forbids emitting it now. Model routing per standing memory: impl/gate/apply workers `opus`, exploration `sonnet`.

## Phase 0 — Merge (pre-pipeline, immediate)

1. `git fetch` + fast-forward local main first (stale-main trap), re-verify 0-behind.
2. Disposition the stray untracked `docs/scratch/arrival-sliceD-impl/sol-wp1-r3-brief.md` (commit into the branch's scratch trail or drop — Kyle's call at merge time).
3. PR `feat/arrival-libs` → main, `--no-ff`, CI green gate (11 jobs). Ratified safe: keeps ~200 converged commits, steps no cost curve.

## Slice 1 — Wire v1 pin (seam triage execution)

**Gate at head: tick-observer design session** (Kyle; scheduling ruled 2026-08-26 in-plan). Agenda: empty observer vs custodian identity, plus the widened seam found this session — envelope `observer` also echoes `body.observer` for *fact* records (body already sits inside the outer commitment), so the session re-derives what the field is *for* across all kinds before pinning. Output: sub-ruling appended to `decision:design/arrival-wire-v1-seam-triage`.

Then, per the ruled triage:

- **Drop `body.t`**: fork the arrival body encoding from the legacy line codec. Today `jsonl_codec.py:160` (`_encode_obj`) writes `t` and `jsonl_codec.py:430` (`records_from_object`) dispatches on it; the arrival write site is `arrival_store.py:458`, the read-back site `arrival_projection.py:168`. Arrival bodies stop carrying `t`; arrival decode dispatches on envelope `k` (the projection site holds `k` when it hands body over). The legacy codec keeps `t` — the sidecar's LegacySource needs it in slice 4.
- **Re-spell tick observer** per the sub-ruling (`arrival_store.py:462` — currently the tick's name).
- **Dual signature: no change** (ruled keep — principled pair, not a seam).
- Regenerate conformance vectors + fixtures (`spec/conformance/vectors/`: fold 16 / merge 10 / lens 7 / witness 5 / replay 2, arrival exercised through the generators). Mechanical; the behavioral convergence (atomicity, refusal postures, sol-HIGH r6) does not reopen. Inner fact commitments never covered `t`, so no preserved signature is invalidated.
- Pin wire v1: update `wire-format.html` (envelope table minus the seams, status flip), emit the pin as a decision fact.

## Slice 2 — Backend contract extraction

The suite's ratified "first implementation sequence" step 1: *extract the current file behavior behind the interface first, preserving its tests.*

- **Contract surface** (backend-contract.html §interfaces): types `Head`/`RecordDraft`/`Commit`; operations `mint`/`head`/`append`/`replicate`/`read`/`scan`/`verify`/`export`/`capabilities`; hard `ArrivalLedger` (custody) vs `ArrivalQuery` (reads) separation — no mutation escape hatch from a query handle. Placement designed by the worker (engine-level protocol module).
- **File backend**: existing `ArrivalLog` + `ArrivalStore` (`engine/arrival.py` 1845 ln, `engine/arrival_store.py` 685 ln) adapted behind the contract — wrap, don't rewrite; the 14 arrival test files keep passing.
- **SqliteStore split named by the ruling** (`engine/sqlite_store.py`, 2860 ln): storage half (`_write_fact_row`/`_write_tick_row`/`_ceremony_persist` seam, :1308–1401) becomes the file backend's projection engine; mint half (`append*`, `fact_commitment_hash` :271–299, coordinate machinery `_stage_arrival_coordinates`/`_stamp_arrival_axis`) extracts into admission. Note: `engine/admission.py` exists but holds *declared-policy* enforcement (grants/strict) — under the substrate laws intake authorization is part of custody, so whether mint-admission joins that module or gets its own home is a worker design point, flagged for review.
- **BackendRegistry + explicit declaration**: `.vertex` `store` clause grows an explicit backend arm (KDL shape designed in-slice; parse sites `lang/ast.py:705`, `lang/loader.py:769–880`); `BackendRegistry.open(descriptor)` → `(ArrivalLedger, ArrivalQuery)` replaces suffix inference as the resolution path. `residence.py`'s `canonical_mode` (:85–105) keeps working through slice 4 — its deletion lands in slice 5. The CLI's twin resolvers (`store.py:52–100`) already encode the canonical-vs-index split the contract ratifies — rename into the contract, not a redesign.
- **`replicate` is net-new** (seam finding #1): no code anywhere preserves `(lineage, ordinal, prev, record_hash)` exactly — every existing write path re-coordinates, i.e. is admission. Build `replicate` in this slice, **before** any transport/receive re-expression, or stale-replica catch-up ships silently as admission (hash-divergent copies of the "same" lineage).
- **Admission op extracted from `_merge_into_arrival`** (`store/merge.py:244–322`) — extraction, not redesign: its `append_marked_many + AppendRejected` retry loop already implements contract §04 steps 1–8, modulo the F1 gap. Close **F1** here: the CAS pin compares ordinal only (`engine/arrival.py:1392`); the contract requires comparing all head fields (lineage, ordinal, record_hash) — strictly stronger, no contract change.
- **Decision point at slice gate — F2**: "verification must not repair" is held carefully by the dying code (`store.py:130–136`, `canonical_audit.py` never opens a store) but is *unstated* in the backend contract's verification levels. Candidate contract addendum for Kyle's ruling; the most valuable invariant the deleted code holds.

## Slice 3 — Witness minimum (head attestation)

Ratified scope ONLY (dispositions §1/§2): a head cached outside every authority + a bootstrap receipt at migration + compare-on-every-open + a periodic full chain-plus-projection audit entry. **No** signed-attestation grammar, notary, or quorum — deferred until a consumer forces it.

- New primitive — nothing exists to refactor (nearest analogs are the genesis record as "attestation root" and `witness.py`'s `TickAnchor`, which is a fold cursor, not custody memory).
- Vocabulary: **head attestation** in code (Rule 18 glossary join); `engine/witness.py` keeps "witness" for the read-path cursor. Distinct types, distinct serialization names.
- Comparison state machine (witness-protocol.html §comparison), v1 refusal subset: unchanged / advanced / rollback / same-height fork / rewrite / replacement — refusals typed, never silent re-acceptance.
- Open detail at slice head: the head-cache home (must sit outside the store file's rewrite boundary; exact location is a slice-level design point, not pre-decided here).
- **Sequencing constraint, explicit: slice 3 precedes slice 4 because the sidecar emits the bootstrap receipt** — the receipt primitive must exist first.

## Slice 4 — Migration sidecar

Frozen `LegacySource` → `Transformer` → `ArrivalSink` (protocol.html §migration; backend-contract.html §sidecar pseudocode). The new runtime keeps **no** compat mode — legacy-format knowledge quarantines here.

- **Not greenfield — `store/rebirth.py` (668 ln) is the existing skeleton** (seam finding): replay-through-deterministic-transform → new store → receipt → genesis seal maps onto mint → append(groups) → verify(Full) → export. Keep its verification-by-re-run as the *sidecar's* verification (stronger than the ledger's `verify(scope)`).
- `LegacySource`: the jsonl-canonical and sqlite-canonical readers move here, frozen (this is where the legacy codec's `body.t` knowledge survives). `ulid_migration()` (`rebirth.py:128–150`, uuid4-era + lowercase-ulid-era knowledge) quarantines here too.
- **`absorb` and `reanchor` demote from store verbs to sidecar ceremonies** (`store.py:948–1380`, `:770–849`): absorb's job is signing genesis over pre-genesis legacy rows — the new runtime has no genesisless stores; reanchor rewrites chain rows in place — impossible on an append-only hash-chained ledger. Semantic demotion, not a port.
- Transformer obligations: map every in-scope row exactly once in ruled source order; preserve authored inner signatures byte-for-byte; **mint genesis + key records from the `.vertex` observers block** (keys move in-log under arrival); respect batch grammar.
- Sink: ordinary contract `append` (no privileged path); restartable only from a verified target head; inventory + equivalence evidence; **atomic descriptor publish** (the `.vertex` store clause update is the cutover) + bootstrap receipt emission; no dual authority — legacy store stays read-only evidence after cutover.

## Slice 5 — Deletion wave + residue sweep

Lands only after slices 1–4 (the sidecar must carry the legacy knowledge before the runtime drops it). **First half of the slice wires the surviving verbs to the contract ops built in slice 2** — portable import, slice-as-scan+predicate, `_run_export` repointing; deletions land only after that rewiring is green, so no verb is stranded.

- **JsonlStore retirement** (`engine/jsonl_store.py`, 1022 ln): first split out the generic dispatch trio (`open_canonical_store` :256, `ensure_index` :323, `resolved_index` :370) into its contract-shaped home — `arrival_store.py` imports plumbing from this file today; then migrate the ~10 production importers (compiler, ceremony, canonical_audit, probe, sdk/declare|types|read, apps store cmd); then delete the class and the mode. (Distinct from `libs/store/src/store/jsonl.py`, already deleted on the branch.)
- **`canonical_mode` three arms + suffix dispatch die** (`residence.py`): callers (compiler, arrival_projection, handle, sqlite_store, probe, vertex_reader, ceremony, arrival_store, canonical_audit, preflight, apps loops store/resolve/ls) resolve through the registry + explicit declaration. **Includes the SDK's public surface** — `sdk/read.py`, `sdk/types.py:91`, `sdk/declare.py:143` carry `canonical_mode` into public API (a third consumer; breaking is legal under the full break).
- **libs/store deletions** (dispositions in the appendix): `merge.py` sqlite + jsonl arms and `_read_index_source`; `receive.py` outright (magic-byte format sniffing the contract forbids; its create arm byte-adopts a foreign projection — neither replicate nor admit); `transport.py` + `_transport_local.py` (contract is literally "moves SQLite files"); `_conn._SCHEMA` collapses into the projection owner (second hand-rolled schema spelling); the arrival-custody guard trio dissolves with mode ambiguity. **One behavior deleted with no successor, by design**: the sqlite arm's silent same-id/different-content target-wins (`merge.py:209–213`) — admission refuses it (MergeDivergence) and replication refuses it (same-height fork); its conformance vector `merge-divergent-collision-target-wins.json` dies with it.
- What **survives above the contract**: `MergeDivergence` + `_verify_admitted_rows` + `_source_registry` (admission policy), `_entry_for` → RecordDraft constructor, slice's filter vocabulary as client-side predicate, `_run_reindex` (projection rebuild), `derived_log_merge.py` (re-labeled file-backend-specific tooling; docstring `:28` re-pointed), `compact.py` (below contract; its `residence.sqlite_sidecars` import is the one surviving residence dependency — pure path arithmetic). `_run_export` repoints to the real `export` op (currently a refusal stub). `_run_adopt` becomes a descriptor operation — where MERGE-and-ADOPT-separable lands in code.
- **F4 free sweep**: `residence.is_jsonl_canonical` has zero production call sites; its Rule 18 allowlist justification is stale cover (the ratchet checks the marker exists, not that its justification holds — a ratchet-practice observation worth a fact of its own).
- **Residue swept in the same change** (dissolution practice): engine `CLAUDE.md` store table (names JsonlStore as production-canonical) + `libs/store/CLAUDE.md` (describes a `search.py` that doesn't exist), Rule 18 grow-list joins (`jsonl_store.py` + the CLI surface — the rule's own comments anticipate exactly these two) plus denylist extensions for newly-retired vocabulary and the swept jsonl allowlist entries, Rule 17 prose sweep, dead tests, docs.

## Slice 6 — Adoption ceremony (operational, not a pipeline slice)

- Order: one **low-stakes store first** (a `dev/*` or `session` vertex) → verify (equivalence evidence, compare-on-open live, read parity) → remaining `~/.config/loops` stores → **project store last** (git-tracked, signed observers, highest stakes).
- **Quiesce each store's live writers for its migration window** (protocol §migration: concurrent ordinary writes on both sides = two histories, not a migration): session hooks (SessionStart orient / SessionEnd emit+seal) disabled for the project store's window, the Discord poller (~60s cadence) stopped for comms; re-enable only after cutover verification.
- **Inventory enumerates stores by reader, not just by directory**: the config-level `project.vertex` aggregates this store + gruel.network via combine — identify aggregated/cross-host stores and their mixed-format windows *before* cutover (an unmigrated aggregated store is unreadable to the new runtime; a migrated one unreadable to old runtimes elsewhere).
- **Scheduled decision at project-store migration** (not pre-made): tracked-vs-gitignored for the migrated `.arrival` — the 111MB friction (`friction:jsonl-canonical-log-exceeds-git-limit`) stands, and the git-hosted backend profile is a future arc.
- Exit: all live stores migrated with bootstrap receipts cached, legacy stores archived read-only. **The 1.0 release ceremony follows this arc; it does not belong to it.**

## Non-goals (scope-the-claim)

- **No rename of `arrival_ordinal`/`arrival_seq`** — under the ratified vocabulary those columns *are* the projected coordinate and are correctly named. (Exploration flagged them as the universal receipt axis across base SqliteStore + witness.py; that is a caution about blast radius, not an obligation.)
- **No filtered-export ledger op** (seam F3): a filtered subset is not a dense prefix, so slice/push-style filtering is `scan` + client-side predicate + admission drafts — do not invent a contract operation for it.
- `FileStore`/`file_writer.py` untouched — not in the ruling.
- Out of arc: DuckDB adapter (next arc — suite step 2, proves neutrality via the cross-backend export oracle), git-hosted backend profile, PostgreSQL, signed attestation/notary/quorum, erasure profiles, authority-transfer ceremony, 1.0 release.

## Verification

- Pipeline-native: independent empirical gate per slice, cross-family sol-HIGH rounds to convergence, dispositions tracked as `finding` facts.
- Slice 1: regenerated vectors round-trip byte-stable; existing inner signatures verify unchanged (commitment never covered `t`).
- Slice 2: all 14 arrival test files green behind the contract unmodified in intent; seed the backend-contract §conformance gates that apply to one backend (CAS race — now full-head compare per F1, injected-failure per append stage, snapshot consistency, export/import/export byte identity); new replicate vectors (exact-suffix accept, same-height-fork refuse, stale-replica catch-up preserves hashes).
- Slice 3: comparison-state vectors (rollback / same-height fork / rewrite refusals) as new conformance family.
- Slice 4: sidecar round-trip on a synthetic legacy store — inventory equality, signature preservation, restart-from-verified-head.
- Slice 5: Rule 17/18 green with grown scope; full suite (5,584 tests) + 11 CI jobs green.
- Slice 6: per-store equivalence evidence + `verify` full pass + read parity against a pre-migration snapshot; project store additionally `verify_chain` + a held-back backup until parity confirmed.

## Cross-slice sequencing spine

The hard ordering constraints, in one place (violating any of these breaks ~30 call sites at once or ships corruption):

1. Dispatch trio (`open_canonical_store`/`ensure_index`/`resolved_index`) splits out of `jsonl_store.py` **before** JsonlStore deletion (importers: merge, resolve, store cmd, vertex_reader ×14, handle, compiler, preflight, ceremony).
2. BackendRegistry + explicit `.vertex` backend declaration land **before** `canonical_mode` deletion (live switch in merge, _conn, probe, preflight, canonical_audit, compiler, ceremony, store cmd, SDK public surface).
3. Admission extraction from `_merge_into_arrival` **before** deleting any merge arm.
4. Export codec **and** `replicate` **before** slice/transport/receive re-expression (all three encode `.db`-as-wire-format today; and without replicate, replica catch-up silently becomes admission).
5. Witness minimum (slice 3) **before** sidecar (slice 4) — the sidecar emits the bootstrap receipt.
6. Sidecar (slice 4) **before** deletion wave (slice 5) — legacy knowledge quarantines before the runtime drops it.
7. The CLI cut is **independent** of the libs/store cut (no CLI consumer of the merge/transport path; sole coupling is rebirth at `store.py:672`, which moves with the sidecar) — order it by constraints 1–2, not by libs/store progress.

---

## Appendix — libs/store + CLI seam disposition table

Full analysis (file:line for every claim): `/Users/kaygee/.config/claude/plans/shimmering-sniffing-canyon-agent-aplan-store-seam-c388a180a9a6553f.md`

| Unit | Disposition |
|---|---|
| `merge.py` sqlite arm + jsonl arm + `_read_index_source` | dies (legacy formats; silent target-wins deleted outright + its vector) |
| `merge.py` arrival arm | re-expresses → `append` + admission (extraction, not redesign; close F1) |
| `merge.py` `_read_arrival_source` | re-expresses → `scan` |
| `MergeDivergence` / `_verify_admitted_rows` / `_source_registry` | survive as admission policy |
| `_entry_for` | re-expresses → RecordDraft constructor (its tick-chain nulling is the admission marker) |
| `_rederive_after_append` | re-expresses → Query projection watermark advance |
| `receive.py` | dies as written (magic-byte sniffing; create arm = byte-adoption, no successor); create-or-merge semantic → §08 portable import |
| `slice.py` | re-expresses → scan + client predicate + admission; ATTACH mechanics die; filter vocab survives |
| `transport.py` + `_transport_local.py` | die ("moves SQLite files") → export → move bytes → import/replicate |
| `compact.py` | survives below contract (file/sqlite admin op); `residence.sqlite_sidecars` is the one surviving residence import |
| `rebirth.py` | re-expresses as the migration-sidecar skeleton; `ulid_migration` quarantines to LegacySource |
| `derived_log_merge.py` | survives; re-labeled file-backend-specific tooling; docstring re-point |
| `_conn.py` `_SCHEMA` | dies (schema spelling collapses into projection owner); `_open`/`_create` survive as file-backend internals |
| CLI `store.py` resolvers / canonical_agreement / per-mode verify | die → registry resolution + `verify(scope)` + watermark (keep "verify must not open" discipline — F2) |
| CLI `_run_export` | repoints to real `export` op |
| CLI `_run_reanchor` / `_run_absorb` | demote to sidecar ceremonies |
| CLI `_run_adopt` | genesis-claiming half dies; survives as descriptor lineage/role designation |
| CLI `_run_reindex`, `ls`/`vertices`/`devtools` readers | survive (Query-profile) |
| SDK `read`/`types`/`declare` canonical_mode surface | dies with the mode (public break, legal at 1.0) |
