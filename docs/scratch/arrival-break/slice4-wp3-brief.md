# Slice 4 WP3 — the ArrivalSink: staging, restart, verification, publish

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp3

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp3 && `. First action:

    cd /Users/kaygee/Code/loops-wt/s4-wp3 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp3` cut from main AFTER the WP2 merge — `libs/migrate` must contain
`legacy_source.py` and `transform.py`; if not, STOP and report (stale base). Test env:
`TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp3/.tmp` and pytest `--basetemp=.../.tmp/pt` for
migrate tests; any ENGINE-suite run uses `TMPDIR=/private/tmp/s4wp3-tmp` (create it) — one
engine test asserts the state root is not under $HOME.

## EXECUTE YOURSELF — DO NOT DELEGATE

There is no one to hand this to. Deliver everything in one response.

## Contract (ratified — deviations reportable, never decidable)

You implement WP3 of `design:arrival-break-slice4-migration-sidecar`: the sink that takes
WP2's deterministic draft sequence into a real arrival store, restartably, with the
verification-by-re-run gate and the atomic descriptor publish. Read FIRST:
`docs/scratch/arrival-break/slice4-design-proposal.md` §C, §D, §E, §H, §I, §J.1 (WP3),
§J.2 — and the WP2 surface you consume: `libs/migrate/src/migrate/transform.py`
(`transform()`, `TransformResult`, `GenesisRequirements`), `legacy_source.py`,
`inventory.py`, `refusals.py`. Binding rulings:

1. **Ordinary contract path only.** The target opens through `BackendRegistry.open` on a
   staging descriptor; drafts append through the registry-wrapped `AttestedLedger` — no
   privileged path, no direct `ArrivalLog` writes, no reaching around the seam
   (`arrival_head_seam.py:19-23` says the sidecar needs no exemption; honor it).
2. **First touch is `mint()` through the wrapper** — never open-then-mint, never a direct
   `bootstrap()` call. The mint writes the bootstrap journal entry as a consequence
   (`arrival_head_seam.py:1642-1669`). Pre-flight the journal side FIRST (§D.3): resolve
   the state root, create `heads/` if absent, write-and-remove a probe entry — so the
   common `NotWitnessed` causes are eliminated while failure is still free. The residual
   (disk fills between probe and genesis) is named in the module docstring, not detected.
3. **Staging path is LINEAGE-NAMED** (ratified M-2): `<store-dir>/<lineage>.arrival` where
   `<lineage>` is the freshly minted lineage id. A fresh attempt mints a fresh lineage at a
   fresh path (PRE_GENESIS branch; no binding, no journal). NO rename at cutover — the
   descriptor names the staging path directly. An abandoned attempt stays as read-only
   evidence. The sidecar NEVER runs trust-reset, never clears a binding, never touches the
   abandoned-epoch fence (interim law refuse-and-re-decree;
   design:arrival-reset-descendant-acceptance is open at Kyle's slice-6 gate — the module
   docstring states this).
4. **Resume is DERIVED, never stored** (§D.1): on restart, open the target through the
   registry, take the seam-vouched head, re-run LegacySource+Transformer from the start,
   diff the expected prefix against the target's scan through the head — any mismatch is a
   typed REFUSAL, never a repair (F2: verification-never-repairs; the absent⇒create
   carve-out covers only a target that does not exist yet). Resume appending at the first
   expected record beyond the head. No cursor file, no sidecar-side state.
5. **Torn-tail target → typed refusal, no repair** (§D.3): `truncate_torn_tail` stays
   unreachable; the refusal names target + condition, with the out-of-band recovery as
   advisory prose only (content-vs-storage discipline: the type asserts what the read
   lacks, never a remedy).
6. **Verification = BOTH gates** (§I.2): `verify(Full(through=head))` on the target
   (internal consistency) AND the equivalence re-run (re-derive expected rows from the
   unmodified source, compare row by row over the logical row fields
   `(kind, ts, observer, origin, payload_text, signature)` with the transform's id
   mapping; framing/ordinals excluded — consistent with the inner commitment). Both run;
   the report carries both answers.
7. **Atomic descriptor publish** (§H): surgical `.vertex` store-clause edit (there is no
   KDL writer — raw text editing is the repo precedent), then re-parse and assert: parses,
   names the new location/backend/lineage, and EVERY other parsed field equals the
   pre-edit parse (verification-by-re-parse). Write temp file in the same directory,
   fsync, `os.replace`. Publish REFUSED unless all five preconditions hold (§H.2): target
   verifies Full; equivalence re-run matches; journal's FIRST entry for the lineage is
   bootstrap/MINT; inventory equality (per-kind counts, tick count, observer census —
   record counts deliberately NOT compared, §I.3); source content hash unchanged since
   snapshot (ratified M-5 — a changed source is "two histories, not a migration", typed
   refusal).
8. **The migration report** (§I.1, ratified M-3): `<lineage>.migration-report.json` beside
   the target, signed by the custodian, referenced by nothing in the ledger. Fields per
   the proposal's table: source format + tool version, both source hashes (content =
   verifiable, file = forensic, rationale preserved), source inventory, target head
   (lineage/ordinal/record_hash), exceptions (keyless declared observers, undeclared row
   observers, dropped units with coordinates — from WP2's TransformExceptions), the
   transform rule name and the re-run diff result. Signing: the custodian's Ed25519 key —
   use engine's Signer (same as WP2's key introductions); the signature covers the
   canonical JSON bytes of the report body (document the exact byte recipe in the
   docstring).
9. **Legacy store is never mutated** and never re-opened for write after cutover; the
   sidecar does not delete it (operator decision, slice 6).

One carried hazard from WP2's gate (pre-existing, now yours): the facts query in
`legacy_source.py`'s sqlite arm hardcodes its six base columns, so a store missing one
raises `sqlite3.OperationalError` outside the migrate family. When your sidecar surface
wraps the pipeline, catch storage-level errors at the run_migration boundary into a typed
migrate-family refusal (content-vs-storage discipline: bytes-never-arrived vs
bytes-uninterpretable — do NOT widen row grammar; this is a storage-side refusal).

## Scope fence

You MAY edit ONLY `libs/migrate/**` and, if a real import demands it, GROW the Rule-4
`migrate` row in `tests/architecture/test_rule_04_lib_dependency_dag.py` to include the
actual new deps (expected: none beyond `{engine, lang}` — `BackendRegistry` and the seam
are engine; justify any growth in your report). NOTHING else. Never touch `.loops/`,
`~/.config/loops`, other worktrees, or run `sl`/`loops` emit. Quarantine ratchet stays
green. STOP and report anything needing an out-of-fence change — especially any gap in the
registry/seam surface (e.g. if the registry cannot open a not-yet-existing staging
descriptor, that contradicts slice 3's lazy-reader claim — report, do not work around).

## Deliverables

1. `src/migrate/sidecar.py`: the orchestrator. Public entry:
   `run_migration(source_path, vertex_path, *, store_dir, signer, transform_rule) ->
   MigrationOutcome` (frozen dataclass: target path, lineage, head, report path,
   exceptions summary). Stages: inventory (refusals fire here, before any target) →
   transform (drafts + genesis requirements) → journal pre-flight → mint through registry
   → append loop → verify Full + equivalence re-run → write + sign migration report →
   publish preconditions → atomic descriptor publish. Restart detection: if a staging
   target for this (source, vertex) exists per the descriptor... it does NOT — a fresh run
   ALWAYS mints fresh (ruling 3); resume happens only when the caller passes the explicit
   staging target (`resume_target=` parameter) — resuming is a deliberate act, never an
   inference.
2. Refusal types for the sink stages in the migrate family (target-mismatch-on-resume,
   torn-tail, publish-precondition failures incl. source-changed, journal-preflight
   failure) — each a location claim, remedies as advisory prose only.
3. The migration report writer + signer + a verifier function (given report path + public
   key → verifies signature and re-checks the target head claim against the live target).
4. The `.vertex` surgical editor with verification-by-re-parse.
5. Tests — against REAL stores, no mocks of engine surfaces (`libs/migrate/tests/`):
   - (1) full round-trip on synthetic legacy stores (both arms): inventory equality per
     §I.3, signature preservation, target verifies Full, journal first entry is
     bootstrap/MINT, descriptor updated atomically, report verifies;
   - (2) kill-mid-append restart: append N/2 drafts, abandon, re-run with `resume_target=`
     → final target BYTE-IDENTICAL to an uninterrupted run (the §I.4 gate);
   - (3) resume against a tampered target (flip one byte in an appended record) → typed
     refusal, target bytes unchanged after (F2 gate, no repair);
   - (4) torn tail (truncate mid-record) → typed refusal, bytes unchanged;
   - (5) second migration after an abandoned attempt → fresh lineage, fresh path, no
     StoreLost;
   - (6) source mutated during staging (append a line after snapshot) → publish refused,
     descriptor unchanged;
   - (7) publish atomicity: after a successful run, the pre-edit `.vertex` parse equals
     the post-edit parse in every field except the store clause;
   - (8) the refused-inventory case creates NO target path (WP1's gate assertion,
     re-checked at the sidecar surface).

## Acceptance bar

COMMIT FIRST, then break/restore proofs (paste red, restore, paste green, paste empty
production diff after each):

1. Make the resume path "repair" a mismatched record (overwrite instead of refuse) → test
   (3) fails.
2. Skip the journal pre-flight and mint anyway → the pre-flight test fails (probe the
   heads/ dir absent case).
3. Break publish atomicity (plain write_text instead of temp+replace) → test (7)'s crash
   simulation fails (kill between write and replace must leave the old descriptor intact —
   simulate by asserting the temp-file protocol, or fault-inject the replace).
4. Drop one precondition check (source-hash re-check) → test (6) fails.
5. Byte-identity: introduce a timestamp into the report-independent append path → test (2)
   fails.

Final checks, paste output: `uv run pytest libs/migrate tests/architecture -q` all green;
`git status --short` clean but `.tmp/`; quarantine grep empty; no import of
`ArrivalLog` for WRITING in sidecar.py (reads via registry Query only — grep and show).

## Report format (stdout, one shot)

1. What changed, file by file. 2. Evidence per proof. 3. Any STOP items (registry/seam
gaps especially). 4. Rule-4 row justification if grown. 5. Found-but-left-alone.
6. Honest unverified list.
