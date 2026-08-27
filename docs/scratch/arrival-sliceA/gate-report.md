# Cut A (AUTHORITY) — independent gate report

Gate agent: sliceA-gate. Date: 2026-08-18.
Target: `slice/arrival-authority` @ `850e679d` (7 commits off `feat/arrival-libs` @ `3b303d5d`).
Pointer branch: `slice/arrival-authority-gate` @ `850e679d`.
Contract: `decision:design/arrival-sliceA-authority` @ `01M0B0Z14T9ATPRAJTKBBMCQQT` + the ratified design doc (read from the main checkout). The implementation report (`docs/scratch/arrival-sliceA/impl-report.md`) was treated as the review's target, never its authority — every gate claim below was re-established by this gate's own execution.

## VERDICT: **CLEAN — PASS on every gate item.**

No blocking findings. Six non-blocking, arbiter-informational findings (report-accuracy and residue items) at the end.

Environment: this gate's own isolated worktree at `850e679d`, fresh uv venv
(`uv sync --all-packages --all-groups`), liveness verified before any count
was trusted — `engine.__file__` resolves into the gate worktree, `mint(key=)`
and `verify_authorship` present on the live module. Baseline runs executed in
a second, detached scratch worktree at `3b303d5d` with its own fresh venv,
liveness verified the same way.

---

## G1 — the authority test, answered literally: **PASS**

Ran the implementer's gate suite AND an independent oracle script written
from scratch (`docs/scratch/arrival-sliceA/gate_g1_g2.py`, committed beside
this report; run with `uv run python docs/scratch/arrival-sliceA/gate_g1_g2.py`).
The oracle's scenario is deliberately different from the implementer's test:

```
ord 0 genesis (kaygee, K1)          ord 5 declaration absorb (movement 2)
ord 1 fact kaygee                   ord 6 key introduction kaygee/K2
ord 2 key introduction beto/B1      ord 7 fact kaygee signed with K2
ord 3 fact beto                     ord 8 seal tick
ord 4 fact kaygee
```

All built through the shipped ceremonies (`ArrivalLog.mint`,
`ArrivalStore.append`/`append_tick`, `absorb_genesis`, `log.append` for the
introductions). A decoy `.jsonl` was planted, then EVERY projection deleted
(`.db`, `-wal`, `-shm`, `.jsonl`); the directory was asserted to hold the
`.arrival` alone. Every answer was then produced by a **fresh subprocess
chdir'd into an empty directory** receiving only the `.arrival` path:

- **identity**: every record in one lineage; the `_decl.genesis` fact's row
  id equals `ArrivalLog.lineage()` — `own_lineage` re-derives with
  `store_meta` gone; the absorbed payload is `{protocol, documents}` only
  (both era pins shed, asserted).
- **records**: kinds `[genesis, fact, key, fact, fact, fact, key, fact, tick]`,
  verbatim payload messages recovered.
- **ordering**: dense ordinals 0..8 via `walk()` (the walk is the integrity
  statement).
- **authorship**: `verify_authorship` verifies every signature.

Output: `G1G2-ANSWER-OK ... GATE-G1-G2-OK`. The implementer's
`test_arrival_authority_gate.py` also passes (4 tests). No answer needed a
projection.

## G2 — the exclusivity trace: **PASS**

*The trace (own execution, projections deleted):*

```
ord= 0 observer=kaygee  key=bBbccakpMrPMzHWE... <- (lineage, 0)
ord= 1 observer=kaygee  key=bBbccakpMrPMzHWE... <- (lineage, 0)
ord= 2 observer=kaygee  key=bBbccakpMrPMzHWE... <- (lineage, 0)
ord= 3 observer=beto    key=WrBpDZhhIwO1nv3L... <- (lineage, 2)
ord= 4 observer=kaygee  key=bBbccakpMrPMzHWE... <- (lineage, 0)
ord= 5 observer=kaygee  key=bBbccakpMrPMzHWE... <- (lineage, 0)
ord= 6 observer=kaygee  key=bBbccakpMrPMzHWE... <- (lineage, 0)
ord= 7 observer=kaygee  key=EKSULIUswUEGvKtw... <- (lineage, 6)
```

Every verifying key resolves from a `(lineage, ordinal)` coordinate in THIS
log; the oracle asserts the keys are physically present in the records at
those coordinates (`log.read(0)`, `log.read(2)`, `log.read(6)`). Second key
at a stated ordinal: two of them — B1 at 2, and a rotation key K2 for the
SAME observer at 6, exercising multi-candidate resolution (the ord-7 fact
verifies under K2, introduced_ordinal=6, not K1).

*The negative:* `grep -rn "observers\|\.vertex" arrival.py arrival_store.py`
— one docstring mention, zero code reads; neither module imports anything
that touches the `.vertex`. The apps-composed tick-chain verifier surface:
`git diff main 850e679d -- libs/engine/src/engine/sqlite_store.py` shows
exactly two hunks (`@@ -791,6 +791,40 @@`, `@@ -876,20 +910,11 @@` — the
absorb-genesis seam); the verifier/observers-anchor region (~:1556-1773) is
**byte-identical vs main**, and apps/ is diff-empty (G3).

*Adversarial probes (own cases, all refused as required):*

- ADV-A: record by an observer BEFORE its key's introduction → refused at
  ordinal 1 (`introduced at < N` clause, `<= N` side).
- ADV-B: introduction signed by the not-yet-valid key itself (self-cert at
  its own ordinal N) → refused at ordinal 1.
- ADV-C: genesis whose signature does not verify against its own
  `body["key"]` (mint key=A, signer=K) → refused at ordinal 0.
- ADV-D: one observer's record signed with another observer's introduced key
  → refused (observer binding).

## G3 — apps/ diff-empty: **PASS**

```
git diff --stat main...850e679d -- apps/              → 0 lines
git diff --stat feat/arrival-libs...850e679d -- apps/ → 0 lines
```
(Two-dot forms also 0.)

## S3 — legacy byte-identical: **PASS**

Read every hunk in the touched shared modules:

- `sqlite_store.py`: absorb-genesis refactored onto two seam methods
  (`_genesis_payload`, `_genesis_lineage_id`); `conn = self._conn` in the
  ceremony, so `_genesis_payload`'s reads run on the same connection inside
  the same `BEGIN IMMEDIATE`; legacy payload dict is field-for-field and
  order-identical (`protocol, documents, chain_head, fact_cursor`), id still
  `gen_id()`.
- `jsonl_store.py`: `open_canonical_store`/`ensure_index` grow the arrival
  arm; the jsonl and sqlite arms are decision-equivalent to the old
  `is_jsonl_canonical` branches (`canonical_mode(x)=="jsonl"` iff the old
  boolean was True for every pre-existing input); `JsonlStore.__init__`
  inverse `log_path_for` → `canonical_for(path, "jsonl")` — same pure
  function. One drive-by SIM105 rewrite (`try/except FileNotFoundError: pass`
  → `contextlib.suppress`) — behavior-identical.
- `preflight.py`: `.arrival` dispatches to a new scoped `_arrival_preflight`
  (whose `agreed` stays None — no innocence claim); jsonl/sqlite paths
  unchanged.
- `compiler.py`: `canonical_mode(...) != "sqlite" or suffix in
  SQLITE_SUFFIXES` — truth-table-identical to the old condition for legacy
  inputs; EventStore fallthrough preserved.
- `ceremony.py`: one comment line. `witness.py`: docstring sense note only.

Every ceremony change is fenced on the `.arrival` locator (mode dispatch);
suites: full engine 1678 green including `test_jsonl_ceremonies.py` and
`test_jsonl_store.py` (both changed only by the mechanical
`log_path_for`→`canonical_for(_, "jsonl")` rename — assertions untouched).
Golden fixtures byte-identical (only `generate_golden.py` carries the same
rename).

## Suite reconciliation: **PASS — all five counts reproduced exactly**

| suite | this gate @ 850e679d | baseline @ 3b303d5d (detached worktree) | report |
| --- | --- | --- | --- |
| libs/engine/tests | **1678 passed, 1 skipped** | 1621 passed, 1 skipped | 1678/1621 ✓ |
| tests/ (arch, no chaos) | **98 passed** | 98 passed | 98 ✓ |
| libs/sdk/tests | **313 passed** | — | 313 ✓ |
| libs/store/tests | **131 passed** | — | 131 ✓ |
| apps/loops/tests | **2525 passed, 1 xfailed** | — | 2525 ✓ |

## Mutation verification re-runs: **PASS — every required red shown**

Each mutant applied by this gate, run, and reverted (tree clean after —
`git status --short` empty, `grep -rn "GATE MUTANT" libs/` empty):

- **(a-i) race fix, gap guard**: `_write`'s
  `if consumed is None or record["ord"] != consumed.arrival_ordinal + 1` →
  `if False` — RED:
  `test_a_record_landing_between_reconcile_and_append_is_never_skipped`
  (1 failed, 17 passed).
- **(a-ii) race fix, ceremony CAS**: `_ceremony_persist`'s `following=` →
  `None` — RED: `test_a_ceremony_racing_an_interloper_refuses_before_any_byte`.
- **(b-1) verifier, single mutant**: `introduced < ordinal` filter removed —
  **GREEN** (15/15, and this gate's own adversarial probes also stay green).
  This CONFIRMS the impl report's equivalent-mutant analysis: the
  registration-after-resolution guard alone still refuses self-certification.
- **(b-2) verifier, both guards**: b-1 plus registration moved before
  resolution — RED: `test_self_certification_is_refused_above_ordinal_zero`.
- **(b-3) genesis self-cert skipped**: `if not verify(...)` → `if False` —
  RED: `test_a_genesis_signed_by_a_key_other_than_its_own_is_refused` +
  `test_mint_key_and_signer_disagreeing_is_caught_by_the_verifier`.
- **(c) half-migrated tie-break**: both probe sibling checks conditioned so
  the legacy log wins the tie — RED: 3 failures in
  `test_probe_arrival_matrix.py` including both half-migrated pins and
  `test_exactly_one_custody_holder_across_the_whole_matrix`. (The impl
  report's "4 failures" presumably counted a broader run; consistent subset,
  not a mismatch.)
- **(Rule 18 growth)**: `JSONL_OFFSET_PROBE = 1` appended to `residence.py`
  — RED: `test_the_arrival_surface_never_names_the_denied_vocabulary`.

## Tracked-ness: **PASS**

`git ls-tree -r 850e679d --name-only` confirms: `impl-report.md`,
`arrival_store.py`, `test_arrival_authority.py`,
`test_arrival_authority_gate.py`, `test_arrival_store.py`,
`test_probe_arrival_matrix.py` all tracked on the branch. No claimed fixture
was eaten by the `*.jsonl` / `docs/dev/` gitignores (the slice ships no
binary/jsonl fixtures; `generate_golden.py` is tracked).

## Deviation claims — facts verified (dispositions are the arbiter's)

1. **is_jsonl_canonical shim**: CONFIRMED. `apps/loops/src/loops/commands/store.py:142`
   is `from engine.residence import index_path_for, is_jsonl_canonical` —
   lazy, and it executes BEFORE the `if not is_jsonl_canonical(canonical):
   return None` mode check, so deleting the symbol ImportErrors every mode.
   The shim (`residence.py:105`, one line, behavior-identical, not in
   `__all__`), the single commented Rule 18 `_ALLOWED` entry
   (`("...residence.py", "def is_jsonl_canonical")`), and the tripwire
   `test_the_retired_boolean_survives_only_for_the_cli_lazy_import`
   (`test_residence.py:36`) all exist and cross-reference each other and the
   apps line.
2. **reanchor allowlist entry**: CONFIRMED — exactly one more entry,
   `("...arrival_store.py", "def reanchor")`, commented; `_ALLOWED` has
   exactly these two entries.
3. **_placement_fault purity vs verify_authorship-first-act**: CONFIRMED and
   empirically probed. `_placement_fault`'s ordinal-0 arm does shape checks
   (key present, decodes to 32 bytes); cryptographic self-certification is
   `verify_authorship`'s first act. No bypass: `walk()` makes no authorship
   claim, and `verify_authorship` unconditionally verifies the genesis
   against its own body key before anything else (mutant b-3 red; ADV-C red
   from a log minted with mismatched key/signer). The double-enforcement
   claim for the above-ordinal-0 clause is real (b-1 green alone, b-2 red
   together) — the redundancy is understood, not missed.
4. **arrival_store.py in _SCAN_TARGETS**: CONFIRMED (third entry at
   `test_rule_18...py:41`); denylist-clean (arch suite green with it scanned).
5. **Key-observer binding — what it enforces beyond the ruled positional
   clause**: the verifier's registry maps observer → [(key, introduced_ordinal)].
   The genesis key binds to the genesis record's observer; an introduced key
   binds to the observer its body names (not its signer). A record's
   signature is tried ONLY against keys valid for the record's OWN observer
   at its position. Beyond "introduced at < N" this adds: (i) one observer's
   record can never verify under another observer's key (ADV-D shows the
   refusal), so authorship names WHO, not just "someone in the log";
   (ii) multiple keys per observer resolve in introduction order (rotation
   exercised at ord 7 of the oracle). Purely additive restriction — nothing
   the ruled clause admits is widened.
6. **Narrower out-of-band detection docstring**: CONFIRMED — the
   `arrival_store.py` module docstring's "Detection scope, stated narrowly"
   paragraph states the mark is offset-and-ordinal parity plus anchor
   checks, and that the arrival agreement audit is a later cut's, alongside
   re-derivation. Not a narrowing of the C2 residual (see below).

## Carried constraints: **PASS**

- **C1 adoption sites validate**: resume mark → `walk_marked` →
  `_anchor_for` (five checks including `_authority_fault` at
  `arrival.py:1134`); catch-up consumes only through `walk_marked`; ceremony
  head reads → `append_marked` → `_append_under_lock` → `_tail_record`,
  which reads the genesis first (content-memoized) and holds the head to
  `_authority_fault` before adopting it; probe corroboration uses
  `open('rb')` + `decode_record` only.
- **No path/inode/mtime-keyed cache**: the only memo is the slice-0
  content-keyed genesis memo; `stat()` uses are size/offset-parity currency
  checks (`_log_size`, `_arrival_index_is_current`), not validation caches.
- **O(n) residual not narrowed**: append is O(1) (reverse tail scan +
  under-lock CAS, no whole-prefix walk); resume is O(1) anchor adoption;
  the whole-file walk appears exactly where the whole file is the question
  (`walk()`, `verify_authorship`, gate surfaces). No chain-to-genesis proof
  was added to any O(1) path.
- **Known residual crash window** (log-fsync → sqlite-COMMIT gap on an
  arrival ceremony → catch-up tails the genesis row in → AmbiguousGenesis
  dead-end until cut B's restamp verb): disclosed by the implementer, read
  and understood by this gate, NOT empirically probed — disposition is the
  arbiter's.

## Lint/type state — the arbiter's IDE complaints, classified

Authoritative config: repo-root `pyrightconfig.json` (includes libs/), pyright
1.1.411, clean full venv. Note the repo's own `./dev check` runs NO pyright at
all (pytest only; CI lints only custody+sign) — there is no configured gate
these files fail.

- **jsonl_store.py reportOptionalMemberAccess (:473-757 family)**:
  PRE-EXISTING. Baseline @ 3b303d5d has the identical 16
  reportOptionalMemberAccess diagnostics (16 = 16); line numbers shift ~2
  from the SIM105 edit. Runtime-guarded by the close-lifecycle convention
  (`_conn` nulled on close), i.e. real type-looseness but no observed
  defect; notably `ArrivalStore` adds the `_db` narrowing property so the
  NEW code does not reproduce the pattern.
- **sqlite_store.py :155 (dumps argument), :494-495 (`__self__` on
  FunctionType)**: PRE-EXISTING — present verbatim at baseline. Not touched
  by the slice (its hunks are :791-930 only).
- Totals on the two files: **111 errors at baseline, 111 at HEAD** — the
  slice introduced zero. Ruff on the eight touched shared modules:
  **78 baseline → 77 HEAD** (the SIM105 fix; none added).
- Slice-authored production modules (`arrival.py` post-edit,
  `arrival_store.py`, `residence.py`, `probe.py`): pyright 0 errors, ruff
  clean. See finding N1 for the one new test file.

---

## Non-blocking findings (arbiter-informational; none affects the verdict)

- **N1 — impl-report overclaim, pyright on new tests**: "pyright clean on
  every file authored this slice (... new tests)" is falsified for
  `libs/engine/tests/test_arrival_store.py`: 7 errors under the repo config
  (6 reportArgumentType at :149/:150/:356 — `int()` over `str | None` meta
  reads; 1 reportOptionalMemberAccess at :483 — raw `store._conn.execute`).
  Test-only; no runtime defect; possibly version/env drift on the
  implementer's side. The other three new test files and all four authored
  production modules are clean.
- **N2 — impl-report imprecision**: "the untouched `test_jsonl_ceremonies.py`
  suite" — the file WAS edited (mechanical `log_path_for` →
  `canonical_for(_, "jsonl")` at 7 sites). Assertions unchanged, so the S3
  pin survives; the wording, not the claim, is wrong.
- **N3 — doc residue**: `libs/engine/CLAUDE.md` (Level 2) still teaches
  `is_jsonl_canonical` as the residence API. The shim keeps the code sample
  importable, but this is precisely the reader-trap the shim's own comment
  warns about; one-line fix whenever docs move.
- **N4 — probe mutant count**: report says 4 failures for the tie-break
  mutant; this gate got 3 running the matrix file alone. Consistent subset
  (the fourth presumably lives in a broader run), not a discrepancy in what
  is pinned.
- **N5 — slice-0 test replacement accounting**: `test_genesis_body_is_minimal`
  removed; three ratified-body/keyless tests added
  (`test_genesis_body_is_the_ratified_three_fields`,
  `test_a_malformed_founding_key_is_refused_at_mint`,
  `test_a_keyless_genesis_is_refused`). Matches the ruling
  ("slice-0-scoped"); recorded for the count ledger.
- **N6 — residual crash window**: implementer-disclosed, read, not probed
  (see Carried constraints). Flagged so cut B inherits it deliberately.

## Reproduction

- Oracle: `uv run python docs/scratch/arrival-sliceA/gate_g1_g2.py`
  (from the repo root, any checkout of this branch with the workspace synced).
- Suites: `uv sync --all-packages --all-groups`, then
  `uv run pytest libs/engine/tests -q` etc. (fresh venv; hypothesis lives in
  per-package dependency-groups, so a bare `uv run pytest` on a fresh venv
  collects with errors — sync first).
