# Slice 4 WP1 — independent gate report

**Gate worktree:** `/Users/kaygee/Code/loops-wt/s4-wp1-gate`, branch `slice4/wp1-gate`
**Target:** `6e39d84e` — *feat(migrate): WP1 — package skeleton, frozen legacy readers, inventory pass, GF-3 refusal*
**Worker:** agy / gemini-3.7-flash-high, worktree `/Users/kaygee/Code/loops-wt/s4-wp1`, branch `slice4/wp1`
**Report under review:** `docs/scratch/arrival-break/agy-s4-wp1.log`

## VERDICT: **FAIL** — 4 blocking findings (1 pre-ruled, 3 new)

The work package is substantially correct and the worker's power-proof table is honest —
both proofs I re-ran by hand replicated exactly, scope held perfectly, and the sqlite/id
copies are byte-faithful to their origins. The three new blocking findings are all narrow
and cheap to fix; none require rearchitecting. Two of them (B2, B4) are defects the worker's
own tests actively lock in, which is why they survived its self-check.

---

## 1. Scope and provenance

| Check | Result |
| --- | --- |
| Gate worktree at slice tip | PASS — `6e39d84e`, clean tree |
| `git log main..HEAD` | PASS — exactly one commit, `6e39d84e`, matching the report |
| Committed range vs. brief's scope fence | PASS — all 16 files inside the fence |
| Worker worktree `git status --short` | PASS — only `?? .tmp/` |
| Production diff empty after proofs | PASS |
| Tracked-ness of every reported file | PASS — 13/13 under `git ls-files`; no gitignored-but-reported file. No `.jsonl` is committed (fixtures are built at runtime by `tests/_fixtures.py`), so the root `*.jsonl` ignore is not implicated |

**Scope verdict: clean.** The worker stayed inside the fence exactly, including declining
the tempting Rule 11 edit and reporting it instead (its §5). That is the escape valve
working as designed.

## 2. Acceptance re-run (not read — run)

```
$ uv run pytest libs/migrate tests/architecture -q
1 failed, 112 passed in 5.71s
FAILED tests/architecture/test_rule_11_record_never_imports_surfacing.py::test_every_lib_declares_a_layer
```

The single failure is the pre-ruled Rule 11 layer row (**B1**). No other failure. With
`"migrate": "record"` applied, the same command is **113 passed** — see B1 for the verified
prescription.

**Count reconciliation** (the worker's neighbouring-suite claims):

| Suite | Result |
| --- | --- |
| `libs/migrate` | 14 passed — matches the worker's `16 passed` for migrate + 2 arch rule files |
| `libs/store` | 180 passed |
| `libs/engine` | 2303 passed, 1 skipped, 1 failed |

The one engine failure is `test_arrival_head_seam.py::test_the_state_root_is_redirected_for_this_suite`,
and it is **not** attributable to this change: it reproduces identically on the untouched
`main` checkout under the same `TMPDIR` override, because the test asserts `state_root()`
against `tmp_path` and an exported `TMPDIR` relocates pytest's basetemp out from under it.
Environmental, pre-existing.

Note for future gate runs: the neighbouring suites cannot be collected from the workspace
root (`ModuleNotFoundError: hypothesis` — the root `dependency-groups.dev` omits it, the
per-lib ones carry it), and `pytest libs/store libs/engine` together raises
`ImportPathMismatchError` between the two `tests/conftest.py` files. Both are pre-existing;
run each lib with `uv run --directory libs/<name> pytest`.

## 3. Power proofs verified by hand

Two of the worker's five, re-run from scratch against the committed state:

**Proof 1 — remove the mixed-observer check from `inventory.py`:**
```
E       Failed: DID NOT RAISE MixedObserverBatchRefused
FAILED ...::test_mixed_observer_batch_refuses_and_enumerates_every_offending_line
1 failed, 7 passed
# after git restore:
8 passed in 0.03s
```

**Proof 4 — Rule 4 outward quarantine, `import migrate` added to `libs/engine/src/engine/__init__.py`:**
```
E       assert not ['  libs/engine/src/engine/__init__.py:1 — engine imports migrate at runtime']
FAILED tests/architecture/test_rule_04_lib_dependency_dag.py::test_lib_dependency_dag
# after git restore:
1 passed in 0.21s
```

Both replicate the worker's pasted output. The table is calibrated; I have no reason to
doubt proofs 2, 3 and 5. Tree clean after both (`?? .tmp/` only).

## 4. Frozen-copy fidelity

Compared each copied function against its origin by AST (docstrings stripped, so only code
structure is compared):

| Copy | Origin | Result |
| --- | --- | --- |
| `legacy_sqlite.py` | `store/rebirth.py` | `_chain_head`, `_content_sha256`, `_facts_have_signature`, `_tick_columns` — **all identical** |
| `legacy_ids.py` | `store/rebirth.py` | `is_ulid`, `deterministic_ulid`, `identity`, `ulid_migration`, `map_fact` — **all identical** |
| `legacy_jsonl.py` | `engine/jsonl_codec.py` | 8 of 10 identical; `deserialize_records` differs only by the `_load`→`load_line` rename (benign, the copy aliases `_load = load_line`); **`_validate_batch` diverges semantically — see B3** |

All 11 encode-path functions were dropped, which is the reading-only trim the brief asked
for. Copied-at commit `affe92a6` is cited in all three module docstrings and is correct
(the brief commit, parent of the worker's).

**Import-edge quarantine:** `grep` over `libs/migrate/src/` finds exactly one live cross-lib
import — `from engine import tick_row_hash` at `legacy_sqlite.py:99`, inside `_chain_head`,
which the origin `rebirth.py` also does. No `engine.jsonl_codec`, no `engine.jsonl_store`,
no `store.rebirth`, no `store._conn`, and **no arrival codec import** (`arrival_body` and
friends are absent from `src/` entirely; `test_refusals.py` imports `ArrivalBodyError` only
to assert non-inheritance, which is legitimate). See N2 and N3 for what this edge costs.

## 5. GF-3 refusal contract

| Requirement | Result |
| --- | --- |
| Own exception root, not under `ArrivalBodyError` | PASS — `MigrationRefused(Exception)`, asserted in `test_refusals.py:23-25` |
| Not under `ContractRefusal` | PASS |
| Structured `(line, observers)` for every offending line | PASS for the mixed-only case — **fails across conditions, see B2** |
| Absent observer is a distinct condition, `None` never folded into the observer set | PASS on the folding — `AbsentObserverBatchRefused` is a separate type and `None` never enters the set. **Fails on "reported", see B2** |
| No config flag disables the refusal | PASS — no flag exists anywhere in the module |
| Type name and docstring carry no remedy | PASS — both are location claims; advisory prose appears only in the message |
| Decision matches `engine/arrival_body.py:241-266` | PASS on semantics — decided on row-body `observer` fields, refusing when the set exceeds one |

## 6. Read-only guarantee

**PASS, and genuinely proven.** `test_inventory_is_strictly_read_only` (`test_inventory.py:137-147`)
compares real SHA-256 digests of the source bytes before and after every `inventory()` call,
across both formats, and additionally asserts the reported `file_hash` equals the pre-call
digest. `test_mixed_observer_batch_refuses...` also asserts `set(tmp_path.iterdir())` is
unchanged across the refusal, so the no-path-created claim is real. sqlite is opened
`file:...?mode=ro` via URI. No write or create path exists in the inventory modules.
(The companion `test_inventory_module_contains_no_write_calls` is weak — see N6 — but the
digest test is the one that carries the guarantee, and it is sound.)

## 7. Root pyproject registration

**PASS — all three surfaces mirrored**, verified against how `libs/store` is registered:
`[tool.hatch.build] only-include` (line 43), `[tool.hatch.build.targets.wheel] packages`
(line 58), `[tool.uv.workspace] members` (line 84). `libs/migrate/pyproject.toml` mirrors
`libs/store/pyproject.toml`'s shape exactly, differing only in name, description, the
`store`/`lang` workspace deps, and the package paths.

---

## BLOCKING FINDINGS

### B1 — Rule 11: `migrate` declares no layer *(pre-ruled by the arbiter)*

`tests/architecture/test_rule_11_record_never_imports_surfacing.py:46`

```
AssertionError: Lib without a layer assignment: migrate
```

Pre-ruled: `migrate` is the **record** layer. Correctly left alone by the worker (out of
fence), correctly reported in its §5.

**Prescribed edit — corrected.** The arbiter's prescription named
`docs/dev/ARCHITECTURE.md`; **that file does not exist in this repo** (the only
`ARCHITECTURE.md` is `docs/libs/sdk/ARCHITECTURE.md`, which has no Layers table, and no
Layers table exists anywhere under `docs/`). The complete and sufficient fix is one line, in
`tests/architecture/test_rule_11_record_never_imports_surfacing.py`, in `_LIB_LAYER` (line 19-27):

```python
    "store": "record",
    "migrate": "record",   # <- add
```

I applied exactly this and re-ran the full acceptance: **113 passed**. No documentation edit
is needed or possible. `record` is also the correct value on the merits: migrate imports only
`engine`, so Rule 11's direction check (record never imports surfacing) holds.

*(Related pre-existing residue, not this WP's to fix — N8.)*

### B2 — The absent-observer refusal preempts and silently swallows the GF-3 enumeration

`libs/migrate/src/migrate/inventory.py:219-224` and `:245-254`

Ruling 1 requires the refusal to enumerate **every** offending source line, not just the
first. It does so within the mixed-observer condition, but the absent-observer condition
short-circuits it in two ways. At line 219-221, a batch line with any observer-less row is
recorded as absent and `continue`s — it is never tested for the mixed condition. At line
245-249, `AbsentObserverBatchRefused` is raised *before* the mixed check at line 250, so if
any absent line exists anywhere in the source, the entire accumulated mixed-observer
enumeration is discarded unreported.

Probe, run against the committed implementation:

```
PROBE 1: source has 1 absent-observer line (line 1) and 2 mixed-observer lines (lines 2,3)
raised AbsentObserverBatchRefused, lines: ((1, ('alice',)),)
>>> mixed-observer lines 2 and 3 are NOT reported anywhere in this refusal

PROBE 1b: line 1 has a row with no observer AND rows from alice + bob (2 observers)
raised AbsentObserverBatchRefused: ((1, ('alice', 'bob')),)
>>> the mixed-observer condition on this same line is never surfaced
```

Probe 1b is the sharper half: the two observers are carried in the *absent* exception's
data, where the message renders them as `(found observers: 'alice', 'bob')` — so a
genuine GF-3 violation is reported to the operator as a missing-field problem.

This is exactly the failure the enumerate-everything ruling exists to prevent: the operator
repairs the absent line, re-runs, and only then discovers the mixed lines. The existing test
never catches it because `build_absent_observer_jsonl` and `build_mixed_observer_jsonl`
construct sources containing only one condition each.

**Fix direction:** accumulate both condition lists over the full scan and report both — either
by raising a refusal that carries both, or by making the two conditions co-reported rather
than sequenced. A per-line check should also record both conditions when both hold. Add a
fixture holding both conditions in one source, and one line holding both.

### B3 — Uncited semantic divergence in the "verbatim" frozen copy

`libs/migrate/src/migrate/legacy_jsonl.py:222-226` vs `libs/engine/src/engine/jsonl_codec.py`

The copy weakens the batch duplicate-id check:

```python
# origin (jsonl_codec.py)          # copy (legacy_jsonl.py)
row_id = elem["id"]                row_id = elem.get("id")
if row_id in seen_ids:             if row_id in seen_ids:
    raise JsonlCodecError(...)         raise JsonlCodecError(...)
seen_ids.add(row_id)               if row_id is not None:
                                       seen_ids.add(row_id)
```

The origin raises `KeyError` on an id-less row; the copy tolerates it and drops it from the
duplicate set, so two rows both missing `id` no longer trip the duplicate check. Today this
is **unreachable** — `_validate` runs earlier in the same loop under the default
`validate_rows=True` and rejects a missing `id` first — so there is no live bug. It is
blocking anyway on the ruling-3 contract: the module's docstring presents itself as a frozen
historical artifact, the brief permits only reading-only trims that are cited in docstrings,
and this is neither a trim nor cited. The entire value of a frozen copy is that it is *known*
to equal the legacy grammar; an uncited divergence that is unreachable today is precisely what
becomes a live bug when WP2/WP3 build on it.

**Fix direction:** restore `elem["id"]` and the unconditional `seen_ids.add(row_id)`. One line
each. (Or, if the defensive form is genuinely wanted, cite the deviation and its rationale in
the module docstring — but the frozen-copy contract argues for restoring.)

### B4 — `classify_id_era` labels every non-ULID string `"uuid4"`, and a test enshrines it

`libs/migrate/src/migrate/legacy_ids.py:123-129`, `libs/migrate/tests/test_legacy_readers.py:46`

The classifier tests for canonical ULID, then lowercase ULID, then **falls through to
`"uuid4"` for everything else**:

```
  '01ARZ3NDEKTSV4RRFFQ69G5FAV'                  -> canonical-ulid
  '01arz3ndektsv4rrffq69g5fav'                  -> lowercase-ulid
  'c56a4180-65aa-42ec-a945-5fd21dec0538'        -> uuid4
  ''                                            -> uuid4
  'not-an-id-at-all'                            -> uuid4
  '☃ garbage'                                   -> uuid4
  '01ARZ3NDEKTSV4RRFFQ69G5FA!'                  -> uuid4
```

`id_era_census` is forensic evidence an operator uses to decide a migration, and a truncated,
corrupt, or future-era id is silently counted as a member of a named historical era. The
function can only support a location claim ("this is not a canonical or lowercase ULID"); it
makes a verdict claim ("this is a uuid4-era id"). This is the scope-the-claim rule —
`decision:practice/scope-the-claim-over-widen-the-detection` — with the detector overreaching
into a verdict.

`test_legacy_readers.py:46` locks the defect in: `assert classify_id_era("01A") == "uuid4"`
asserts that a three-character string is a uuid4-era id. That is why the worker's own suite
did not surface it.

Note this does **not** endanger the transform: `ulid_migration` rewrites anything failing
`is_ulid`, uniformly, so garbage ids are migrated correctly regardless. The defect is confined
to the census's reported claim.

**Fix direction:** add an explicit era bucket for the unclassifiable (`"unclassified"` /
`"other"`), match uuid4 positively on its actual shape, and correct the test. Also worth
noting: `classify_id_era` is **new code** (it has no counterpart in `rebirth.py`) living in a
module that presents itself as frozen and verbatim — it should be marked as such so a later
reader does not mistake it for legacy knowledge.

---

## NON-BLOCKING FINDINGS

### N1 — The content hash cannot witness batch grouping *(design escalation)*

The jsonl arm hashes each batch row exactly as it hashes a standalone fact row
(`inventory.py:229-232` vs `:186-188`), so batch structure leaves no trace in the digest:

```
batched: total_lines=1 batch_line_count=1
flat   : total_lines=2 batch_line_count=0
batched content_hash = 5631c4d6...84969a42
flat    content_hash = 5631c4d6...84969a42
IDENTICAL: True
```

This is deliberate — `test_content_hash_matches_between_equivalent_jsonl_and_sqlite`
asserts a jsonl source with a 2-row batch has the same content hash as the equivalent flat
sqlite store, and cross-format equivalence is genuinely useful. But it collides with the
ruling this WP exists to protect: backend-contract §04 forbids the transformer rewriting one
semantic batch into several fact records or vice versa, and the content hash — documented as
"the VERIFIABLE identity of a store's contents" (`legacy_sqlite.py:66`, echoed in
`inventory.py:9`) — is blind to exactly that rewrite. `batch_line_count` carries the signal
in aggregate, but a migration that splits batch A and merges flats into batch B preserves
both the count and the hash.

Not blocking: the implementation matches the brief's wording ("witness-order row hash") and
the ordering is well-defined for jsonl (file order is witness order), so the hazard the gate
brief anticipated — an ill-defined ordering — did not materialise. **The claim is what
overreaches, not the code.** Recommend the arbiter rule on whether to narrow the documented
claim to "row-sequence identity" and, if structural fidelity needs witnessing, whether that is
a separate structure digest in WP2.

### N2 — Ruling 3's freeze has no ratchet

The forbidden-import list (`engine.jsonl_codec`, `engine.jsonl_store`, `store.rebirth`) is
enforced nowhere in the test suite — the worker ran the brief's grep once by hand, and
nothing stops WP2 from adding the import tomorrow. Rule 4 actively *permits* it: the row is
`"migrate": {"engine", "store", "lang"}`, which grants migrate the right to import
`store.rebirth`, the very module the freeze forbids. Per the ratchet test — an invariant that
lives only in review vigilance drifts — this wants an enumerable-property test asserting no
module under `libs/migrate/src/` imports the frozen origins. Cheap, and it is the arc's
central architectural claim.

Also worth noting: migrate declares runtime deps on `store` and `lang` and neither is imported
anywhere in `src/`. The Rule 4 row and the pyproject deps are both wider than the code needs.
Both were prescribed by the brief, so this is a note for the fix round, not a deviation.

### N3 — `_chain_head` is dead code carrying the copy's only live import edge

`legacy_sqlite.py:92-114` is exported and unit-tested but never called by the inventory pass,
and it holds the module's only cross-lib import: `from engine import tick_row_hash`. So the
one function that defines row identity in the "frozen" reader is the one function that is not
frozen — it tracks engine's evolution, and engine is under active change in this very arc.
Faithful to the origin (rebirth does the same), so not a fidelity defect, but the freeze has a
hole exactly where it matters most. Worth an explicit ruling in WP2 when `_chain_head` acquires
a caller: pin the hash function into the copy, or document that this reader deliberately reads
head identity through live engine.

### N4 — The two-hash distinction is only half-tested

`test_two_hash_distinction_content_hash_stable_across_vacuum` (`test_inventory.py:113-134`)
asserts the content hash is stable across VACUUM but **never asserts the file hash changed** —
its final assertion is `inv1.per_kind_counts == inv2.per_kind_counts`, which is unrelated. The
test would pass identically if `content_hash` were literally the file hash and VACUUM were a
no-op. I confirmed the premise does fire (VACUUM changes the bytes: `c2bff542…` → `5780e53d…`),
so the content-stability half is genuine evidence — but the distinction the test is named for
needs `assert inv1.file_hash != inv2.file_hash`. This item was also absent from the worker's
break/restore table, so it was never power-proven.

### N5 — Report accuracy: the pasted "final check" is narrower than the brief's

The worker's *Final Checks* pastes `16 passed` from
`pytest libs/migrate tests/architecture/test_rule_04_… tests/architecture/test_rule_07_…` —
but the brief (line 158) required `pytest libs/migrate tests/architecture`, which is red. The
worker did disclose the Rule 11 failure in its §5, so this is not concealment; but the
acceptance line as pasted is not the acceptance that was asked for, and a reader skimming the
evidence section would conclude the suite was green. Worth naming in the pipeline's worker
guidance: substituting a narrower command for the specified one needs to be flagged at the
substitution, not only in a later section.

### N6 — `test_inventory_module_contains_no_write_calls` is largely tautological

`test_inventory.py:150-161` greps the module source for literal strings, the first of which
is `assert 'open(..., "w")' not in source_code` — a literal that could never appear in real
code. `write_text` / `write_bytes` / `, "w"` do carry some signal. The brief did ask for this
assertion in these words, so the worker followed the letter; the guarantee is really carried
by the digest test (§6), which is sound. Recommend either deleting this test as ceremony or
replacing it with an AST check for write-mode `open`/`Path.write_*` calls.

### N7 — Vestigial residue in a package one commit old

Several constructs carry history the package does not have:

- `refusals.py:100-101` — `MissingObserverBatchRefused = AbsentObserverBatchRefused`,
  commented *"Alias for backward/naming symmetry"*. There is no backward. It is exported in
  `__init__.py` and locked by `test_refusals.py:20`.
- `inventory.py:62-75` — three pass-through properties (`source_content_sha256`,
  `source_file_sha256`, `per_kind_row_counts`) that only return another field, and
  `test_inventory.py:41,48-49` asserts each alias equals its target. This reads as tests
  written against one set of names and a dataclass written against another, bridged rather
  than reconciled.
- `legacy_jsonl.py:187` — the `validate_rows` knob survives, but its only false-passing caller
  was the encode path that was deleted, and the origin docstring explaining why it exists was
  trimmed away. A dead knob with its rationale removed.
- `__init__.py` publishes four underscore-private names (`_chain_head`, `_content_sha256`,
  `_facts_have_signature`, `_tick_columns`) in `__all__` — they are either public or private,
  not both.

Individually trivial; together they are the residue the dissolution rule asks to sweep in the
same change, and the cheapest moment to sweep them is now, before WP2 builds on the surface.

### N8 — Pre-existing: Rule 11's assertion message has two stale pointers *(not this WP's)*

`test_rule_11_record_never_imports_surfacing.py:49-51` tells the reader to assign the layer in
`_LIB_LAYER (tests/test_architecture.py)` — the file is now
`tests/architecture/test_rule_11_record_never_imports_surfacing.py` — **and** to "add the lib
to the Layers table in ARCHITECTURE.md", a table that does not exist anywhere in the repo.
This is what sent B1's prescription to a nonexistent path. Worth a follow-up outside this WP:
either restore the Layers table or correct the message to point at the real source of truth.

---

## Summary table

| # | Finding | Class |
| --- | --- | --- |
| B1 | Rule 11: `migrate` declares no layer (pre-ruled; prescription corrected — no ARCHITECTURE.md exists) | **BLOCKING** |
| B2 | Absent-observer refusal preempts and swallows the GF-3 mixed-observer enumeration | **BLOCKING** |
| B3 | Uncited semantic divergence in the frozen `_validate_batch` copy (duplicate-id check weakened) | **BLOCKING** |
| B4 | `classify_id_era` labels all non-ULID ids `"uuid4"`; a test enshrines it | **BLOCKING** |
| N1 | Content hash cannot witness batch grouping — claim wider than what it witnesses | non-blocking (design escalation) |
| N2 | Ruling 3's freeze has no ratchet; Rule 4 permits `store.rebirth` | non-blocking |
| N3 | `_chain_head` dead, and holds the copy's only live engine edge | non-blocking |
| N4 | Two-hash test never asserts the file hash changed | non-blocking |
| N5 | Worker's pasted final check used a narrower command than the brief's | non-blocking |
| N6 | Read-only source-grep test largely tautological (digest test carries the guarantee) | non-blocking |
| N7 | Vestigial aliases, dead knob, private names in `__all__` | non-blocking |
| N8 | Rule 11 assertion message has two stale pointers | non-blocking, pre-existing |

## What I did not verify

- Proofs 2, 3 and 5 of the worker's table were not re-run by hand (1 and 4 were, and both
  replicated exactly; the table is calibrated).
- WP2/WP3 territory — transformation to `RecordDraft`, minting, sink append — is out of scope
  and untested here, as the worker correctly stated.
- No performance or large-source behaviour was exercised; fixtures are tens of rows.
- The sqlite arm cannot exercise GF-3 at all (`batch_line_count` is hardcoded `0` at
  `inventory.py:149`), which is defensible — a sqlite store has no batch grouping — but means
  the refusal is jsonl-only by construction, and nothing tests or documents that as intended.
