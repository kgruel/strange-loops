# Arrival substrate — WHOLE-BRANCH adversarial review, round 1

You are the cross-family reviewer for the `feat/arrival-libs` branch of the
strange-loops monorepo. You have workspace-write: run the suites, execute
probes, read anything. Your value is precisely that you are a different model
family from the authors (Claude Opus/Fable, Gemini flash/pro) — hunt in their
shared blind spots. Prior rounds receipted your finds landing exactly there:
duck-typing assumptions, declaration-vs-availability confusion, float
semantics.

## 1. Anchor

- Repo: this checkout (`/Users/kaygee/Code/loops`), branch `feat/arrival-libs`.
- Diff spec: `git diff 406cec31...HEAD` — 135 commits, 168 files,
  +39182/−1305.
- The branch is three converged cuts plus a two-commit tail:
  - **Cut A** — arrival substrate core (ArrivalLog, ArrivalStore, projection,
    custody). Receipts: `docs/scratch/arrival-sliceA/`.
  - **Cut B** — projections + derived-log git merge driver + custody guard.
    Receipts: `docs/scratch/arrival-sliceB/`.
  - **Cut C** — declared Ordering end-to-end (atoms `Arrival()|ByKey`,
    `StoreReader.ordered`, CAS token → arrival head, jsonl bridge
    dissolution). Receipts: `docs/scratch/arrival-sliceC/`.

## 2. Design contract (the target to attack)

The canonical short list is `decision:design/arrival-substrate-laws` — THE
FIVE:

1. **The store IS the arrival log.** Projections compute answers; arrival
   determines what they are about. If a projection disagrees with arrival,
   the projection is wrong, never the reverse.
2. **Ordering over an arrival basis is witness order or a declared
   (thing, id) order.** id totalizes, tie-break only, never a clock; the
   substrate never learns what `ts` means.
3. **Drivers propose candidates; only the custodian admits records and mints
   witness positions.** Two things minting positions is the one forbidden
   shape.
4. **Witness positions compare only within one arrival lineage.**
   Cross-lineage comparison is UNDEFINED and must fail structurally
   (`WitnessAggregateUnsupported`).
5. **Projection maintenance is derived from ordering semantics + reduction
   algebra** — not an independent store mode.

Admission boundary: malformed / bad signature / id-collision-different-bytes
/ unauthorized-source → reject; otherwise admit. ADMIT ≠ BELIEVE.

Cut-specific NON-NEGOTIABLES (full bodies in
`docs/scratch/arrival-sliceB/design-proposal.md` and
`docs/scratch/arrival-sliceC/design-proposal.md`):

- Ordering is DECLARED, never inferred. One totalization: sort key `(K, id)`,
  id ascending, tie-break only. Missing-K = non-membership. Mixed-type K
  refuses (strict type identity incl. bool≠int).
- `'arrival'` ordering is single-store-only; aggregates take ByKey (default
  ts); aggregate+Arrival refuses.
- CAS token = arrival head `(record_ordinal, fact_id)`; batch rows share an
  ordinal, id breaks the tie. `_INTENT_VERSION=2`; pre-bump intents refuse.
- `store/jsonl.py` bridge module wholly dissolved, residue swept.
- ts lens vector family byte-identical to the pre-cut frozen goldens.
- Legacy sqlite-canonical families byte-for-byte untouched except two
  licensed refusal rewords; `Spec.replay_from`, checkpoint machinery
  (`handle.py`), and `benchmarks/characterize.py`'s pre-existing probes are
  KEEP fences.
- Custody guard (invariant 15): creating a store where an `.arrival` log
  holds custody refuses before any file exists.

## 3. Prior coverage — where NOT to spend your budget vs where to hunt

Each cut converged individually: per-slice opus gates, gemini flash+pro
rounds, and a cut-C sol belt-and-braces r1–r3 (converged at `5637f260`,
ledger fully dispositioned — briefs in `docs/scratch/arrival-sliceC/`).
Re-litigating already-dispositioned findings is low value unless you have NEW
evidence. The zones no round has structurally seen:

1. **Cross-cut seams.** Every prior review was cut-scoped. Cut C code calling
   cut A/B surfaces (e.g. `ordered()` over stores minted by cut A paths, CAS
   head vs cut B's merge driver rewriting derived logs, custody guard vs
   arrival index rebuild) has never been reviewed as one diff.
2. **Post-convergence commits, reviewed by NOBODY:**
   - `63184a09` — the custody guard moved inside `store._conn._create`;
     slice/rebirth dropped their call-site guards; receive kept its
     (copies a foreign db, never calls `_create`). Verify: is every create
     arm still covered? Is the guard ordering vs the `FileExistsError` check
     right when a `.db` legitimately exists as a derived index? Any path
     that writes a store file without passing `_create` or receive's guard?
   - `61c00586` — benchmark probes (`benchmarks/characterize.py` arrival
     section), recorded arm, LEDGER.md claims. Verify the probes measure
     what they claim (fixture counts asserted? does `declaration_head()`
     actually walk at depth, or hit a cache?), and that LEDGER.md's numbers
     match the arm JSON.
3. **Whole-branch invariant sweeps** cheap for you, expensive for cut-scoped
   review: any remaining ordering inference (sorting by ts/id outside the
   declared surfaces), any second custodian (writes to `.arrival` outside
   ArrivalLog), any cross-lineage witness comparison, any resurrection of
   dissolved `store/jsonl.py` vocabulary or imports.

## 4. Empirical standard

Findings need evidence: a failing test you wrote, a reproduced behavior, or
exact file:line reasoning that survives reading the surrounding contract.
Suites (all green at HEAD; run what you need):

- `uv run pytest libs/atoms/tests libs/engine/tests libs/sdk/tests libs/store/tests -q`
- `uv run pytest tests -q` (arch rules — run ALONE; combining with
  libs/engine/tests produces known cross-corpus interference, not real
  failures)
- `uv run pytest apps/loops/tests -q`

## 5. Verdict format

1. **Findings table**: ID (CX-BR-NN), severity (MAJOR/MINOR/NOTE), file:line,
   claim, evidence. Location claims, not verdict claims — say where the
   contract is broken and how you know, not "this is fine".
2. **Per-commit verdicts** for `63184a09` and `61c00586`: PASS/FAIL with
   evidence.
3. **Overall call**: CONVERGED / NOT CONVERGED for ship, with the one
   sentence you'd put in front of the arbiter.

Zero findings is an acceptable answer if you actually hunted — say where you
looked and what you tried.
