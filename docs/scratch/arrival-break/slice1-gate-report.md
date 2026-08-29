# Slice 1 gate report — wire v1 pin

**GATE: PASS** (2 non-blocking findings, 0 blocking)

Independent re-run of the slice-1 oracle from scratch. Target: `slice/arrival-wire-v1`
@ `83f8f323`. Contract: `docs/scratch/arrival-break/slice1-impl-brief.md` @ `68c7aa57`,
binding sub-ruling `01M172M74FZ9E27V34QKDF7Y77`
(`decision:design/arrival-wire-v1-seam-triage`). The implementation report
(`slice1-impl-report.md`, read from git bytes at `83f8f323`) was treated as the review's
target, not its authority — every claim below was re-derived.

## Gate mechanics

Fresh worktree `~/Code/loops-slice1-gate` on `slice/arrival-wire-v1-gate` @ `83f8f323`.
Own venv (`uv sync --all-packages`), never the implementer's:

```
$ command -v python  -> /Users/kaygee/Code/loops-slice1-gate/.venv/bin/python
$ command -v pytest  -> /Users/kaygee/Code/loops-slice1-gate/.venv/bin/pytest
engine: /Users/kaygee/Code/loops-slice1-gate/libs/engine/src/engine/__init__.py
store:  /Users/kaygee/Code/loops-slice1-gate/libs/store/src/store/__init__.py
atoms:  /Users/kaygee/Code/loops-slice1-gate/libs/atoms/src/atoms/__init__.py
```

Base is current, not stale: `git merge-base main 83f8f323` = `68c7aa5711c3c354` = the
`main` tip, so the diff read in item 5 is against live main.

---

## Item 1 — full suites green in a fresh env, counts reconciled — **PASS**

All nine suites run in the gate's own venv. Every count matches the implementation
report's table exactly; no reconciliation was needed.

| Suite | Gate result | Report claim | Match |
| --- | --- | --- | --- |
| `libs/engine/tests` | 1937 passed, 1 skipped (81.36s) | 1937 p + 1 s | yes |
| `libs/store/tests` | 177 passed | 177 | yes |
| `libs/atoms/tests` | 517 passed | 517 | yes |
| `libs/custody/tests` | 13 passed | 13 | yes |
| `libs/lang/tests` | 655 passed | 655 | yes |
| `libs/sdk/tests` | 324 passed | 324 | yes |
| `libs/sign/tests` | 37 passed | 37 | yes |
| `tests/architecture` | 98 passed | 98 | yes |
| `tests/chaos` | 12 passed | 12 | yes |

**Pre-existing `ImportPathMismatchError` — confirmed pre-existing.** Reproduced on BOTH
sides with the same combined invocation. On the slice tip:

```
$ python -m pytest libs/engine/tests libs/store/tests -q
_pytest.pathlib.ImportPathMismatchError: ('tests.conftest',
  '.../loops-slice1-gate/libs/engine/tests/conftest.py',
  PosixPath('.../loops-slice1-gate/libs/store/tests/conftest.py'))
```

and on the main checkout at `68c7aa5711c3c354` (its own venv):

```
_pytest.pathlib.ImportPathMismatchError: ('tests.conftest',
  '/Users/kaygee/Code/loops/libs/engine/tests/conftest.py',
  PosixPath('/Users/kaygee/Code/loops/libs/store/tests/conftest.py'))
```

Identical error, identical cause (both packages ship `tests/conftest.py`; both files are
present on `main` per `git ls-tree`). Not introduced by this slice.

The report's second reconciliation — that `pytest spec` collects zero tests — was
re-derived rather than restated:

```
$ python -m pytest spec -q                          -> no tests ran in 0.07s
$ find spec -name "test_*.py" -o -name "*_test.py"   -> (no output)
```

So `tests/architecture spec` and `tests/architecture` both reporting 98 is correct, not a
gap: `spec/` holds conformance vectors and their generators, and the vector consumers are
test modules inside the package suites above, all green.

**Conformance-vector blast is null — verified independently of the panel and of the
implementation report.** The sub-ruling verified this for the observer respell only and
explicitly left the `body.t` drop unassessed:

```
$ grep -rl '"t":' spec/conformance/vectors/         -> (no output)
$ grep -rlE '"lin"|"ord"|"rh"' spec/conformance/    -> (no output)
```

No checked-in vector carries a `t` discriminator, and none embeds an arrival envelope at
all, so nothing under `spec/` needed regeneration for either change. An arrival-envelope
vector family remains net-new work gated on this pin.

## Item 2 — inner-signature preservation — **PASS**

`test_dropping_t_moves_no_inner_commitment` (engine) asserts exactly what the oracle
names: `fact_commitment_hash` computed over the pre-drop row, then recomputed from the
row **recovered out of a t-less body**, and equality between them — plus that the inner
signature rides verbatim.

```python
row = fact_row(signature="sig:preserved")
before = fact_commitment_hash(*row[1:6])
(_t, recovered), = rows_of_body("fact", body_of_fact_row(row))
assert fact_commitment_hash(*recovered[1:6]) == before
assert recovered[6] == "sig:preserved"
```

PASSED in the targeted run. The test is synthetic, so the NON-NEGOTIABLE rests on it
*plus* the suites that exercise **existing** signed fixtures, all green above:
`test_jsonl_golden_fixtures.py`, `test_admission_verification.py` (store), and the
`libs/sign` + `libs/custody` suites. Structurally, no signature machinery could have been
touched: `libs/engine/src/engine/arrival.py` and `libs/custody/` do not appear in the
branch diffstat at all, so `fact_commitment_hash`, `content_commitment`,
`fact_signer_for` and `_resolve` are bit-identical to main. **No preserved inner
signature is invalidated.**

## Item 3 — byte-stable round trip on t-less records — **PASS** (with finding GF-1)

`test_encode_decode_encode_is_byte_stable` (3 params: fact, signed fact, tick) and
`test_a_batch_round_trips_byte_stably`. Both serialize to a **string and compare
strings**, not dicts:

```python
once = json.dumps(body, sort_keys=True, separators=(",", ":"))
(_t, decoded), = rows_of_body(k, json.loads(once))
twice = json.dumps(encode(decoded), sort_keys=True, separators=(",", ":"))
assert once == twice
```

All 4 PASSED. The comparison is on bytes, and `sort_keys=True` is the *correct*
canonicalization to compare under: the arrival record's body is hashed through
`arrival._canonical_bytes` → `rfc8785.dumps` (JCS), which sorts keys, so key order
carries no wire weight. See finding GF-1 for the docstring's overclaim about it.

## Item 4 — mutation demonstrations, re-run by the gate — **PASS**

All three reverted with a targeted edit in the gate worktree, the whole affected test
file run (not just the named test), then `git checkout --` and `git diff` confirmed empty
before the next. Every result matches the report, including its file-level pass counts.

**(a) batch same-observer check** — dropped the `_refuse_mixed_observers(rows)` call from
`arrival_body._validate_batch`:

```
FAILED test_arrival_body.py::test_a_batch_spanning_observers_is_refused_on_construction
FAILED test_arrival_body.py::test_a_batch_spanning_observers_is_refused_on_decode_too
2 failed, 21 passed          (Failed: DID NOT RAISE ArrivalBodyError)
RESTORED diff=[]
```

**(b) merge-site observer** — `store/merge.py` `_entry_for`: `observer=custodian` →
`observer=stripped[1]`:

```
FAILED test_arrival_merge.py::test_a_merged_tick_names_the_TARGETS_custodian
1 failed, 30 passed          (assertion diff: + pulse)
```

**(c) store-site observer** — `arrival_store._write`: `self._custodian()` →
`committed_row[1]`:

```
FAILED test_arrival_store.py::test_ticks_ride_as_records_naming_the_custodian_not_the_tick
1 failed, 19 passed          (assertion diff: + pulse)
```

**The two sites are genuinely independent — verified, not assumed.** I ran the *other*
package's test file under each mutation:

- under (b), `libs/engine/tests/test_arrival_store.py` → **20 passed** (engine blind to
  the merge site);
- under (c), `libs/store/tests/test_arrival_merge.py` → **31 passed** (store blind to the
  live write site).

So (b) and (c) fail different tests in different packages, and neither test would have
caught the other site — which is exactly the "single-site fix goes green and wrong" trap
ruling 2 called out.

Both tests are strong, not coincidental. The store-site test mints under
`observer="custodian"` with fact author `"kyle"` and tick name `"pulse"` — three-way
distinct — and asserts positively against `log.genesis()["observer"]`, that the fact
envelope beside it still names `"kyle"`, and that `"t" not in tick_record["body"]`. The
merge test uses `target-custodian` / `source-custodian` / `pulse` and asserts the label
is the TARGET's, explicitly `!= "source-custodian"`.

## Item 5 — contract conformance, read from the diff — **PASS**

Read `git diff main...83f8f323` plus per-commit `--name-only`.

- **Tick observer = destination log's genesis observer at BOTH mint sites.** Live path:
  `arrival_store._write` now passes `self._custodian()`, which is
  `self._log.genesis()["observer"]`. Merge path: `merge_store` reads
  `log.genesis()["observer"]` once per attempt and threads it
  `_entries_for(..., custodian)` → `_entry_for(kind, rows, custodian)` →
  `Entry(observer=custodian)`. Both land in one commit (`680b241b`). Prose at
  `arrival_store.py:25-27` and `merge.py:694-702` rewritten in the same change.
- **No fact/batch/genesis/key envelope-observer change.** Live fact path still
  `committed_row[3]`; `_ceremony_persist` still `observer=rows[0][3]` for both the `fact`
  and `batch` branch; merge's fact/batch branch still `observer=first[3]`. Genesis/key
  paths live in `arrival.py`, untouched.
- **No tick outer signatures added.** `signer=self._fact_signer if is_fact else None` is
  unchanged at the live site; `merge.py` has no `signer` anywhere but a docstring
  sentence saying it never will.
- **`content_commitment` shape untouched** — `arrival.py` is absent from the diffstat.
- **Legacy codec still writes and dispatches on `t`** — `object_of_fact_row` /
  `object_of_tick_row` / `object_of_batch` / `_dump` are semantically unchanged (the only
  `jsonl_codec` edits are the `_validate` → `row_object_fault` fault-returning refactor
  and hoisting `FACT_NULLABLE`/`TICK_NULLABLE`/`SIGNATURE_FIELD` to module constants).
  Pinned by `test_the_legacy_line_codec_keeps_its_t`.
- **Dual-signature machinery untouched** — neither `arrival.py` nor `libs/custody/`
  appears in the diff.
- **No `arrival_ordinal`/`arrival_seq` renames** — `git diff main...83f8f323 | grep` for
  both names returns nothing.
- **Nothing staged from `.loops/`** — per-commit `--name-only` across all four commits
  lists 23 files, none under `.loops/` and none matching `*.jsonl`/`*.log`. Working tree
  clean. Verified from git's bytes, not the worktree.

## Item 6 — docs — **PASS**

Every surviving `body.t` mention is a statement *that it was dropped*, never a live field
spec. Full set, from `grep -rn` over `docs/architecture/arrival/`:

- `index.html:351` — "Wire v1 is pinned — `body.t` dropped, …"
- `wire-format.html:73` — "…`body.t` is dropped, the tick `observer` is the …"
- `wire-format.html:198` — "A body carrying the retired `t` field is refused by the
  ordinary unknown-field rule"
- `wire-format.html:263,267` — the seams callout: "The duplicated discriminator DROPPED"
  and "The legacy line codec keeps its own `t`" (legacy-codec context, permitted)
- the only other hit is `body.technical-document` in vendored CSS — a selector.

**`protocol.html` §06 states the ruled law.** The false sentence ("A signed fact can
therefore move between custody lineages without fabricating a new author signature",
attached to the outer signature) is gone. The replacement names the outer signature "the
arrival-content signature, and it is per-lineage … minted only in the lineage where the
record first arrived", and adds a paragraph titled "The signature that travels through
re-custody is the inner one", explaining that merge drops the outer signature rather than
re-minting it. Cites ruling 5.

**`wire-format.html`:** the `fact`, `batch` and `tick` body-profile prose no longer lists
`t`; the worked example JSON at :410 drops its `"t": "fact"` line; the envelope table's
`observer` row now spells the per-kind semantics (author-and-key-selector for
fact/batch, custodian for tick, founding/introducing identity for genesis/key); the batch
profile gains the same-observer rule; the tick profile states the name "lives here, in
the body, where it is data. It is not the record's `observer`." The seams callout
(:240-254) is rewritten from `is-warning` "ruled" to plain "ruled and closed", covering
all three rulings and the deliberate tick-signature deferral. **Status flipped**: badge
line went from "Branch-compatible envelope / 26 August 2026" to "Pinned — seams ruled and
executed / 29 August 2026".

`index.html` also moved the closed sub-ruling out of "Requires a later ruling" and
replaced it with the deferred tick outer signatures. `backend-contract.html` has zero
`t`/tick-observer mentions — nothing to change. All five arrival HTML files parse with
balanced tags (0 errors, 0 unclosed) under a stack-checking `HTMLParser` pass.

## Item 7 — the two beyond-brief items, verified — **PASS** (with finding GF-2)

**(a) Unminted-log refusal path.** The test exists and pins the promised message on the
tick path:

```python
with pytest.raises(GenesisRefused, match="mint a genesis first"):
    store.append_tick(Tick(name="pulse", ...))
```

`test_a_tick_on_an_unminted_log_still_refuses_with_the_mint_first_message` PASSED, and
the pre-existing fact-path test `test_an_unminted_log_opens_empty_and_refuses_appends`
still PASSES. `ArrivalStore._custodian` catches the raw `GenesisRefused("… does not
exist")` and re-raises with the mint-first wording, so reading the genesis for the tick
label did not quietly falsify the class docstring's promise for one row class. Real
obligation, correctly discharged.

**(b) Rule 18 registration — coverage proven by mutation, both directions run.**

- Removing `"libs/engine/src/engine/arrival_body.py"` from `_SCAN_TARGETS` → **34
  passed**, nothing fails. `_SCAN_TARGETS` is a hand-maintained tuple with no
  completeness assertion, so the "joins at birth" trigger is comment-enforced. That is a
  pre-existing property of the rule, not something slice 1 introduced (see GF-2).
- With the entry present, seeding a denied token into `arrival_body.py` → **the rule
  fires**, naming the file and line:

```
E  AssertionError: The arrival surface names vocabulary the arrival model retired …
E      libs/engine/src/engine/arrival_body.py:103: 'receipt_order' — ordering is by
       ordinal, not by an order concept
FAILED test_rule_18_arrival_vocabulary_denylist.py::test_the_arrival_surface_never_names_the_denied_vocabulary
1 failed, 33 passed
```

So the registration is real coverage, not a decorative list entry. Both mutations
restored; `git diff` empty after each.

## Item 8 — derived-projection byte-identity tripwire — **PASS**

`test_the_derived_log_line_is_unchanged_by_the_drop` is parametrized over **fact** and
**tick**, and `test_the_derived_log_line_for_a_batch_is_unchanged_by_the_drop` covers
**batch** — all three, as the oracle requires. Each asserts byte equality against the
legacy encoder:

```python
restored = legacy_object_of_body(k, body_encode(row))
assert serialize_object(restored) == serialize_object(legacy_encode(row))
```

All 3 PASSED. The baseline is trustworthy because the legacy encoder is semantically
unchanged from main (item 5). `legacy_object_of_body` validates as an arrival body FIRST,
so a malformed body cannot be laundered into a well-formed line by acquiring a
discriminator — pinned by `test_restoring_a_malformed_body_refuses_rather_than_laundering_it`.

---

## Findings

### GF-1 (NON-BLOCKING, test-strength / docstring honesty) — the byte-stability test's docstring claims more than the assertion pins

`test_encode_decode_encode_is_byte_stable` documents itself as "asserted on BYTES rather
than on dict equality — **key order** and JSON spelling are part of what a wire format
promises". It then serializes with `sort_keys=True`, which normalizes key order away. The
assertion is therefore canonical-form byte equality, which is *slightly* stronger than
dict equality (it would catch a `1` vs `1.0` drift) but does **not** pin encoder key
order.

No correctness gap behind it: the arrival body is hashed through JCS (`rfc8785.dumps`),
which sorts keys, so encoder key order carries no wire weight and `sort_keys=True` is the
honest canonical form to compare under. The finding is that the docstring names a
property the test does not check — a future reader trusting it would think key order is
ratcheted when it is not. Fix is one sentence in the docstring, not a code change.

### GF-2 (NON-BLOCKING, ratchet design, pre-existing, matters to slice 2+) — Rule 18's `_SCAN_TARGETS` has no completeness assertion

Proven by mutation in item 7b: deleting a target from the tuple fails nothing. The
rule's own stated trigger — "a module born on the arrival surface joins `_SCAN_TARGETS`
at birth" — lives in a comment and depends on implementer vigilance. Slice 1 honored it
correctly and unprompted, so this is not a slice-1 defect; but the arc has five more
slices, each likely to add arrival-surface modules, and an unregistered module is
silently unscanned rather than loudly missing.

Directly the "ratchet test" pattern: the invariant is enumerable (glob `libs/engine/src/
engine/arrival_*.py` and `libs/store/src/store/*` against the tuple, with a shrink-only
allowlist for deliberate non-joiners like `jsonl_codec`/`jsonl_store`). Worth raising as
arc work, not slice-1 rework.

### GF-3 (NON-BLOCKING, rationale scope — flag for slice 4) — the same-observer scoping protects legacy *reads*, but a mixed-observer batch is still refused at re-mint

The implementation report justifies keeping the rule off the line codec because adding it
"would convert any historical mixed-observer batch from a migratable record into a hard
refusal — a new failure mode introduced into migration". The scoping is the right call and
the effect is real for reading, but the claim is wider than what it buys. Demonstrated:

```
1. legacy codec WRITES a mixed-observer batch line: {"t":"batch","rows":[{"t":"fact",...
2. legacy codec READS it back fine: ['kyle', 'someone-else']
3. re-minting as an arrival batch: REFUSED -> batch rows span 2 observers ('kyle', ...
```

Migration is read *plus* re-mint, and slice 4's sidecar re-mints through `body_of_batch`
(the report says so itself). So a historical mixed-observer batch is still a hard refusal
at migration — the refusal moved from the codec to the body grammar rather than being
avoided.

This is not a defect in slice 1. Refusing is arguably the only correct outcome (an
arrival batch record's envelope observer selects a key that signs a commitment covering
every row, so such a record cannot be minted honestly), and the sub-ruling verified no
live mixed-observer batches exist — the edit ceremony assembles every row against one
observer variable. It is recorded so slice 4 designs for it deliberately (split the group
into per-observer batch records, or refuse with a migration-specific message) instead of
discovering it as a surprise, and so the report's rationale is not carried forward as a
guarantee it does not make.

## Blocking findings

**None.**

## Verdict

**GATE: PASS.**

Every oracle item passes on independent re-derivation. All nine suite counts reconcile
exactly against the implementation report; the one reported error is confirmed
pre-existing on main by identical reproduction. The NON-NEGOTIABLE holds — no preserved
inner signature is invalidated, and the signature machinery is structurally untouched
(absent from the diff). All three mutation demonstrations reproduce with the reported
failure sets, and the two mint sites are verified independent by cross-package runs
rather than taken on the report's word. The contract's non-goals are respected. The docs
pass is complete and the ruled outer-signature law is stated correctly.

The implementation report's claims were checked, not accepted; the only place its prose
runs ahead of what it delivers is GF-3's migration rationale, which is a scope-of-claim
note rather than a defect. GF-1 and GF-2 are quality notes for the arc.
