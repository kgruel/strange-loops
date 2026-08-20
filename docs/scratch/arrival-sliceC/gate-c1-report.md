# Gate report — slice C1, atoms `Ordering` + totalization

**Verdict: PASS.** No blocking findings. Four non-blocking advisories, enumerated at the end.

Gate worktree `.../scratchpad/wt-c1-gate` on `slice/c1-atoms-ordering-gate`, branched from
`slice/c1-atoms-ordering` @ **e2c0f0c5**. Contract: `docs/scratch/arrival-sliceC/design-proposal.md` §Q1.
The implementer report was treated as a claim set, not as evidence.

## 1. Scope — PASS

`git log --oneline feat/arrival-libs..HEAD` shows exactly one commit, so the merge-base diff hides
nothing:

```
e2c0f0c5 feat(atoms): declared Ordering primitive with one totalization
```

Base confirmed: `git rev-parse feat/arrival-libs HEAD~1` → both `cac20d5f`. (The report's stated parent
`cac20d5f` is correct; the integration branch advanced past `a49997cd` when C0 landed.)

```
$ git diff feat/arrival-libs...HEAD --stat
 libs/atoms/src/atoms/__init__.py  |  12 ++++
 libs/atoms/src/atoms/ordering.py  | 142 ++++++++++++++++++++++++++++++++++++++
 libs/atoms/tests/test_ordering.py | 127 ++++++++++++++++++++++++++++++++++
 3 files changed, 281 insertions(+)
```

Tracked-ness verified with `git ls-files` rather than `git status` (the repo ignores `*.jsonl` and
friends): both new files are tracked. `git status --short` is empty. Only `libs/atoms/` touched — the
fence holds.

## 2. Suites re-run independently — PASS

```
$ uv run --package atoms pytest libs/atoms/tests -q
486 passed in 9.91s

$ uv run pytest tests -q
110 passed in 4.48s
```

Both match the report's numbers exactly.

## 3. Power proofs, independently constructed — PASS

Three breaks, each using a **different mechanic** from the one the report used for the same test, so
these are independent confirmations rather than replays. After each, the file was restored from a
byte-for-byte copy; the final `git status --short` and `git diff --stat` are empty and the suite is
green again.

**Break A — id tie-break neutered by constant, not by dropping the tuple element.**
`keyed.append((value, get_id(record), record))` → `keyed.append((value, 0, record))`.
The report dropped `entry[1]` from the sort key; this instead keeps the two-element key and starves it.

```
libs/atoms/tests/test_ordering.py:17: AssertionError
FAILED libs/atoms/tests/test_ordering.py::TestByKey::test_sorts_by_key_then_id_ascending
1 failed, 18 passed in 0.08s
```

**Break B — the type-identity check deleted outright, not loosened to `isinstance`.**
The `if key_type is None / elif type(value) is not key_type: raise` block replaced by a bare
`key_type = type(value)`. The report reported that the `isinstance` loosening does **not** fail the
int/float test; deleting the check entirely does, which independently confirms that test has real
power over the strict-type-identity posture:

```
FAILED libs/atoms/tests/test_ordering.py::TestMixedTypes::test_bool_is_not_int
FAILED libs/atoms/tests/test_ordering.py::TestMixedTypes::test_int_and_float_under_one_key_refuse
2 failed, 17 passed in 0.06s
```

(`test_string_and_int_under_one_key_refuse` correctly survives this break — `"5"` vs `5` still blows up
in `sort` and is wrapped as `OrderingError`. That is the test working as specified, not a hole.)

**Break C — `Arrival()` synthesizes order from a payload field, not from the id.**
`return list(records)` → `return sorted(records, key=lambda r: r.get("ts", 0))`. The report broke
Arrival by sorting on id; this proves the ratchet also catches field-derived synthesis, which is the
form C2/C4 would plausibly reach for.

```
libs/atoms/tests/test_ordering.py:101: AssertionError
FAILED libs/atoms/tests/test_ordering.py::TestArrival::test_returns_records_in_the_order_given
1 failed, 18 passed in 0.06s
```

Restored state:

```
$ git status --short      (empty)
$ git diff --stat         (empty)
$ uv run --package atoms pytest libs/atoms/tests/test_ordering.py -q
19 passed in 0.08s
```

## 4. Adversarial probes — inputs the suite does not cover — PASS

Run against the real module; each line is actual output.

```
empty records ByKey: OK -> []
empty records Arrival: OK -> []
equal K + equal id: OK -> ['a', 'a']
equal K, mixed id types: OrderingError: key values under declared key 'ts' do not compare:
    '<' not supported between instances of 'str' and 'int'
distinct K, mixed id types (no tie): OK -> ['a', 1]
generator ByKey first: OK -> ['a', 'b']
generator consumed twice: OK -> []
record with K but no id: KeyError: 'id'
ByKey('id') self-key: OK -> ['a', 'b']
single record mixed-type never checked: OK -> [{'id': 'a', 'ts': '5'}]
float nan key: OK -> ['a', 'b']
None ordering variant: OrderingError: unknown Ordering variant: None
Ordering is a union alias: atoms.ordering.Arrival | atoms.ordering.ByKey
ByKey subclass matches: OK -> ['b', 'a']
```

Against the contract:

- **Equal K and equal id** — stable, no comparison ever reaches the record itself. The triple's third
  element is never in the sort key, so a non-comparable record can never crash a tie. Correct.
- **Empty input** — `[]` under both variants, no special-casing needed.
- **Record with K but no id** — raw `KeyError` from the default accessor, exactly the ruled posture
  (arbiter ruling 6). Matches, not re-litigated.
- **Mixed-type ids** — refuses when they actually collide in a tie, passes when K already separates
  them. Refusing loudly is the contract-consistent outcome; see advisory 3 on the message.
- **Generator consumed twice** — second call yields `[]`. Standard exhausted-iterator behavior, and
  `totalize` correctly materializes on the first pass (`list(records)` for Arrival, the triple list for
  ByKey), so no caller gets a lazily-half-consumed result.
- **Unknown variant** (`None`, a bare string) — `OrderingError`, no identity fallback.

## 5. Diff read line by line — PASS

- **ONE totalization.** `ordering.py` contains exactly one `sort` call (`keyed.sort(key=lambda entry:
  (entry[0], entry[1]))`) and no other sort-key definition anywhere in the diff. No second definition
  snuck into `__init__.py` or the tests.
- **id is tie-break only.** The key tuple is `(K, id)` in that order, ascending, and the semantic
  position is pinned by `test_id_is_tie_break_only_never_semantic_time` (a low K with a high id sorts
  first) — verified red under break A's sibling mechanic.
- **Missing K is non-membership.** `if value is None: continue` runs *before* the triple is built and
  before the type check, so absent records neither appear in the projection nor participate in type
  refusal. Both halves are pinned by tests.
- **No coercion.** `type(value) is not key_type` — identity, not `isinstance`, so `bool` is not `int`
  and `int` is not `float`. The error names the field, both type names, and the offending value.
- **`Arrival()` never synthesizes.** `return list(records)`; neither accessor is referenced in that arm.
- **Exports match the lazy-import idiom.** The five names are added to both `__all__` and
  `_LAZY_IMPORTS` in a matching commented block, placed and internally ordered like the neighbouring
  Fold/Parse blocks (classes sorted, lowercase functions last). Verified empirically that the laziness
  is real:

  ```
  after bare import atoms.ordering in sys.modules: False
  lazy attr works: ByKey(field='ts')
  now in sys.modules: True
  ```

- **Docstrings state the ruled postures** — declared-not-inferred, per-log dense ordinals, not
  expressible cross-store, id tie-break "never semantic time", missing-K and `None` as non-membership
  with the exclusion-by-declaration framing, mixed-type and non-comparable refusal, accessors ignored
  for `Arrival()`. One ruling is missing; see advisory 2.

## Advisories — all NON-BLOCKING

1. **B017 lint introduced by this slice.** `test_both_variants_are_frozen_and_compare_by_value` uses
   `pytest.raises(Exception)`; `dataclasses.FrozenInstanceError` is the precise assertion. Confirmed
   this is the *only* B017 in `libs/atoms` (`ruff check --select B017 libs/atoms` → 1 hit, the new
   one), so it is new debt rather than house style. Non-blocking because CI lints only
   `libs/custody libs/sign` (`.github/workflows/ci.yml:65`), not atoms. Separately,
   `ruff format --check` flags `libs/atoms/src/atoms/__init__.py`, but that is **pre-existing** — the
   base-branch copy fails the same check at an untouched line — so it is not this slice's residue.
2. **The docstring omits ruled posture 6.** Record-with-K-but-no-id raising a raw accessor error is a
   settled ruling but is not stated anywhere in `totalize`'s docstring; the other rulings are. Worth a
   line at C2 or wherever the first consumer lands. In the same spirit, the int-vs-float refusal is
   covered only by the generic "mixed types" sentence — given the implementer named it the likeliest
   place C1 blocks C4, an explicit clause would earn its keep. Flagged as a documentation gap only; the
   ruling itself is settled and not re-litigated here.
3. **One error message blames the wrong tuple element.** When K values are equal and the *ids* do not
   compare, the raised text is `key values under declared key 'ts' do not compare`. The refusal is
   right; the attribution is not. Cosmetic.
4. **Unruled edge behaviors, noted for the record, none contradicting the contract.** `ByKey`
   subclasses match the `case ByKey(...)` arm (ordinary structural-match semantics). NaN key values sort
   without complaint and produce an arbitrary order (inherent float behavior, not something the
   type check can see). A generator passed twice yields `[]` on the second call.

## Unverified by this gate

Inherited from the slice's own scope, restated so nothing is presumed proved: no consumer imports
`totalize` yet, so "three near-copies ruled out by construction" is a C2/C4/C5 claim, not a C1 fact;
the `Arrival()` ≡ old-rowid-sequence equivalence is a store-level pin outside this slice; and there is
no performance measurement of the per-call triple list.

## Cleanup

Temporary break backups and the extracted base file were deleted. `git status --short` in the gate
worktree is clean apart from this report.
