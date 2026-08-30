# Slice 4 WP2 — the Transformer

## Working directory — verify FIRST

Your workspace is the git worktree at:

    /Users/kaygee/Code/loops-wt/s4-wp2

Every command MUST be prefixed `cd /Users/kaygee/Code/loops-wt/s4-wp2 && `. First action:

    cd /Users/kaygee/Code/loops-wt/s4-wp2 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp2` based on main AFTER the WP1 merge (`git merge-base HEAD main`
must equal your HEAD's parent lineage — if `libs/migrate` is absent from your tree, STOP and
report; you are on a stale base). Test env: `TMPDIR=<worktree>/.tmp`, pytest
`--basetemp=<worktree>/.tmp/pt`.

## EXECUTE YOURSELF — DO NOT DELEGATE

There is no one to hand this to; if you delegate or stop to ask, the work does not happen.

## Contract (ratified — deviations are reportable, not decidable)

You implement WP2 of `design:arrival-break-slice4-migration-sidecar` — the Transformer:
legacy rows → an ordered, deterministic sequence of arrival record drafts. Read FIRST:
`docs/scratch/arrival-break/slice4-design-proposal.md` §0.2, §A, §G, §I.2, §J.1 (WP2), §J.2,
and M-4's ruling in the design fact. Binding rulings:

1. **Map every in-scope row exactly once, in ruled source order** (jsonl: line order;
   sqlite: the frozen reader's order — facts then ticks, documented as such).
2. **Group grammar**: one legal single-observer legacy batch line → ONE arrival batch
   record; one flat row → one fact record. The transformer NEVER regroups (backend-contract
   §04 binds it — ratified L.3). Mixed-observer/absent-observer/codec-invalid lines cannot
   reach the transformer (WP1's inventory refuses first); the transformer still REFUSES —
   not asserts — if handed one (defense at the seam, same typed family).
3. **Inner signatures byte-for-byte**: the authored fact signature rides in the row
   verbatim, never re-serialized, never re-signed. Unsigned rows stay honestly unsigned.
4. **Migrated fact/batch/tick records are OUTER-UNSIGNED** (§0.2): envelope observer = the
   author echo per `decision:design/arrival-wire-v1-pin`; no envelope signature. Put the
   rationale in the transformer module docstring: the sidecar can only sign as the
   custodian; unsigned ordinary records are legal and the authority walk skips them
   (`arrival.py:2044-2045`); the key introductions establish the registry for FUTURE
   writes — they do NOT validate migrated content. A reader who assumes otherwise has the
   security model backwards; say so.
5. **M-4 (ratified): legacy ticks become NATIVE arrival `tick` records**, NOT `tick.<name>`
   facts (rebirth's shape dissolves). The tick's signed envelope must be carried
   byte-for-byte so its original signature still verifies (the frozen reader hands you the
   stored envelope; do not re-derive or re-key it). Tick envelope observer follows the
   wire-v1 pin: custody-producer label = destination log's genesis observer.
6. **Genesis + key introductions from the `.vertex` observers block** (§G): the migration
   custodian is the vertex's self-observer (the only private key the sidecar holds — state
   it in output metadata, per §G.1). Draft order is FORCED: key introductions (one per
   declared observer carrying a key, each signed by the custodian per the authority clause
   `arrival.py:1962-1970`) precede all migrated records. The genesis itself is minted by
   WP3's `mint()` through the seam — the transformer produces everything AFTER ordinal 0,
   and its output declares what the genesis must carry (custodian public key). Follow
   engine's existing signed-record grammar for how a key introduction is constructed and
   signed — do not invent a signing path; if engine's grammar does not expose what you
   need, STOP on that item and report the gap (it is a seam finding, not yours to bridge).
7. **§G.3's two exception edges owe records, not refusals**: a declared observer with
   `key=None` → skipped, named in the transform's exception report; an observer appearing
   in rows but absent from the observers block → rows admitted (admit ≠ believe), no
   introduction, named exception. Neither is a verdict about the store — location claims
   about what the declaration covers.
8. **Determinism**: same source + same declaration + same transform rule → byte-identical
   draft sequence. This is what WP3's verification-by-re-run and restart derivation lean
   on. `legacy_ids.ulid_migration()` supplies id mapping; its determinism is already pinned.

## Scope fence

You MAY edit ONLY: `libs/migrate/**`, and the `migrate` row in
`tests/architecture/test_rule_04_lib_dependency_dag.py` — GROW it to exactly the set of
libs `libs/migrate/src` actually imports after your work (expected: `engine`, `lang`;
`store` only if a real import forces it — comment why). NOTHING else. No engine/store/lang
edits, no reformatting in passing, never touch `.loops/` or anything outside the worktree,
never run `sl`/`loops` emit. The quarantine ratchet (`test_quarantine.py`) must stay green —
the forbidden legacy modules stay forbidden; frozen knowledge lives in migrate already.
If something outside the fence must change, STOP and report.

## Pre-work — three ruled cleanups from the WP1 gate (do these FIRST, own commit each)

P1. **Collapse the inventory refusal type lattice to ONE concrete type** (arbiter ruling):
today mixed-alone raises `MixedObserverBatchRefused` while mixed-plus-codec-invalid raises
the root — a subclass whose selection depends on unrelated file content is a dispatch trap.
Keep `MigrationRefused` as the family ROOT (WP3 adds sink/publish refusals under it); the
inventory refusal becomes one concrete subclass carrying the three enumerated classes
(codec-invalid / mixed / absent) as structured data. Update tests; no caller dispatches on
the dead subclasses.

P2. **Sweep the compat shims** in `refusals.py`: constructors currently accept old and new
tuple shapes with len-based normalisation and a positional compat parameter — a package
days old with no external callers. One constructor, one tuple shape.

P3. **Parameterise, don't duplicate, the frozen grammar**: `inventory.py`'s hand-rolled
batch-row validator (~:306-385) re-implements `row_object_fault` so it can validate with
observer excluded (the absent class needs that). Give the frozen `row_object_fault` an
explicit parameter (e.g. `required_fields=` override or `skip_fields=`) — cited as a
deliberate, minimal seam in its docstring — and delete the second implementation. Two
implementations of one grammar drift (that is exactly how WP1's B3 happened).

## Deliverables

1. `src/migrate/transform.py`: the Transformer. Input: the frozen readers' row streams +
   the parsed `.vertex` declaration (via `lang`) + a `Transform` rule (`legacy_ids`).
   Output: a deterministic, ordered iterable of arrival record drafts (key introductions,
   then migrated fact/batch/tick records) plus a structured exception report (§G.3 edges)
   and the genesis requirements (custodian identity + public key). Use engine's draft/body
   types (`RecordDraft` and the `arrival_body` constructors) — the drafts must be exactly
   what the contract `append` path accepts in WP3, no privileged shapes.
2. Group grammar implementation with the seam defense (ruling 2).
3. M-4 native-tick conversion with envelope byte-preservation.
4. Key-introduction construction per engine's grammar (ruling 6).
5. Tests (`libs/migrate/tests/`), extending the WP1 fixture builder:
   - signature byte-comparison over a fixture with signed AND unsigned rows (assert the
     draft carries the exact stored signature bytes / honest absence);
   - key-introduction ordering + validity asserted against `verify_authorship` semantics
     (construct the would-be log order and check the authority clause holds: custodian
     valid at 1..k, introduced observers valid only after their introduction);
   - both §G.3 exception edges (keyless declared observer; undeclared observer in rows)
     land in the exception report and do NOT refuse;
   - grouping: a 2-row single-observer batch line → one batch record with seq 0..1; the
     same rows flat → two fact records (and the two outputs are NOT identical — the
     grouping is semantic, per §04);
   - native tick: a signed legacy tick converts to a `tick` record whose envelope bytes
     round-trip verbatim;
   - determinism: full transform run twice → byte-identical sequences; and with
     `ulid_migration`, old→new id mapping is reproducible without a stored map;
   - seam defense: handing the transformer a mixed-observer batch raises the typed refusal
     (not an assert, not ArrivalBodyError passthrough).

## Acceptance bar

COMMIT FIRST, then break/restore proofs (paste failing output, restore, paste green, paste
empty production diff after each):

1. Byte-preservation: make the transformer re-serialize payload text → the signature
   byte-comparison test fails.
2. Grouping: make the transformer split a batch into per-row fact records → the grouping
   test fails.
3. Ordering: emit a migrated record before the key introductions → the authority-ordering
   test fails.
4. Determinism: introduce a `set()` iteration or timestamp into the draft path → the
   determinism test fails.
5. M-4: convert ticks to `tick.<name>` facts (the old rebirth shape) → the native-tick test
   fails.

Final checks, paste output: `uv run pytest libs/migrate tests/architecture -q` all green;
`git status --short` clean but `.tmp/`; quarantine grep
`grep -rn "engine.jsonl\|store.rebirth\|store._conn" libs/migrate/src/` empty.

## Report format (stdout, one shot)

1. What changed, file by file. 2. Pasted evidence per proof. 3. The Rule-4 row you landed
and every real import justifying it. 4. Deviations (reported, never silently decided) —
especially any gap in engine's grammar you stopped on. 5. Found-but-left-alone. 6. What you
did not verify, honestly.
