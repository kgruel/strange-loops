# Gate report — slice C5 (lens key families + checkpoint dispatch)

**Target:** `slice/c5-lens-key-families` @ `9ca1aafb`, one commit over wave tip `7b52e190`.
**Gate worktree:** `slice/c5-lens-key-families-gate` (independent; the implementer's worktree and
`/Users/kaygee/Code/loops` were not touched — no pytest was ever run in either).

## VERDICT: **PASS** — no blocking findings. Four advisories below.

Every claim in the implementer's report that I could test independently held. The four power
proofs I ran used mechanics the implementer did not use, and all four landed where predicted.

---

## Item 1 — Scope: **PASS**

`git diff --stat 7b52e190...HEAD` is exactly the reported 11 files, +839/-50:

```
 libs/atoms/src/atoms/__init__.py                          |   2 +
 libs/atoms/src/atoms/ordering.py                          |  30 +++
 libs/engine/tests/test_conformance_lens.py                |  81 +++++-
 libs/engine/tests/test_ordering_checkpoint_dispatch.py    | 205 +++++++++++++++
 spec/conformance/SCHEMA.md                                |  19 +-
 spec/conformance/generate_lens.py                         | 287 +++++++++++++++++++--
 .../lens/lens-by-key-missing-field-excluded.json          |  73 ++++++
 .../lens/lens-by-key-mixed-types-refused.json             |  45 ++++
 .../vectors/lens/lens-by-key-payload-seq.json             |  62 +++++
 .../vectors/lens/lens-by-key-tie-id-asc.json              |  62 +++++
 ...test_rule_17_fold_order_prose_is_receipt_order.py      |  23 +-
 11 files changed, 839 insertions(+), 50 deletions(-)
```

KEEP fences, verified rather than accepted:

```
$ git diff feat/arrival-libs...HEAD -- libs/engine/src/engine/handle.py | wc -l
0
$ git diff 7b52e190...HEAD -- libs/engine/src/engine/handle.py | wc -l
0
$ git diff 7b52e190...HEAD -- libs/atoms/src/atoms/spec.py benchmarks/ | wc -l
0
```

`handle.py` is verbatim-untouched against BOTH the arbiter-named base and the wave tip.
`Spec.replay_from` and the benchmark arms are untouched. All four new vector files are
tracked (`git ls-files spec/conformance/vectors/lens/` lists six files: the two frozen ts
vectors plus the four new by-key ones).

## Item 2 — Vector contract, NORMATIVE: **PASS**

Regenerated independently in my own worktree, from a cold `uv sync --all-packages`:

```
$ uv run python spec/conformance/generate_lens.py
Wrote spec/conformance/vectors/lens/lens-timestamp-tie-id-asc.json
Wrote spec/conformance/vectors/lens/lens-sub-millisecond-timestamp-precision.json
Wrote spec/conformance/vectors/lens/lens-by-key-payload-seq.json
Wrote spec/conformance/vectors/lens/lens-by-key-tie-id-asc.json
Wrote spec/conformance/vectors/lens/lens-by-key-missing-field-excluded.json
Wrote spec/conformance/vectors/lens/lens-by-key-mixed-types-refused.json
$ git diff --stat spec/conformance/
$ git status --short
(empty)
```

Regeneration-stable. And byte-frozen against the pre-slice tip, which is the stronger claim
loops-go depends on:

```
$ git diff 7b52e190...HEAD -- \
    'spec/conformance/vectors/lens/lens-timestamp-tie-id-asc.json' \
    'spec/conformance/vectors/lens/lens-sub-millisecond-timestamp-precision.json' | wc -l
0
```

The mechanism that buys this is sound and I checked it in the diff: the ts family is the
DEFAULT, and `generate_lens.py` omits `input.ordering` from the wire whenever
`case.ordering == DEFAULT_ORDERING`, so no byte is added to those two files. Their oracle
also stays `vertex_facts` — `totalize` is only asserted to agree, and a disagreement raises
`AssertionError` before anything is written.

## Item 3 — Checkpoint dispatch tests: **PASS** (with one reading stated, not checked off)

- **Enumeration is against `get_args(Ordering)`, no default licence.**
  `test_every_ordering_variant_is_ruled` asserts `set(get_args(Ordering)) == set(LICENSING)`,
  so adding a union member without ruling on it fails. Confirmed by reading, and the
  no-default path is separately proved RED below (Proof A).
- **`Arrival` licenses checkpoint + `replay_from` suffix.**
  `test_replay_from_suffix_replay_is_sound_under_arrival_only` runs both variants through the
  actual mechanism (`spec.replay` for the checkpoint, `spec.replay_from` for the warm step,
  `spec.replay` over the full totalized list for the cold reference) and asserts
  `(warm == cold) is sound` plus `is_suffix_stable(ordering) is sound`.
- **The fold is genuinely order-sensitive.** `_spec()` uses `Upsert(target="items", key="topic")`
  and every payload carries `topic="t"`, so it is last-write-wins over a single key — the
  strictest possible order discriminator. Confirmed by reading `atoms.fold`'s `Upsert`.
- **`ByKey` cold-folds.** Same test, `sound=False` arm: the backdated record belonged *before*
  the checkpointed prefix, so `warm != cold`.

**Reading the gate should have, on "a real backdated append":** the divergence test
(`test_replay_from_suffix_replay_is_sound_under_arrival_only`) backdates an *in-memory*
record — `_LATE_ARRIVAL = {"id": "r3", "ts": 100.0}` appended to a Python list. The *sqlite*
backdated append lives in the adjacent
`test_handle_takes_the_warm_path_under_the_licensed_ordering`, which writes
`_append(store, 100.0, ...)` after `_append(store, 300.0, ...)`, refreshes, and asserts
`batch.replay_mode == "checkpoint-suffix"`. So the pair jointly satisfies the brief's intent
— divergence proved on the real `replay_from` mechanism, real backdated store append proved
against the real handle — but no single test does both. I accept this: splitting them is what
lets the divergence test stay a pure taxonomy test with `handle.py` untouched, which was the
arbiter's constraint. Recording it explicitly rather than ticking the box.

## Item 4 — Suites re-run, and the lang count RECONCILED: **PASS**

All run by me in the gate worktree. Every number matches the implementer's report exactly:

| suite | result |
|---|---|
| `tests` | 110 passed |
| `libs/engine` | 1761 passed, 1 skipped |
| `libs/atoms` | 486 passed |
| `libs/store` | 175 passed |
| `libs/sdk` | 313 passed |
| `libs/lang` | 655 passed |
| `apps/loops` | 2525 passed, 1 xfailed |

**The lang reconciliation — answered, not waved through.** `libs/lang` is *byte-identical*
from `main` through this slice: `git diff --stat main...slice/c5-lens-key-families -- libs/lang`
is empty, and `git log main..feat/arrival-libs -- libs/lang` is empty. So the slice cannot have
changed the count, and neither can wave drift.

The 691-passed/3-skipped figure is an **environment difference**, and the arithmetic closes
exactly. Three lang test functions are parametrized over a corpus discovered by
`_REPO_ROOT.rglob("*.vertex")` at collection time — one in `libs/lang/tests/test_kdl_splice.py`
(rglob at :311, parametrize at :331) and two in `libs/lang/tests/test_vertex_mutation.py`
(rglob at :374, parametrizes at :384 and :425). The two `pytest.skip` sites in the whole
package (`test_kdl_splice.py:342`, `test_vertex_mutation.py:435`) are both inside that corpus
family, which is why skips only appear when the corpus is larger.

```
$ find /Users/kaygee/Code/loops -name '*.vertex' | wc -l   →  24
$ find <gate worktree> -name '*.vertex' | wc -l            →  11
$ git ls-files '*.vertex' | wc -l                          →  11
```

13 untracked live `.vertex` files exist in the main checkout and in no fresh worktree.
**13 extra files × 3 corpus-parametrized tests = 39**, and `691 + 3 = 694`, `694 − 655 = 39`.
Bit-for-bit. The 3 skips are the extras that carry no known parent block / no loop kinds.

Answer: not version drift, not a subset run, not slice-caused — `libs/lang`'s collection is
non-hermetic, so its count is only comparable between trees with the same untracked `.vertex`
corpus. See Advisory 1. (I deliberately did not run pytest in the main checkout to prove this;
the file-count arithmetic is sufficient and running there would have written `.pytest_cache`
into a tree I was told not to touch.)

## Item 5 — Independent power proofs: **PASS** (3 of 3 landed as predicted)

All mechanics are novel — none appears in the implementer's list. Tree restored and clean
after each (`git status --short` empty, pasted at the end).

**Proof A — the no-default rule, broken by *granting* the licence rather than by flipping a
ruled answer.** Replaced `case _: raise OrderingError(...)` with `case _: return True` in
`atoms/ordering.py`, i.e. an unknown variant silently becomes checkpoint-eligible:

```
E       Failed: DID NOT RAISE OrderingError
libs/engine/tests/test_ordering_checkpoint_dispatch.py:64: Failed
FAILED ...::test_unknown_ordering_variant_is_refused_not_defaulted
1 failed, 8 passed
```

RED, correctly. Note *which* test caught it: only the dedicated refusal test.
`test_every_ordering_variant_is_ruled` stayed green, because it compares the union's members
against the table and says nothing about the fall-through. That is the correct division of
labour, but it means the enumeration test alone would not close this hole — the pair is
load-bearing, not redundant.

**Proof B — the runner's refusal branch deleted** (the brief's "make the runner ignore
`expected.error`"). Removed the `if "error" in vector["expected"]: with pytest.raises(...)`
block from `test_conformance_lens.py`:

```
E  atoms.ordering.OrderingError: mixed key types under declared key 'seq': int and str (offending value '2')
libs/atoms/src/atoms/ordering.py:158: OrderingError
FAILED ...::test_conformance_lens[lens-by-key-mixed-types-refused]
1 failed, 7 passed
```

RED, correctly, and it fails by the refusal *escaping* rather than by a `KeyError` on a
missing `lens_order` — so the vector is genuinely exercising the refusal, not merely the
absence of an expected order.

**Proof C — the invariance probe (must STILL pass).** Hand-edited
`lens-by-key-tie-id-asc.json`: reversed each member's append array in place *and* reversed the
member-label order in `input.members`.

```
member append order reversed in-file
1 passed
```

Correct. All three records sit at `seq=7`, so the entire order comes from the `id ASC`
tie-break inside `totalize`; append order and member iteration order are inert, exactly as
SCHEMA §9 asserts. Had this vector's expected order leaked from file order, this would have
gone RED. Restored via `git checkout -- spec/conformance/vectors/`.

Final state after all proofs: `git status --short` → empty.

## Item 6 — Adversarial probes on the runner branch: **PASS**

The four new vectors run individually and green through the runner's declared-key branch:

```
test_conformance_lens[lens-by-key-missing-field-excluded] PASSED
test_conformance_lens[lens-by-key-mixed-types-refused]    PASSED
test_conformance_lens[lens-by-key-payload-seq]            PASSED
test_conformance_lens[lens-by-key-tie-id-asc]             PASSED
test_conformance_lens[lens-sub-millisecond-timestamp-precision] PASSED
test_conformance_lens[lens-timestamp-tie-id-asc]          PASSED
test_lens_area_is_not_empty                               PASSED
test_lens_area_covers_both_key_families_and_a_refusal     PASSED
8 passed
```

**Hand-built `{"by_key": "id"}` — the self-keying question.** I built a probe vector from
`lens-by-key-payload-seq`'s members with `ordering: {"by_key": "id"}` and expected the
id-ascending order. It **passes**: `id` resolves against the envelope per SCHEMA §9's resolver
rule, and the totalization degenerates to `(id, id ASC)` = plain id ASC. This is a real
discriminator on that fixture, since its seq order is the exact reverse of its id order
(`...003, ...002, ...001` under seq vs `...001, ...002, ...003` under id). Verdict: self-keying
is **sane and accepted**, not refused, and the behaviour matches SCHEMA.md rather than
diverging from it. I see no reason to refuse it — `id` is a total order by construction, so it
is the one key for which the tie-break can never fire. Probe deleted afterwards.

**Second probe, unprompted — a non-`ts`/`id` envelope field.** `{"by_key": "observer"}` over
the same fixture produces an **empty projection** and passes with `lens_order: []`. Every
record has an `observer` on its envelope, but the resolver sends anything outside `{ts, id}` to
the payload, where it is absent — so missing-K non-membership excludes all of them. This is
strictly schema-consistent ("every other key resolves against the flat payload") and not a bug,
but it is a silent-empty footgun. See Advisory 2. Probe deleted; tree clean.

## Item 7 — Full diff read, cruft: **PASS**

Read the complete diff. No debug statements, no commented-out code, no stray files, no TODOs,
no leftover scaffolding. Docstrings are dense but they are carrying the contract, not narrating
the change. The `wt-base` worktree I created during the lang reconciliation has been removed.

**Ruff, verified rather than accepted.** The report claims "3 pre-existing findings, none
added." Confirmed: checking out `7b52e190`'s versions of `generate_lens.py` and
`test_conformance_lens.py` and re-running gives the same `Found 3 errors.` The surviving one on
the current generator is `I001` (import block un-sorted) at `generate_lens.py:35`, which
pre-dates the slice. CI lints only `libs/custody libs/sign` (`.github/workflows/ci.yml:65`), so
none of this is gated. See Advisory 3.

## Rule 17 allowlist shrink — checked against the arbiter's ruling

Four entries deleted, none added, none modified — verified in the diff. All four excused prose
that the slice rewrote: SCHEMA §9's two `(ts ASC, id ASC)` lines and `generate_lens.py`'s two
docstring lines. The replacement comment names the shrink and why. Shrink-only, as ratified.
`tests/architecture` is green (110 passed), which includes
`test_allowlist_has_no_stale_entries` — so the shrink is exercised, not merely asserted.

---

## Advisories (all non-blocking, none gate-relevant)

1. **`libs/lang` collection is non-hermetic** — `_REPO_ROOT.rglob("*.vertex")` in
   `test_kdl_splice.py:311` and `test_vertex_mutation.py:374` makes the test count a function
   of untracked files in the working tree (24 vs 11 `.vertex` files ⇒ 694 vs 655 collected).
   Not introduced by this slice and out of its scope, but it will keep producing phantom
   "count drift" findings in future gates. Worth pinning the corpus to `git ls-files` output,
   or at minimum asserting a fixed corpus size, in a later cleanup slice.

2. **The field resolver silently empties a projection keyed on a non-`ts`/`id` envelope field.**
   `{"by_key": "observer"}` yields `[]` rather than an error, because the key resolves against
   the payload and is missing there. Missing-K non-membership is correct and declared; the
   footgun is that a plausible envelope key is indistinguishable from a typo. If C6+ ever
   exposes ordering declarations to users, an "empty projection under a declared key" warning —
   or admitting more envelope fields to the resolver — is worth considering. Purely
   forward-looking; nothing to change here.

3. **Two of the touched engine test files fail `ruff format --check`**
   (`test_ordering_checkpoint_dispatch.py`, `test_conformance_lens.py`). `generate_lens.py`
   already failed it at `7b52e190`, so formatting is not enforced on this tree and CI does not
   check these paths. Cosmetic.

4. **`is_suffix_stable` matches `case Arrival()` structurally**, so a *subclass* of `Arrival`
   would silently receive the checkpoint licence, and `get_args(Ordering)` would not see it
   (subclasses are not union members) — the enumeration test would stay green. The taxonomy is
   a closed union by convention so this is not reachable today, and it is exactly the shape of
   default-licence hole the test suite is built to close, which is why it is worth naming. No
   change requested.

---

## Overall

**PASS.** The normative frozen vectors are byte-identical against the pre-slice tip and
regenerate stably from a clean environment; the key axis is genuinely optional on the wire,
which is *why* they are; the checkpoint licence is a ruled property with no default path and
its refusal is proved RED; the ts family's oracle was not swapped underneath the frozen files;
`handle.py`, `Spec.replay_from`, and the benchmarks are untouched; the Rule 17 shrink is
shrink-only and exercised; every suite is green with the lang delta fully explained by an
environment property that predates the slice. No blocking findings.
