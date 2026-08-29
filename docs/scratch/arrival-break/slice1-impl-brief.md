# Slice 1 impl brief — wire v1 pin (seam triage execution)

Pipeline: impl-pipeline. Arc: `design:arrival-break-implementation`. This brief is the
implementation contract for slice 1. Deviations from it MUST be reported (emit a `finding`
fact + state it in the report) — deviation from a written contract is reportable; silent
deviation is the failure mode the pipeline exists to catch.

## Contract

Binding facts (read them: `sl read project --facts --kind decision --plain | grep wire-v1`):

- `decision:design/arrival-wire-v1-seam-triage` — parent triage (2026-08-26): **body.t
  DROPS** (pure vestige; outer `k` discriminates), **tick observer RE-SPELLED**, **dual
  signature KEEPS** (principled two-subject pair, untouched).
- Same topic, sub-ruling @ `01M172M74FZ9E27V34QKDF7Y77` (2026-08-29, closes the open
  spelling): the five rulings below.
- Panel evidence: `docs/scratch/arrival-break/slice1-panel-synthesis.md` (commit 7984a5de).

The five rulings, binding:

1. **Candidate A** — envelope `observer` for TICKS becomes a custody-producer label.
   Facts/batches/genesis/key envelope observers UNCHANGED. The field remains
   signer-selection plumbing for signed kinds — do not touch `fact_signer_for` /
   `_resolve` key-selection behavior.
2. **The label = the destination log's genesis observer** (`self._log.genesis()['observer']`).
   BOTH mint sites in one change: `libs/engine/src/engine/arrival_store.py:462` (shared
   fact/tick ternary) AND `libs/store/src/store/merge.py:749-755` (`_entry_for` — second,
   independently-encoded mint site; needs a destination-log genesis read it does not do
   today). Prose stating the ruled-out semantics rewrites in the same change:
   `arrival_store.py:25-27`, `merge.py:694-702`.
3. **Tick outer signatures DEFERRED explicitly** — wire v1 pins with ticks outer-unsigned
   ON PURPOSE. Do not add tick signing. The label is a true-but-unverified claim; docs may
   say so.
4. **Batch same-observer grammar ENFORCED**: "all rows in a batch share one observer"
   becomes a wire-grammar refusal at the arrival seam. Construction over detection.
5. **Outer-sig law: wire-format's half.** Outer signature = per-lineage arrival-content
   signature; the inner fact-domain signature is what travels through re-custody.
   `protocol.html` §06 is false as written and rewrites in this slice's doc pass.

**NON-NEGOTIABLE**: no preserved inner signature may be invalidated. Inner fact
commitments never covered `t` or the envelope observer (`fact_commitment_hash` =
kind, ts, observer, origin, payload). If any existing signed fixture stops verifying,
stop and report — that is a contract breach, not a fixture to regenerate.

## Scope — four changes + docs

1. **Drop `body.t` from arrival bodies.** Fork the arrival body encoding from the legacy
   line codec. Today `jsonl_codec.py:160` (`_encode_obj`) writes `t` and `:430`
   (`records_from_object`) dispatches on it; the arrival write site is
   `arrival_store.py:458`, read-back `arrival_projection.py:168`. Arrival bodies stop
   carrying `t`; arrival decode dispatches on envelope `k` (the projection site holds `k`
   when it hands body over). **The legacy codec KEEPS `t`** — slice 4's LegacySource needs
   it. Design point (yours, with rationale in the report): whether arrival decode/grammar
   REFUSES a body that still carries `t` — the full break has no compat mode, and zero
   `.arrival` stores exist, which argues for refusal-by-grammar; decide and justify.
2. **Tick observer re-spell** per rulings 2 (both mint sites, prose sites). Known test
   blast: `libs/engine/tests/test_arrival_store.py:157-171` (asserts tick envelope
   observer == the tick's name), `libs/store/tests/test_arrival_merge.py:74-82` (fixture
   hardcodes `observer=body['name']`). Update to ruled semantics AND add the missing
   assertion: merged-tick envelope observer (no test pins the merge path today — that gap
   is how a single-site fix would go green and wrong).
3. **Batch same-observer refusal.** Placement is your design point: `_validate`
   (`arrival.py:343-405`) is deliberately kind-agnostic — kind-specific rules live in
   `_placement_fault`; put the batch-row rule where the batch grammar lives, justify in
   the report. A constructed multi-observer batch must be refused with a typed error.
4. **Doc pass** (docs/architecture/arrival/): `wire-format.html` — envelope/body profile
   tables lose `body.t`, the ruled-seams callout (:240-254) rewrites to the ruled
   spellings, status flips from draft-with-open-seams to pinned wire v1; `protocol.html`
   §06 rewrites per ruling 5 (outer sig = per-lineage; inner travels). Match the suite's
   existing inline-fact-ref conventions. Check `index.html`/`backend-contract.html` for
   `body.t` or tick-observer mentions.
5. **Fixtures/vectors.** Observer change: zero conformance-vector blast (verified null
   set); regen surface is the Python fixtures above. `body.t` drop: the panel did NOT
   assess its vector blast — check `spec/conformance/vectors/` generators yourself and
   regenerate whatever actually embeds arrival-encoded bodies. Report what you found
   either way.

## Non-goals (do not touch)

- Fact/batch/genesis/key envelope observer semantics (candidate C was explicitly not ruled).
- Tick outer signatures (deferred), `content_commitment` shape, dual-signature machinery.
- `arrival_ordinal`/`arrival_seq` names. `FileStore`/`file_writer.py`. Legacy codec's `t`.
- No backend-contract/registry work — that is slice 2.

## Mechanics

- **Worktree**: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-slice1 -b slice/arrival-wire-v1 main`.
  Step 0 in the worktree: verify base — `git merge-base HEAD main` must include commit
  7984a5de; if behind, reset onto current main before touching anything.
- **Env**: uv workspace. Run suites from the worktree root. Verify which binary you
  exercise (`command -v` inside the env) before trusting green. Record exact test counts;
  reconcile any count that differs from a clean-base run instead of waving it through.
- **Suites to run**: all arrival test files (engine + store packages), plus the engine and
  store package suites, plus `spec/` conformance if touched. Architecture tests
  (`tests/architecture/`) from the repo root env.
- **Commits**: conventional style, logical units, on `slice/arrival-wire-v1`. End messages
  with: `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`.
  NEVER stage `.loops/` or any store file. Verify committed artifacts with `git ls-files`
  (the root gitignore eats `*.jsonl`/`*.log` silently).
- **Loops emissions** (attributed, arbiter-custody signing): from the MAIN checkout cwd
  (`cd /Users/kaygee/Code/loops`), `sl emit project ...`. Emit at moments only:
  slice progress (`task name=arrival-break-slice1-wire-v1 status=in-progress ...`),
  deviation-from-contract (MUST, as `finding`), findings worth a disposition. Every
  emission carries `agent=slice1-impl slice=1 role=implementer`. Facts only — never seal,
  never mint ticks.
- **Report**: write `docs/scratch/arrival-break/slice1-impl-report.md` AS YOU GO (commit it
  on the branch): scope delta, design points with rationale (body.t refusal, grammar-rule
  placement, genesis-read plumbing in merge), test-count table (before/after, per suite),
  mutation-verification evidence (below), fixture/vector assessment, deviations. Then
  ALSO send the final summary via SendMessage — final text can be lost; the file is the
  record.

## Oracle (the gate re-runs all of this from scratch — make it pass honestly)

1. All arrival + engine + store suites green in a fresh env; counts reconciled.
2. Inner-signature preservation: existing signed fixtures verify unchanged.
3. Byte-stable round-trip: encode→decode→encode identity on t-less arrival records.
4. Mutation evidence (demonstrate each; the gate re-runs them):
   - batch same-observer check reverted → the new refusal test FAILS;
   - merge-site observer change reverted → the merged-tick observer test FAILS;
   - store-site observer change reverted → the tick observer test FAILS.
5. `git ls-files` shows every fixture/receipt/doc actually committed.
6. Docs: no `body.t` mention survives outside legacy-codec/sidecar context; protocol §06
   states the ruled law; wire-format status flipped.
