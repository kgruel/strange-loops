# Slice 2 / WP3 gate report — admission extraction

**GATE: PASS** — two NON-BLOCKING findings, neither of which touches behaviour.

Target: `slice2/wp3-admission` @ `e8c93295`, off wave base `0d38c969`.
Gate worktree: `~/Code/loops-s2wp3-gate` (branch `slice2/wp3-admission-gate`), fresh
`uv sync --all-packages`. A second disposable worktree at `0d38c969`
(`~/Code/loops-s2wp3-base`, removed after use) supplied every baseline arm, because the
impl deleted theirs and a baseline that cannot be re-derived is not evidence.

Contract: `slice2-wp3-brief.md` (its Oracle is this checklist), design §C + §D.3.
The impl report (`git show e8c93295:docs/scratch/arrival-break/slice2-wp3-report.md`)
was the TARGET of this review, not its authority. Every claim below was re-run.

---

## Oracle, per item

### 1. Brief oracle — PASS

**The two named suites.** `test_arrival_merge.py` + `test_admission_verification.py`:
**49 passed**.

**The "unmodified in intent" claim, checked honestly.** Both touched test diffs are
exactly what was claimed and nothing more:

- `test_arrival_merge.py` — a **one-line docstring** change inside
  `test_a_merged_tick_names_the_TARGETS_custodian`: the prose pointer
  ``store.merge._entry_for`` → ``engine.admission._draft_for``. Zero assertions, zero
  imports, zero fixture lines touched. The whole file diff is `2 +-`.
- `test_tick_chain.py` — D2's fix and only D2's fix: `+14` lines, being the same
  6-line block twice (both `_build_old_canon_store` sites), each adding
  `m.setattr(adm, "_canonical_bytes", _old_canon)` **inside the existing
  `monkeypatch.context()`** with a 5-line comment naming the reason at the site. No
  assertion changed. Verified as a whole-file diff, not by sampling hunks.

**Rule 4 green.** Architecture suite passes, and structurally: `admission.py`'s
module-level imports are `__future__`, `hashlib`, `dataclasses`, `rfc8785` — **no
`store` import exists in the module at all**. The one engine-internal reach
(`from .sqlite_store import FACT_COLUMN_INDEX`) is inside `_verify_admitted_rows`, so
`sqlite_store`'s module-level import of the commitment is not a cycle. Confirmed by
importing each module alone, in both orders: no cycle either way.

**Rule 18 green** with `libs/engine/src/engine/admission.py` present in `_SCAN_TARGETS`,
the join trigger (custody moved in) named at the site, and the §F ratchet asymmetry
documented there rather than papered over.

**Zero deltas, verified as COLLECTION counts** — which is what the claim "no test added
or removed" actually means. Both sides collected independently:

| Suite | Baseline `0d38c969` | Gate `e8c93295` | Delta |
|---|---|---|---|
| engine | 1990 collected | 1990 collected | **0** |
| store | 180 collected | 180 collected | **0** |
| architecture | 99 collected | 99 collected | **0** |

Pass results at the gate rev: engine **1989 passed, 1 skipped**; store **180 passed**;
architecture **99 passed**.

**`git ls-files` clean.** `git status --porcelain --untracked-files=all` empty at
`e8c93295`; the change is 8 tracked files (7 source/test + the report), no `uv.lock`
churn — which also keeps the ruff comparison in item 7 honest.

### 2. Mutations, re-run here — PASS (all three exact)

Each applied to `admission.py` in the gate worktree, target file run **whole** (not
`-k`, so collateral drift would show), then `git checkout --` and `git status` verified
empty before the next.

| # | Mutation | Result here | Report claimed |
|---|---|---|---|
| a | `_refuse_divergence` returns before raising | **3 failed, 28 passed** — all 3 `TestDivergenceRefusal`, all `DID NOT RAISE MergeDivergence` | 3 failed, 28 passed ✓ |
| b | `_verify_admitted_rows` returns before checking | **5 failed, 13 passed** — all `DID NOT RAISE AdmissionUnverified` | 5 failed, 13 passed ✓ |
| c | `admit_records` hands `_drafts_for` the SOURCE's genesis observer | **1 failed, 30 passed** — `test_a_merged_tick_names_the_TARGETS_custodian`, failing on the VALUE (`target-custodian` vs `source-custodian`) | 1 failed ✓ |

Tree clean after the cycle; store suite re-run **180 passed**.

**Assessment of the not-run revert-the-delegation arm: the impl's refusal is SOUND, and
(a)–(c) do satisfy "the op is on the live path."** The impl's stated reason (a faithful
inline copy is the same bytes in a different file, so the arm cannot discriminate) is
correct as far as it goes, but it is not what settles this. What settles it is the
**routing**: `test_admission_verification.py` imports exactly `merge_store` and
`AdmissionUnverified` from `store.merge`, and every one of its ~20 call sites goes
through `merge_store(...)`; `test_arrival_merge.py` imports `merge_store` and
`receive_store` and nothing else from the admission surface. **Neither file imports a
moved admission helper directly.** So each failure above is reached through
`merge_store` → `_merge_into_arrival` → `admit_records` → the mutated function. That is
strictly stronger than the revert arm, which only ever asked whether the op is reached
at all. Design §D.3's exit criterion is met in substance; the brief's "e.g." licensed
this substitution, and it was the right call.

### 3. D2 — the severed monkeypatch seam — PASS, reproduces bit-for-bit

Re-derived independently with a throwaway probe (a `verify_facts` call **before**
`reanchor`, the assertion the fixture never makes), run across all three arms. Probe
kept in scratchpad, never committed; both worktrees restored and verified clean.

| Arm | Arrangement | `verify_facts` before `reanchor` | Report claimed |
|---|---|---|---|
| 3 | **baseline `0d38c969`**, original test (patch `sqlite_store` only) | `ok=False`, **3 breaks** | ok=False, 3 breaks ✓ |
| 2 | gate rev, test **un-fixed** (admission patch removed, both sites) | `ok=True`, **0 breaks** | ok=True, 0 breaks ✓ |
| 1 | gate rev, **committed fix intact** (both modules patched) | `ok=False`, **3 breaks** | ok=False, 3 breaks ✓ |

**And the silence reproduces too, which is the part that matters.** With the fix removed
at the gate rev, `test_tick_chain.py` runs **51 passed** — a fully green file over a
fixture that had stopped being the scenario its docstring describes. The mechanism is
confirmed at source: `TestReanchor` asserts `verify_facts` only at line 883, *after*
`reanchor`, so nothing in the file was positioned to notice.

The committed fix patches **both** modules inside the same `monkeypatch.context()`, at
both fixture sites, with the reason written at the site. The general lesson the report
draws — a module-global monkeypatch is a seam a move can sever with no assertion
noticing, so a moved function must be checked against what *patches* it, not only what
calls it — is carried by this evidence and is worth keeping past this WP.

### 4. D1 — forced moves beyond the table — PASS, forcing argument holds at source

Read `_drafts_for` (`admission.py:358-404`) directly. It consumes `_comparable` (twice),
`_refuse_divergence`, and `_draft_for`/`RecordDraft` — all four moved by §C.3's table —
and returns `(drafts, facts, ticks, admitted)`, where `admitted` is precisely the list
`_verify_admitted_rows` (also moved) takes as its first argument.

So the two options for leaving it in `store` are exactly as stated: `engine` imports
`store` (Rule 4 forbids it outright), or `store` imports `_comparable`,
`_refuse_divergence`, `_draft_for` and `RecordDraft` back across the lib boundary to
reassemble a loop that no longer lives anywhere whole. `_SourceRows` is `admit_records`'
input parameter type and `_source_registry` reads its `.canonical`, so crossing as
public `SourceRows` is forced by the same argument. **The deviation is real, correctly
reasoned, and correctly reported rather than left for the gate to find.**

### 5. Extraction discipline — PASS (one precision nit, F1)

- **The arm is still owned and merely delegates.** `_merge_into_arrival`
  (`merge.py:249-311`) reads both sides, calls `admit_records` with the two callbacks,
  and maps counts back. **No merge arm was deleted**: sqlite arm at `:177`, arrival arm
  at `:249`, jsonl refusal at `:158`.
- **`merge_store` dispatch.** The executable body is **AST-identical** across the two
  revs (docstring stripped, compared as normalized AST). One docstring line differs —
  see finding **F1**.
- **SD-1 held.** `_stage_arrival_coordinates`, `_check_arrival_provider_agreement`, and
  `_stamp_arrival_axis` extracted from both revs and diffed: **byte-identical**, line
  offsets shifted only by the removals above them. The whole `sqlite_store.py` diff is
  the three removals plus the import-back — the coordinate machinery is untouched, as
  C.1's ruling requires.
- **Public surface preserved** — verified by running the imports, not by reading them:

  ```
  store.MergeDivergence            -> engine.admission.MergeDivergence
  store.merge.MergeDivergence      -> same object as store.MergeDivergence
  store.merge.AdmissionUnverified  -> engine.admission
  engine.sqlite_store.fact_commitment_hash   -> same object as admission's
  engine.sqlite_store._fact_commitment_hash  -> same object as admission's
  engine.fact_commitment_hash (lazy)         -> engine.admission, same object
  ```

  **Both** historical spellings resolve, and to the same function object. `_pinned_head`
  stayed in `store.merge` as claimed; `test_arrival_merge_pin.py` imports it by that
  path and passes (3 passed).
- **`engine/__init__.py` lazy map repoints** `fact_commitment_hash` to
  `engine.admission` — a one-line diff, and the resolved object matches.
- **No third `_canonical_bytes`.** Source definitions across the whole tree, both revs:
  baseline = `sqlite_store.py` + `arrival.py` (2); gate = `admission.py` +
  `arrival.py` (2). Count unchanged; the sqlite spelling moved rather than forked.
  (`test_ceremony_orchestration.py` has an unrelated same-named helper taking `world`,
  present at both revs.)
- **`arrival.py` untouched** — diff is **0 lines**, as slice 5's deferral requires.
- **`APPEND_ATTEMPTS` semantics preserved.** Value `8` at both revs; now the op's
  default parameter (`attempts: int = APPEND_ATTEMPTS`) and exported. No stale
  `_APPEND_ATTEMPTS` survives in any source file.

### 6. Design-choice audit — PASS (one precision nit, F2)

- **The two-callback signature keeps engine free of store.** `admit_records`' types are
  `ArrivalLog`, `SourceRows`, `Head`, `Verify`, `Callable`, `bool`, `int` — engine and
  contract vocabulary only. **No store type appears in any signature**, and no `store`
  import exists in the module. The callbacks are the mechanism that makes this possible
  rather than a workaround for it: the sqlite projection genuinely is the caller's.
- **`AdmissionResult` ↔ `MergeResult` loses nothing.** Both are frozen dataclasses of
  the same four ints (`facts_added`, `facts_skipped`, `ticks_added`, `ticks_skipped`);
  `_merge_into_arrival` maps all four across, field for field.
- **The module-level `engine.admission` import in `merge.py` — the discipline break is
  honestly named and the cost claim's conclusion is verified (stronger than measured).**
  Baseline `merge.py`'s only module-level import was intra-lib (`._conn`), so this
  genuinely is the module's first eager cross-lib import; the report does not soften
  that, and it names the reason at the site. **Rule 16 holds**: its allowlist judges bare
  `import atoms/engine/lang`, and a bare `import engine` in a fresh interpreter pulls in
  **nothing** (`engine.admission`, `engine.sqlite_store`, `rfc8785`, `engine.arrival` all
  absent). On the cost: the cold import footprint of `engine.sqlite_store` is
  **byte-for-byte the same module set** at baseline and at the gate rev — `dataclasses`
  and `rfc8785` were already eager there — so nothing was added to the cold-open path.
  On the sdk path, `engine.admission` is already in `sys.modules` before `store.merge`
  is reached, so the eager import's marginal cost there is zero. See **F2** for the one
  figure that does not reproduce.
- **The `_canonical_bytes` docstring rewrite is Rule 18-correct.** `reanchor` — the
  denied token the original docstring carried — appears **nowhere** in `admission.py`
  (case-insensitive). The retired identifier is left named where it lives, in
  `sqlite_store`. Rule 18 is green with the module scanned.
- **Design choice 2 (pin timing) is genuinely behaviour-equivalent**, verified at
  source rather than accepted: `_pinned_head` completes the pin via `log.anchor(consumed)`,
  a seek to `consumed` — a position snapshotted by `_target_state` at attempt-top in
  *both* the baseline loop and the op. An arrival log is append-only, so the record at a
  given ordinal is immutable and the seek returns the same anchor whether it runs at
  read-time or append-time. The enforcement point is unchanged: the full-head
  compare-and-swap under the lock inside `append_marked_many`. If anything the new
  arrangement is tighter — the pin and the dedup snapshot are now read at the same
  instant.
- **`_entries_of` is honestly disclosed residue.** It does duplicate the
  `RecordDraft`→`Entry` conversion that `ArrivalLedger.append`
  (`arrival_contract.py:347`) will own, and the report names it as slice-5 residue with
  the reason (the brief pins `append_marked_many` as the op) rather than leaving it to be
  discovered. Correct call for this slice.

### 7. Line counts and lint — PASS (every number exact)

Measured with the same tools, from the worktree roots:

| Claim | Verified |
|---|---|
| `admission.py` 134 → 720 | **134 → 720** ✓ |
| `merge.py` 857 → 525 | **857 → 525** ✓ |
| `sqlite_store.py` 2860 → 2822 | **2860 → 2822** ✓ |
| ruff 61 → 60 findings | **61 → 60** ✓ |
| `I001` 3 → 2, no new class | **I001 3 → 2** ✓; rule histogram is a strict subset — same 9 classes, one `I001` fewer, nothing new ✓ |

Ruff run in-tree from each worktree root so config resolution matches, which is the
precaution the impl's own 16-vs-61 scratchpad mistake exists to teach.

---

## Findings

### F1 — "`merge_store`'s dispatch is byte-identical" overclaims by one line — NON-BLOCKING

The report (§1) says `merge_store`'s three-way dispatch is byte-identical. The
**executable code is AST-identical**, which is the load-bearing part and it holds. But
the function is not byte-identical: one docstring line changed,
`:func:`_verify_admitted_rows`` → ``engine.admission._verify_admitted_rows``.

Non-blocking, and the change itself is *correct* — the function it cross-referenced
moved, so leaving the old pointer would have been exactly the un-swept residue this
repo's conventions forbid. The issue is only that a gate checking "byte-identical"
literally would trip on a line the impl had every reason to change. The claim should
have read "the dispatch code is unchanged; one docstring cross-reference was swept."

### F2 — design choice 10's `968µs` figure does not reproduce as stated — NON-BLOCKING

The report says `engine.admission` "measures 968µs cumulative with no child import
attributed to it." On a cold bare `import store.merge` here, `-X importtime` attributes
**4962µs cumulative** to `engine.admission`, **with `rfc8785` attributed as a child at
1151µs**. The figure is scoped in the report to "the sdk.emit path," and that scoping is
what makes it true — it is not a general cost, and as written it reads more general than
it is.

Non-blocking, because **the conclusion is not just intact but better supported than the
report's own measurement makes it**: the cold import footprint of
`engine.sqlite_store` is byte-for-byte identical at baseline and gate rev (`dataclasses`
and `rfc8785` were already eager on that path), and on the sdk path `engine.admission`
is already loaded before `store.merge` is reached, so the eager import's marginal cost
is zero. There is no cold-open regression, and no cold-open ratchet exists in the tree
to regress. The footprint comparison is the evidence this claim should have rested on.

---

## Verdict

**GATE: PASS.**

All seven oracle items PASS. The three mutations reproduce exactly and, on the import
evidence, prove the op is on the live path through `merge_store` — stronger than the
revert arm the impl declined, whose refusal is sound. D2 reproduces bit-for-bit across
all three arms, including the silence itself (51 green tests over a half-built
scenario), and its fix is correct and reasoned at the site. D1's Rule-4 forcing argument
holds at source. SD-1 held byte-for-byte, no merge arm was deleted, the public surface
resolves under every historical name, and no third `_canonical_bytes` was minted.

Both findings are documentation-precision issues in the report's own wording. Neither
touches behaviour, neither required a code change, and in both cases the underlying work
is right — in F2's case, more right than claimed. **Nothing blocks.**
