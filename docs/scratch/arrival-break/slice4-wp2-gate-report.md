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
