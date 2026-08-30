# Slice 4 WP2 gate report — the Transformer

**Verdict: BLOCK** — 3 blocking findings, 3 non-blocking.

Gate worktree `/Users/kaygee/Code/loops-wt/s4-wp2-gate`, branch `slice4/wp2-gate`, scoped over
`main..HEAD` = `357cd670..5f5149d9`. Protocol: `delegating-to-antigravity` §4 with the two
pipeline adaptations (scope over the committed range; gate commits land only on the pointer
branch).

The central oracle **passes**. The transformer's output is a real arrival log that engine's own
structural walk and authority walk accept, with the ordering, envelope-observer and
outer-unsigned rules all holding. The three blocking findings are all defects at the
transformer's *edges* — its default call signature, its sqlite input path, and its group
grammar under a filtering rule — not in the core mapping.

---

## Range reconciliation

Three commits, all accounted for in the worker report, no unexplained commits:

| commit | claim | verified |
|---|---|---|
| `c966d981` | P1+P2 refusal lattice collapse + compat-shim sweep | yes |
| `536f737f` | P3 `row_object_fault` parameterisation | yes, with residue (N3) |
| `5f5149d9` | WP2 transformer | yes, with B1–B3 |

Scope fence held exactly. `git diff --name-status main..HEAD` touches only `libs/migrate/**`
(8 files) and the one permitted `migrate` row in
`tests/architecture/test_rule_04_lib_dependency_dag.py`. Zero files under `libs/engine`,
`libs/store`, `libs/lang`. Working tree clean but `.tmp/`. Both new files are tracked
(`git ls-files` confirms `transform.py` and `test_transform.py`).

---

## Test re-runs (all run by the gate, not read from the report)

| suite | result | baseline | reconciles |
|---|---|---|---|
| `libs/migrate tests/architecture` | 128 passed | worker claimed 128 | yes |
| `libs/engine` | 2304 passed, 1 skipped | 2304 + 1s | yes |
| `libs/store` | 180 passed | 180 | yes |
| `libs/migrate/tests/test_quarantine.py` | 1 passed | — | yes |

**Gate-protocol note, not a WP2 finding.** The engine suite fails
`test_arrival_head_seam.py::test_the_state_root_is_redirected_for_this_suite` when run with the
brief's mandated `TMPDIR=<worktree>/.tmp`, because that path is under `$HOME` and the test
asserts `Path.home() not in state_root().parents`. With `TMPDIR` outside `$HOME` the suite is
2304 passed / 1 skipped, identical to a throwaway worktree at `main`. The 3 commits touch zero
engine files. Worth fixing in the gate protocol for future work packages, since every gate
worktree lives under `/Users/kaygee/Code/`.

---

## The central oracle — engine's grammar, not migrate's opinion of it

Built independently of the worker's tests: took the transform output, minted a real
`ArrivalLog` under the declared genesis requirements, appended every draft through the normal
`append` path, then ran engine's `walk()` and `verify_authorship()` over the result.

```
records walked: 11
key-introduction ordinals: [1, 2]
migrated ordinals: [3, 4, 5]..10
migrated records carrying an outer sig: []   (must be empty)
resolutions: [(0,'kyle',0), (1,'kyle',0), (2,'kyle',0)]
tick envelope observers:  ['kyle']
fact envelope observers:  ['alice','bob','carol']
genesis: ord=0 k=genesis observer=kyle key==custodian_public=True
```

All three sub-checks the gate was asked to make hold:

**(a) Key introductions and the authority clause.** Introductions are signed with the custodian
key via `engine.arrival.Signer`, carry `observer = custodian` on the envelope, and land at
ordinals 1..k. The ordering assumption holds under the "genesis carries the custodian key"
arrangement: `_walk_authority` registers the genesis key for the genesis observer at ordinal 0,
and `_resolve` accepts a key introduced strictly before the record's own ordinal, so the
custodian is valid at 1..k. `verify_authorship` returns exactly 3 resolutions (genesis + 2
introductions) with `introduced_ordinal=0` on each. A subsequent live record signed by an
introduced observer resolves under its key at `introduced_ordinal=1`, confirming the registry
is real and not merely well-formed.

**(b) Migrated records outer-unsigned with the ruled envelope observer.** No fact, batch or
tick record carries a `sig` key. Fact and batch envelope observers are the author echo
(`alice`, `bob`, `carol` — including `carol`, who is undeclared, per §G.3's admit-≠-believe
edge). Tick envelope observer is the custody-producer label (`kyle`, the genesis observer), per
the wire-v1 pin.

**(c) Native ticks carry the legacy envelope byte-for-byte.** The signed legacy tick's full
envelope survives verbatim in the record body — `signature: "sig-tick-2"` alongside all four
chain fields (`prev_hash`, `window_start`, `fact_cursor`, `window_hash`) — with no outer
signature. Nothing is re-derived or re-keyed.

The module docstring's security rationale (why outer-unsigned; that introductions establish the
registry for future writes and do **not** validate migrated content; that a reader assuming
otherwise has the model backwards) is present and correct, as ruled.

---

## BLOCKING findings

### B1 — `signer=None` is the default, and it manufactures drafts engine structurally refuses

`transform.py:139` makes `signer` optional with a `None` default; line 219 then emits
`sig = signer(...) if signer is not None else None`. Called without a signer — the default
call — `transform()` returns normally with **unsigned key introductions** and no refusal, no
warning, and no required argument.

Engine's verdict when the sink tries to append one:

```
AppendRejected: candidate refused: a key introduction carries no signature —
an introduction is vouched for by a key that is already valid, never
self-certifying above ordinal 0
```

This is `_placement_fault` (`arrival.py:579-585`) refusing the record outright. The failure
does not land at transform time; it lands mid-migration, **after the genesis has already been
minted**, leaving a half-built lineage. Brief ruling 6 requires each introduction to be signed
by the custodian; the signature makes producing an unsigned one the path of least resistance.

Fix direction: make `signer` a required keyword argument, or refuse in `transform()` when
introductions would be needed and no signer was supplied. The transformer should not be able to
return a sequence it knows the contract will reject.

### B2 — the sqlite path has no seam defense; `ArrivalBodyError` leaks out of `transform()`

Ruling 2 and gate check 7 both name this explicitly: a defective row must raise the migrate
family's typed refusal, "not `ArrivalBodyError`, not an assert."

The JSONL branch validates each row with `row_object_fault` before constructing a body. The
sqlite branch (`transform.py:242-294`) does not: `read_facts` hands raw sqlite values straight
into `body_of_fact_row`, whose `_validate_row` raises `ArrivalBodyError` — which escapes
`transform()` uncaught. Two probes, both against real sqlite files:

```
[FAIL] typed-wrong row (ts stored as TEXT)
       ArrivalBodyError LEAKED out of transform(): fact field 'ts' must be a number, got str
[FAIL] NULL observer
       ArrivalBodyError LEAKED out of transform(): fact field 'observer' must not be null
```

The first case is not hypothetical — `engine.arrival_body._encode`'s own docstring names it as
the motivating example: *"a fact carrying `ts="1.0"`, which sqlite's REAL affinity accepts."*
A legacy sqlite store with a text-typed timestamp column is exactly the kind of thing the
migration sidecar exists to meet.

The three seam-defense tests the worker wrote all use JSONL sources, so the sqlite half of the
seam is untested as well as undefended.

### B3 — silent regroup when a transform rule drops batch rows

Ruling 2: "The transformer NEVER regroups." Two paths violate it, both at `transform.py:508-523`:

- a legal 2-row batch line whose rule drops one row is emitted as a **`k="fact"` record**, not a
  batch;
- a batch line whose rows are *all* dropped vanishes entirely (`if not mapped_rows: continue`)
  with no entry in the exception report.

Probe with a rule that drops one row of the fixture's 2-row alice batch:

```
draft kinds: ['key','key','fact','fact','fact','fact','fact','fact','tick','tick']
batch records remaining: 0
```

Engine has an explicit opinion here. `body_of_batch`'s docstring: *"A single row does NOT
collapse to a fact body here: the caller that has one row is already choosing `k="fact"` for the
envelope, and a collapse would be this module deciding a record's kind behind it."* The
transformer does precisely what engine refused to do, on the transformer's own authority.

Dead under the two shipped rules (`identity()` and `ulid_migration()` never return `None`), but
`Transform.map_fact` documents "or None to drop it" as part of its contract, so the path is
reachable by design and load-bearing for any future filtering rule. The brief's terms are
"deviations are reportable, not decidable" — this decision was made silently and appears nowhere
in the worker report. The refusal-vs-collapse question is a design call, not the worker's.

---

## Non-blocking findings

### N1 — the batch grammar is now implemented three times, in the same commit series that was ruled to stop that

P3's stated purpose was "delete the second implementation. Two implementations of one grammar
drift (that is exactly how WP1's B3 happened)." P3 did remove inventory's hand-rolled *field*
validator. WP2 then added a fresh copy of the surrounding *batch* grammar to `transform.py`.

Normalised line comparison of `inventory.py`'s batch block against `transform.py:400-490`:

```
inventory block lines: 107   transform block lines: 82
identical normalised lines shared: 59
share of transform block that is verbatim inventory: 72%
```

The duplicated logic is the whole batch-envelope grammar: unknown-field check, `rows`-is-a-list
check, `_MIN_BATCH_ROWS` check with its identical error prose, nested-batch refusal,
tick-in-batch refusal, discriminator check, duplicate-id check, and the absent/mixed observer
classification. The two copies differ only in what they accumulate afterwards (inventory
gathers census and content hash; transform builds drafts).

The root cause is structural: deliverable 1 specifies the transformer's input as "the frozen
readers' row streams," but only the sqlite branch consumes a reader. The JSONL branch re-opens
and re-parses the source file from scratch, which is why it needs its own copy of the grammar to
do so. Consuming a shared reader — or having inventory hand forward its classified rows — would
dissolve both the duplication and the seam-defense gap in B2.

### N2 — a malformed declared key produces a draft with no migrate-family refusal

A `.vertex` observers block carrying a non-base64 key yields an introduction draft that
`transform()` returns without comment; engine refuses it only at append:

```
AppendRejected: a key introduction's body carries no well-formed key:
key is not valid base64: Only base64 data is allowed
```

Same shape as B1 and the same remedy — the transformer holds its own introduction drafts to
none of engine's structural rules, though `_key_shape_fault` is the published check. Filed
non-blocking because it fails loud at the same seam rather than silently, but it fails after
genesis just as B1 does.

### N3 — P3's residue was not swept

Deleting inventory's duplicate validator left its imports behind. `ruff check --select F401`:

```
inventory.py:23  math imported but unused
inventory.py:32  .legacy_jsonl._JCS_INT_MAX imported but unused
inventory.py:33  .legacy_jsonl._JCS_INT_MIN imported but unused
inventory.py:39  .legacy_jsonl.SIGNATURE_FIELD imported but unused
inventory.py:55  .refusals.MigrationRefused imported but unused    (P1 residue)
transform.py:63  typing.TYPE_CHECKING imported but unused
```

Six dead imports, five of them the trail of P1/P2/P3. `ruff` is not a CI gate for `libs/migrate`
(CI lints only `libs/custody libs/sign`), so nothing else will catch these. WP1 already carried
15 `E501`; WP2 adds 4 more plus one `SIM108`.

---

## Checks that passed

**P1/P2 (verified).** `refusals.py` now carries exactly `MigrationRefused` (family root) and one
concrete `LegacySourceRefused`. The dead subclasses are gone from the entire repo — grep for
`MixedObserverBatchRefused|AbsentObserverBatchRefused` across `libs/ tests/ apps/` returns
nothing. The constructor is keyword-only with one tuple shape; no `len()`-based normalisation
survives anywhere in the file; no positional compat parameter.

**P3 (verified, modulo N1/N3).** `row_object_fault` carries an explicit
`skip_fields: frozenset[str] = frozenset()` parameter whose docstring cites it as a deliberate
minimal seam naming inventory batch validation as the caller. Inventory's second implementation
of the field grammar is deleted, not merely unused.

**Determinism (verified beyond the worker's check).** The full transform run twice in-process is
byte-identical. Run under four different `PYTHONHASHSEED` values (0, 1, 12345, 98765) with a
fixed keypair, the serialised draft sequence digests identically every time:
`13d00e17e64c3a26de00e13616e5966dd56b8befd1d0a2fc5ecdd9bd14d87168`. Dict and set iteration order
does not reach the draft path. (A first attempt showed four different digests; that was the
probe regenerating keypairs per run, not a defect — recorded here because the confound is easy
to repeat.)

**Rule 4 row (verified by import inventory).** The row grew to exactly `{"engine", "lang"}`. A
full import inventory of `libs/migrate/src` shows `engine.arrival`, `engine.arrival_body`,
`engine.arrival_contract`, and `lang` as the only first-party lib imports; `store` is correctly
absent. `ulid` is a third-party dependency, not a lib row. The quarantine ratchet passes; the
three grep hits for forbidden module names are docstring provenance lines ("Historical artifact
copied from …"), pre-existing on `main` from WP1, not imports.

**Break/restore proofs, two hand-verified by the gate.**

*Proof 1 (byte-preservation).* Made the transformer re-serialize payload text with
`json.dumps(json.loads(...), indent=2)`:

```
>       assert uuid4_signed.body["payload"] == FACT_UUID4_SIGNED["payload"]
E       assert '{\n  "text": "fact 1"\n}' == '{"text":"fact 1"}'
FAILED test_signature_byte_preservation_and_honest_absence[jsonl]
1 failed, 1 passed, 9 deselected
```
Restored → `2 passed`. Production diff empty.

*Proof 3 (authority ordering).* Reordered the returned sequence so migrated records precede the
introductions:

```
>       assert draft_alice.kind == KEY_INTRODUCTION_KIND
E       AssertionError: assert 'fact' == 'key'
FAILED test_key_introduction_ordering_and_authority_validity
1 failed, 10 deselected
```
Restored → `1 passed`. Production diff empty.

Both go red on the real defect and green on restore, which calibrates the worker's table of
five. Worth noting the worker's proof-3 arm is stronger than it needed to be: its ordering test
does not stop at draft order but materialises a real `ArrivalLog` and runs `verify_authorship`
over it, so it is a genuine engine-grammar oracle rather than a self-assertion.

---

## Summary

The transformer's core is correct and independently verified against engine's own grammar: the
mapping, the ordering, the authority clause, the outer-unsigned rule, the wire-v1 envelope
observers, byte-preservation of inner signatures, native tick conversion with verbatim envelope
bytes, and determinism including under varied hash seeds. Both §G.3 exception edges behave as
ruled, and the scope fence and Rule-4 row are exact.

What blocks is the perimeter. The default call signature emits structurally invalid
introductions (B1); the sqlite input path has no seam defense and leaks `ArrivalBodyError`
(B2); and the group grammar silently regroups under a filtering rule, deciding a question engine
explicitly declined to decide for its callers (B3). B2 and N1 share a root — the JSONL branch
re-parses the source instead of consuming a frozen reader, which is both why the grammar is
duplicated a third time and why the sqlite half of the seam went undefended. Addressing that
structurally would likely resolve both.

---

# Round 2 — fix round 1 re-check (`9c1a9372`)

**Verdict: BLOCK** — every ruled re-check passes and all four round-1 findings are genuinely
fixed, but scrutiny of the consolidation itself surfaced 2 new blocking defects and 2
non-blocking ones.

Merged `9c1a9372` into `slice4/wp2-gate` at `3abc1278`; the round-1 report commit `542c4ba3`
stays reachable. Engine-suite runs used `TMPDIR=/private/tmp/s4wp2-gate-tmp` per the round-1
protocol note; the sandbox permits it, so nothing was skipped.

## Scope

Exactly one commit. Eight files, all under `libs/migrate/**`. `tests/architecture/` untouched
(`git diff 5f5149d9..HEAD -- tests/architecture/` is empty), so the Rule-4 row is unchanged —
and still true: `legacy_source.py` has **zero** cross-lib imports, and the only `engine`/`lang`
imports in the package remain in `transform.py`. Working tree clean but `.tmp/`.

| suite | result | reconciles |
|---|---|---|
| `libs/migrate tests/architecture` | 138 passed (was 128) | yes |
| `libs/engine` | 2304 passed, 1 skipped | yes |
| `libs/store` | 180 passed | yes |
| `tests/architecture` + quarantine ratchet | 100 passed | yes |

## Ruled re-checks — all pass

**F4, signer required.** `transform()` without a signer now raises
`TypeError: missing 1 required keyword-only argument: 'signer'` at the call site;
`inspect.signature` confirms `KEYWORD_ONLY` with no default. Zero unsigned introductions are
constructible on the happy path.

**B2, sqlite seam (as filed).** Both probes that originally failed now return the typed
migrate-family refusal:

```
ts-as-TEXT    -> LegacySourceRefused: line 1: fact field 'ts' must be a finite number,
                 got 'not-a-number'
NULL observer -> LegacySourceRefused: line 1: 1 row(s) missing 'observer' field
```

**F3, drop semantics.** Partial-batch drop raises
`BatchRegroupRefused: Transform rule 'drop-one' dropped 1 of 2 rows in batch at line 6 …
(refuse-not-split)`. Whole-unit drop yields
`DroppedUnit(coordinate=6, kind='batch', rule='drop-whole')` — source coordinate, kind and rule
name all present. The collapse code is gone: `len(mapped_rows) == 1` no longer appears in
`transform.py`.

**Reviewer B1, empty-observer cohort.** A sqlite store with rows at rowids 1, 3 (`observer=''`)
and 4 (`observer=NULL`), plus a legitimate alice row at rowid 2, is refused by **`inventory`
before transform** and by `transform`, enumerating exactly `[1, 3, 4]`. The two spellings stay
distinct in the census — `{1: {'empty': 1}, 3: {'empty': 1}, 4: {'missing': 1}}` — and render
distinctly in the message (`1 row(s) with observer='' (empty string)` vs
`1 row(s) missing 'observer' field`). No re-attribution path exists: the `if fr.observer:`
census guards are gone from both modules and `transform` adds the observer unconditionally.

**Central oracle, re-run end-to-end on the post-refactor transformer.** Drafts → real
`ArrivalLog` → engine `walk()` + `verify_authorship()`:

```
records: 11   intro ordinals: [1, 2]   migrated: 3..10
migrated with outer sig: []
resolutions: [(0,'kyle',0), (1,'kyle',0), (2,'kyle',0)]
tick envelope observers: ['kyle']   fact envelope observers: ['alice','bob','carol']
signed legacy tick body preserved verbatim, signature "sig-tick-2" + all four chain fields
```

Unchanged from round 1 — the refactor did not disturb the authority walk, the envelope
observers, or byte-preservation.

**Grammar duplication collapsed.** Round 1 measured 59 of 82 normalised lines shared between
`inventory.py` and `transform.py`. Both consumers now contain **zero** grammar markers — no
`_MIN_BATCH_ROWS`, no `row_object_fault(`, no nested-batch or tick-in-batch refusal, no
`present_observers`. They survive only in `legacy_source.py` (the single shared layer) and
`legacy_jsonl.py` (the deliberately frozen historical artifact). The consolidation is real.

**Determinism.** Byte-identical in-process, and identical across four `PYTHONHASHSEED` values
(0, 1, 12345, 98765): `ed75651d0f81ee30091b362ea4ca08097271dcc647dcabf3615110517fa3ba3e`. The
rebuilt iteration paths introduce no hash-order dependence.

**Inventory parity vs pre-fix.** The first comparison was confounded — `_fixtures.py` changed in
this commit, so both hashes moved. Re-run controlled, building the fixtures **once** from a
worktree at `5f5149d9` and running both versions' `inventory()` over the *same bytes*: every
field is byte-identical on both arms, `content_hash` and `file_hash` included
(`0ad1bac69dd94f241c01c30fba946c8858977b5555b7a3a67151f7271a5aaa7b`). WP1's landed semantics are
preserved exactly.

**Break/restore proofs, both hand-verified.**

*F3* — restored the batch→fact collapse in place of the refusal:
`Failed: DID NOT RAISE BatchRegroupRefused` → `test_partial_batch_drop_refused` red; restored →
green; production diff empty.

*F2* — removed the `== ""` clause from all three empty-observer sites so an empty string counts
as a real observer: `Failed: DID NOT RAISE LegacySourceRefused`, taking down both
`test_sqlite_empty_observer_refuses_and_enumerates_rowids_distinct` and
`test_sqlite_seam_defense_refuses_empty_observer`; restored → 2 passed; production diff empty.

---

## BLOCKING (new, found in the fix itself)

### R2-B1 — the sqlite arm re-implements the grammar by hand, and has already diverged; `ArrivalBodyError` still escapes

`legacy_source.py` puts the JSONL grammar in one place, but its **sqlite arm does not use it**.
Lines 410–422 and 462–487 are a hand-written field validator that never calls
`row_object_fault`. It has already drifted on a real check: `row_object_fault` enforces the JCS
safe-integer domain (`_JCS_INT_MIN`/`_JCS_INT_MAX`); the sqlite arm checks only
`math.isfinite`.

Probe — a sqlite store with an `INTEGER`-affinity `ts` column holding `2**60`:

```
transform -> ArrivalBodyError LEAKED: fact field 'ts' is outside the JCS safe-integer
             domain: 1152921504606846976
inventory -> NO refusal; returns SourceInventory(total_rows=1, observer_census={'alice': 1}, …)
```

Two things are wrong. First, the new module's own docstring states: *"No raw exceptions
(`ArrivalBodyError`, `JsonlCodecError`, `KeyError`, `TypeError`) escape the public
inventory/transform surfaces."* That claim is false as written. Second — and worse for the
consolidation's premise — `inventory` **accepts** a source that `transform` then crashes on. One
shared stream layer producing two different verdicts for the same input is exactly the
divergence the consolidation was sold on eliminating.

Narrow in practice: real legacy stores declare `ts REAL`, and REAL affinity coerces to float,
where `isfinite` and the body check agree. But the frozen reader is deliberately era-aware about
schema and the sidecar exists to meet stores it did not create. Round-1 N1 said the grammar
should exist once; it now exists once *for JSONL* and a second time, by hand, for sqlite.

Fix is small: route the sqlite arm's field checks through `row_object_fault` (frame `"row"`,
`skip_fields={"observer"}`) as the JSONL arm does, or — if the two arms must stay separate —
narrow the docstring claim to what the code actually guarantees.

### R2-B2 — P2's ruled compat-shim sweep has regressed

Round 1 verified: *"no `len()`-based normalisation survives anywhere in the file."* It is back,
in `refusals.py`:

```python
absent_observer_lines: tuple[Any, ...] | list[Any] = (),
absent_observer_spellings: dict[int, dict[str, int]] | None = None,
...
obs = tuple(str(o) for o in item[2]) if len(item) > 2 else ()
if len(item) > 3 and isinstance(item[3], dict):
    spellings[lineno] = item[3]
```

`LegacySourceRefused` now accepts 2-, 3- and 4-element tuples with `len()` dispatch, plus a
parallel `absent_observer_spellings` parameter that does the same job by another route, under a
`tuple[Any, ...]` annotation that gives up the shape entirely. This is P2's exact wording —
*"constructors currently accept old and new tuple shapes with len-based normalisation and a
positional compat parameter — a package days old with no external callers. One constructor, one
tuple shape."*

Both production call sites (`legacy_source.py:368` and `:513`) pass 4-tuples.
`absent_observer_spellings` is passed by **nobody**. The only callers of the 3-tuple arm are the
tests: `test_refusals.py:53` and `:74` still pass 3-tuples.

That is what makes this more than hygiene. The shim was added so un-updated tests would keep
passing, which means `test_refusals.py` now exercises a constructor shape production never
produces — and the spelling data that is the entire substance of the reviewer-B1 fix is
untested at the constructor level. Fix: update the two test call sites to 4-tuples, delete the
`len()` arms, the dead parameter, and the `Any` annotation.

---

## Non-blocking

### R2-N1 — `_key_shape_fault` is a private engine symbol crossing the lib boundary

`transform.py:67` imports `_key_shape_fault` from `engine.arrival`. It is underscore-prefixed
and absent from engine's `__all__`. Rule 4 governs lib-level dependencies, not symbol privacy,
so nothing catches this. F5's requirement is right and reusing engine's own shape check is the
right instinct — but it should be reached through a public surface, or engine should export it.
Flagged rather than fixed since promoting an engine symbol is outside the WP2 fence.

### R2-N2 — the residue sweep (F6) went backwards on line length

| check | pre-fix `5f5149d9` | HEAD | |
|---|---|---|---|
| `F401` unused import | 6 | 4 | improved |
| `E501` line-too-long | 19 | 36 | **worse** |
| `SIM108` | 1 | 0 | fixed |

Four dead imports remain — `LegacySourceRefused` and `MigrationRefused` are now unused in *both*
`inventory.py` and `transform.py` (`transform.py` still lists both in its refusals import block
while raising neither). `ruff` is not a CI gate for `libs/migrate`, so nothing else will catch
them.

---

## Disposition

Round-1 `s4wp2-signer-none-unsigned-introductions`, `s4wp2-sqlite-seam-arrivalbodyerror-leak`,
`s4wp2-silent-regroup-batch-collapse` and the reviewer's `s4wp2-empty-observer-cohort-unmigratable`
are all **fixed** at `9c1a9372`, each verified by the probe that originally failed. The
consolidation is a genuine structural improvement: the grammar duplication is gone, WP1's
inventory semantics are preserved byte-for-byte, and the central oracle still passes end-to-end.

What blocks is narrow and cheap. R2-B1 is the round-1 N1 criticism relocated rather than
dissolved — the sqlite arm kept its own copy of the grammar and has already diverged from it on
a check that matters, producing both an uncaught `ArrivalBodyError` and an
inventory/transform disagreement. R2-B2 is a ruled cleanup regressing, with tests pinned to a
shape production does not use. Neither is a redesign; both are contained edits inside
`libs/migrate`.

---

# Round 3 — fix round 2 re-check (`5a531574`)

**Verdict: BLOCK** — both R2 findings are fully fixed and every ruled re-check passes, but the
R2-B1 fix over-corrected and made an entire era of legacy SQLite store unmigratable. One
regression, one line to fix.

Merged `5a531574` at `c1e4e4a9`. Scope exact: one commit, eight files, **zero** outside
`libs/migrate/**`. Suites: `libs/migrate tests/architecture` 141 passed, `tests/architecture` +
quarantine 100 passed, `libs/engine` 2304 passed / 1 skipped, `libs/store` 180 passed. Working
tree clean.

## Ruled re-checks — all pass

**(1) R2-B1, the 2**60 probe.** Both surfaces now return the typed migrate-family refusal, and
their verdicts agree:

```
transform -> LegacySourceRefused: line 1: fact field 'ts' is outside the JCS
             safe-integer domain: 1152921504606846976
inventory -> LegacySourceRefused: (identical)
verdicts AGREE: True
```

Swept six divergence cases (`ts` as TEXT, NULL observer, empty observer, `ts` NaN, payload as
INT, empty id): no `ArrivalBodyError`, no `KeyError`, and `transform` and `inventory` agree on
every one. The inventory/transform disagreement that made R2-B1 blocking is gone.

**(2) R2-B2, the refusals surface.** `len(` count in `refusals.py` is **0**;
`absent_observer_spellings` appears nowhere in the package; `typing.Any` is gone. The
constructor takes four parameters (`codec_invalid_lines`, `mixed_observer_lines`,
`absent_observer_lines`, `source`) with a precise
`tuple[tuple[int, int, tuple[str, ...], dict[str, int]], ...]` annotation, and the spelling
census now rides inside the 4-tuple rather than in a parallel dict — a cleaner shape than the
one I asked for. `test_refusals.py` exercises the production shape, including spelling
(`(20, 1, (), {"empty": 1})` and `(22, 2, (), {"missing": 1, "empty": 1})`). Live refusal
objects carry 4-tuples: `((1, 1, (), {'empty': 1}),)`.

**(3) F1 break/restore, hand-verified.** Reverted the sqlite fact arm to the old hand-rolled
`isfinite` check:

```
E  engine.arrival_body.ArrivalBodyError: fact field 'ts' is outside the JCS
   safe-integer domain: 1152921504606846976
FAILED test_inventory.py::test_sqlite_seam_defense_refuses_unsafe_integer_ts
FAILED test_transform.py::test_sqlite_seam_defense_refuses_unsafe_integer_ts
```

Red with the exact leak the finding named; restored → 2 passed; production diff empty.

**(4) Hand-validator deleted, not bypassed.** `math.isfinite`, `import math`, and the
hand-written `"must be a non-empty string, got"` messages are all gone from
`legacy_source.py`; the `:410-422` and `:462-487` blocks are replaced by `row_object_fault`
calls (5 call sites in the module).

**(5) Scope.** Rule-4 row untouched and still true — `legacy_source.py` has zero cross-lib
imports. Quarantine ratchet green. `ruff`: dead imports 4 → **0**, `E501` 36 → 23; one new
`I001` (a stray blank line where `from typing import Any` was removed).

**(6) Regression checks.** Central oracle still passes on HEAD — 11 records, introductions at
`[1, 2]`, migrated `3..10`, no outer signatures, resolutions
`[(0,'kyle',0), (1,'kyle',0), (2,'kyle',0)]`, legacy tick signature `sig-tick-2` preserved.
Determinism digest `ed75651d…` and inventory output `74cf0fe3…` both **byte-identical to round
2**.

---

## BLOCKING

### R3-B1 — the sqlite tick arm now refuses era-1 stores that migrated cleanly one commit ago

Routing the tick arm through `row_object_fault` was right, but the `obj` handed to it is built
from `_tick_columns(conn)` — which is **era-aware** and returns only the columns the store
actually has. `row_object_fault` checks for *absent* fields before it ever consults nullability:

```python
missing = [f for f in checked_fields if f not in obj]
if missing:
    return f"missing field(s) in {t} {frame}: {missing}"
```

`TICK_FIELDS` includes all four chain fields, so a ticks table predating them is refused —
even though the frozen grammar explicitly licenses them as null:
`TICK_NULLABLE = frozenset(("since", *TICK_CHAIN_FIELDS))`. Absence and null are being conflated
in the one direction the grammar says they must not be.

Same store, two commits, decisive:

```
AT 9c1a9372 (fix round 1)
  inventory: OK — total_rows=2 tick_count=1
  transform: OK — 3 drafts, tick body = {…, 'prev_hash': None, 'window_start': None,
                                          'fact_cursor': None, 'window_hash': None}

AT 5a531574 (HEAD)
  inventory: REFUSED — line 1: missing field(s) in tick row:
             ['prev_hash', 'window_start', 'fact_cursor', 'window_hash']
  transform: REFUSED — (identical)
```

One commit ago this store migrated correctly, producing exactly the tick body the grammar
intends: chain fields present and null. Now it cannot be migrated at all.

This is not a hypothetical schema. `_tick_columns` exists solely to tolerate it — *"Tick columns
present in this store, canonical order, era-aware"* — and `_content_sha256` in the same frozen
module documents hashing that stays *"stable across the column's arrival."* The frozen reader
was written knowing chain columns arrived partway through the store's history, which is the
exact population a migration sidecar exists to serve. With slice 4 gating 1.0 on all live stores
migrating, an era that refuses is blocking even though it fails loud rather than corrupting.

Fix is one line — build the tick `obj` over the full field tuple so an absent column becomes a
null field, which `TICK_NULLABLE` already permits:

```python
obj = {f: t_dict.get(f) for f in TICK_FIELDS}
if t_dict.get("signature") is not None:
    obj["signature"] = t_dict["signature"]
```

The facts arm needs no equivalent change: `FACT_FIELDS` has no nullable members, `signature` is
not in `FACT_FIELDS`, and `_facts_have_signature` already handles that column's absence. (Noted
in passing, not a finding: the facts query hardcodes the six base columns, so a store missing one
would raise `sqlite3.OperationalError` outside the migrate family — pre-existing at
`9c1a9372`, unchanged here, and out of this round's scope.)

A test belongs with the fix: an era-1 sqlite fixture whose ticks table lacks the four chain
columns, asserting it migrates to a tick body carrying explicit nulls.

---

## Disposition

`s4wp2-sqlite-arm-grammar-diverged` and `s4wp2-compat-shims-regressed` are both **fixed** at
`5a531574`, each verified by the probe that originally failed, with the hand-validator deleted
rather than bypassed and the shims genuinely gone rather than relocated. The consolidation now
has one grammar governing both arms, and every earlier property — central oracle, determinism,
inventory parity — is preserved bit-for-bit.

What blocks is the new edge the fix opened: making the sqlite arm share the JSONL grammar also
made it share a presence check that the era-aware reader cannot satisfy. The correction is
contained, one line plus a fixture, and does not disturb anything verified above.
