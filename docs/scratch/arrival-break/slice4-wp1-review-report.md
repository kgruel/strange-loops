# Slice 4 WP1 — adversarial slice review

**Reviewer:** independent adversarial reviewer (not the acceptance gate)
**Under review:** `6e39d84e` "feat(migrate): WP1 — package skeleton, frozen legacy readers, inventory pass, GF-3 refusal"
**Base:** `main` = `affe92a6`
**Worktree:** `/Users/kaygee/Code/loops-wt/s4-wp1-review` (detached, read-only; probes under `.tmp/`, tracked diff empty at start and end)
**Contract:** `docs/scratch/arrival-break/slice4-wp1-brief.md`; worker report `docs/scratch/arrival-break/agy-s4-wp1.log`

Settled rulings excluded per the arbiter's do-not-re-report list (refuse-not-split, deliberate copy duplication,
Rule 11 layer assignment, package birth/Rule 4 row/Rule 7 entry existence) are not re-litigated here.

**Baseline established before probing:** `uv run pytest libs/migrate tests/architecture -q` → **112 passed, 1 failed**
(the pre-ruled `test_every_lib_declares_a_layer` Rule 11 failure only). `uv run --package migrate pytest libs/migrate/tests -q`
(the exact shape CI runs) → **14 passed**. CI's library discovery is a glob, so `migrate` auto-enrolls with no workflow edit.

---

## Summary of findings

| # | Class | Finding |
|---|---|---|
| B-1 | **BLOCKING** | GF-3 refusal decides on **unvalidated** rows — inverts `arrival_body`'s order — so structurally invalid batch lines are refused with a mixed-observer location claim that the source does not support |
| B-2 | **BLOCKING** | Uncaught `TypeError` from `inventory()` when a batch row's `observer` is a non-string; same root cause as B-1 |
| B-3 | **BLOCKING (on contract)** | The refusal does not enumerate every offending line: absent-observer wholly preempts mixed-observer, and any later codec fault preempts the refusal entirely |
| N-1 | non-blocking | The cross-format content-hash equality test passes by fixture accident; the two arms hash in different orders and the jsonl arm's order is undocumented |
| N-2 | non-blocking | `total_lines` counts LINES in the jsonl arm and ROWS in the sqlite arm — identical content reports different totals |
| N-3 | non-blocking | `classify_id_era` labels every non-ULID id `uuid4`; the census makes an era verdict on evidence that supports only "not a ULID" |
| N-4 | non-blocking | Weakest test proven weak: both read-only tests stay green when `inventory()` is mutated to create a directory and append a file |
| N-5 | non-blocking | Frozen-copy behavioural divergence in `_validate_batch` — the duplicate-id rule is weakened under `validate_rows=False` |
| O-1..O-8 | observation | see below |

Verified sound and worth stating: frozen-copy fidelity is otherwise clean; the census core is correct against an
independently hand-computed fixture; the read-only claim holds under a WAL-mode probe; and one mutation I expected
to survive (collapsing the content hash into the file hash) was correctly caught.

---

## Category 1 — frozen-copy fidelity

**Read:** `libs/migrate/src/migrate/legacy_jsonl.py:1-271`, `legacy_sqlite.py:1-139`, `legacy_ids.py:1-130` against
`libs/engine/src/engine/jsonl_codec.py:1-529` and `libs/store/src/store/rebirth.py:100-240`.

**Probe** (`.tmp/probe/diff_copy.py`) — `inspect.getsource` diff of every copied callable plus a value comparison of
every copied constant:

```
[jsonl] _validate: IDENTICAL
[jsonl] _row_of / deserialize_row / deserialize_records / records_from_object /
        row_object_fault / _reject_constant / _no_duplicate_keys / _load:  code identical, docstrings trimmed
[jsonl] _validate_batch: *** DIFFERS ***  (see below — the one behavioural edit)
[sqlite] _tick_columns: IDENTICAL
[sqlite] _facts_have_signature: IDENTICAL
[sqlite] _content_sha256: IDENTICAL
[sqlite] _chain_head: IDENTICAL
[ids] deterministic_ulid / identity / ulid_migration / FactRow / Transform: IDENTICAL
[ids] is_ulid: docstring only ("Crockford base32" -> "uppercase Crockford base32")

CONSTANT COMPARISON
  FACT_FIELDS / TICK_FIELDS / TICK_CHAIN_FIELDS / FACT_NULLABLE / TICK_NULLABLE /
  SIGNATURE_FIELD / _NUMERIC / _BATCH_KEYS / _MIN_BATCH_ROWS / _JCS_INT_MAX / _JCS_INT_MIN: all SAME
  _CROCKFORD: SAME    _TICK_BASE_COLS: SAME    _TICK_CHAIN_COLS: SAME
```

The docstring trims drop rationale (the JCS-domain range-check comment, the duplicate-key rationale, the
"absent IS the unsigned era" note) without touching behaviour. Given the modules are explicitly historical
artifacts, losing the *why* is a real cost but not a defect I will call.

### N-5 (non-blocking) — the duplicate-id rule is weakened under `validate_rows=False`

`libs/migrate/src/migrate/legacy_jsonl.py:222-226` vs `libs/engine/src/engine/jsonl_codec.py` (`_validate_batch`):

```diff
-        row_id = elem["id"]
+        row_id = elem.get("id")
         if row_id in seen_ids:
             raise JsonlCodecError(f"duplicate id {row_id!r} within one batch")
-        seen_ids.add(row_id)
+        if row_id is not None:
+            seen_ids.add(row_id)
```

Probe `.tmp/probe/p7_validate_rows.py`, two rows both missing `id`, `validate_rows=False`:

```
origin engine.jsonl_codec: KeyError: 'id'
copy   migrate.legacy_jsonl: ACCEPTED (no error)

# control: same id in both rows, validate_rows=False
origin engine.jsonl_codec: JsonlCodecError: duplicate id 'A' within one batch
copy   migrate.legacy_jsonl: JsonlCodecError: duplicate id 'A' within one batch
```

Unreached today (`inventory()` always calls with the default `validate_rows=True`, under which `_validate` guarantees
`id` is present and non-null). But the copy **kept the `validate_rows` kwarg**, so WP2's transformer can reach it, and
when it does the copy silently admits id-less batch rows the origin refuses. Either restore `elem["id"]` or drop the
kwarg the copy does not use.

---

## Category 2 — refusal semantics vs `engine/arrival_body.py:241-266`

**Read:** `libs/migrate/src/migrate/inventory.py:202-254`, `refusals.py:1-101`,
`libs/engine/src/engine/arrival_body.py:211-266`.

The decision *expression* was copied faithfully (`{row["observer"] for row in rows}` → a set built over row bodies,
refuse when `len > 1`). What was not copied is its **precondition**. In `arrival_body._validate_batch`, rows are
validated at lines 229-237 and `_refuse_mixed_observers` is called at line 238 — it reads `row["observer"]` unguarded
precisely because validation already guaranteed the field exists and is a string. `inventory.py` inverts this: the
observer scan at lines 206-224 runs **before** `_validate_batch(obj)` at line 228, and the `continue` at 220/224 means
an offending line never reaches validation at all.

**Probe** (`.tmp/probe/p1_differential.py`) — same single line fed to `engine.jsonl_codec.deserialize_records` and to
`migrate.inventory.inventory`:

```
case                                                 | engine.jsonl_codec                               | migrate.inventory
------------------------------------------------------------------------------------------------------------------------
batch: 2 rows, mixed observers (both valid)          | ACCEPT                                           | MixedObserverBatchRefused          [expected]
batch: 1 row only (illegal arity)                    | JsonlCodecError: batch must carry at least 2 rows| JsonlCodecError: batch must carry at least 2 rows
batch: rows not a list                               | JsonlCodecError: 'rows' must be an array         | JsonlCodecError: 'rows' must be an array
batch: 2 rows, DUPLICATE id, mixed observers         | JsonlCodecError: duplicate id '01ARZ…FB1'        | MixedObserverBatchRefused   <-- DIVERGES
batch: row is a TICK, plus mixed observer            | JsonlCodecError: batch row 1 is a tick record    | MixedObserverBatchRefused   <-- DIVERGES
batch: row has UNKNOWN field, plus mixed observer    | JsonlCodecError: unknown field(s): ['bogus']     | MixedObserverBatchRefused   <-- DIVERGES
batch: nested batch row + mixed observer             | JsonlCodecError: batch row 1 is a nested batch   | MixedObserverBatchRefused   <-- DIVERGES
batch: observer explicitly NULL in one row           | JsonlCodecError: 'observer' must not be null     | AbsentObserverBatchRefused  <-- DIVERGES
batch: observer is an INT (5) and a str              | JsonlCodecError: 'observer' must be a string     | TypeError: '<' not supported between instances of 'int' and 'str'   <-- DIVERGES
batch: observer is an OBJECT (unhashable)            | JsonlCodecError: 'observer' must be a string     | TypeError: unhashable type: 'dict'   <-- DIVERGES
```

### B-1 (BLOCKING) — the refusal overclaims on structurally invalid lines

Rows 4-7 of that table: a nested batch, a tick inside a batch, a row with an unknown field, and a duplicate id are all
reported to the operator as

> "The following source line(s) carry batch rows spanning more than one observer, which cannot map to a single
> Arrival record" — `MixedObserverBatchRefused`

That line is not a valid batch at all, so the claim is not supported by the source. Brief ruling 2 requires the type to
assert *what the source carries* — a location claim — and the arbiter's hunt list names "same decision basis" as the
test. The decision basis differs: `arrival_body` decides on validated rows, `inventory` decides on arbitrary JSON.
This is also the exact failure mode of the standing `decision:practice/scope-the-claim-over-widen-the-detection`
ruling: the detector emits a verdict ("this source has a multi-observer ceremony") where the evidence supports only
"this line is not a well-formed batch".

**Fix:** run `_validate_batch(obj)` first, then apply the observer decision to the validated rows — which is both what
`arrival_body` does and what "copy that decision rule's semantics, not its code path" asked for. This also fixes B-2
for free, since validation is what rejects a non-string observer.

### B-2 (BLOCKING) — uncaught `TypeError` escapes the inventory pass

`inventory.py:217` `observers_in_batch.add(r["observer"])` and `:220/:223` `tuple(sorted(observers_in_batch))` both
assume a hashable, mutually-orderable observer. A legacy line carrying `"observer": {"a": 1}` raises
`TypeError: unhashable type: 'dict'`; `"observer": 5` alongside `"observer": "bob"` raises
`TypeError: '<' not supported between instances of 'int' and 'str'`. Both escape `inventory()` untyped — the
operator-facing gate over live legacy stores crashes with a bare `TypeError` where the engine codec gives a clean,
attributable `JsonlCodecError` naming the field and its type. Same root cause as B-1.

### B-3 (BLOCKING on contract) — the enumeration is not complete

Two mechanisms cost lines out of the report.

**(a) Absent-observer wholly preempts mixed-observer.** `inventory.py:219-224` sorts each offending line into exactly
one bucket (`continue` after either), and `:245-254` raises absent **first**. Probe `.tmp/probe/p3_refusal.py` on a
source with mixed@line 1, absent@line 2, mixed@line 3:

```
source: line1=MIXED(kyle,dana)  line2=ABSENT  line3=MIXED(erin,frank)
raised: AbsentObserverBatchRefused
offending_lines: ((2, ('alice',)),)
--- message ---
Migration refused for source '…/both.jsonl' (batch rows missing observer field).
The following source line(s) carry batch rows missing the required 'observer' field:
  line 2: missing observer field (found observers: 'alice')
…
Mixed lines 1 and 3 appear in the report: False
```

Lines 1 and 3 — the actual GF-3 offenders — are silently dropped. The operator repairs line 2, re-runs, and only then
learns about lines 1 and 3. Ruling 1 requires the refusal to enumerate *every* offending source line, and the brief's
deliverable 5 says the absent condition is reported "in the exception's data distinctly", which reads as one exception
carrying two distinguished buckets — not two exception types racing to be raised first. The acceptance suite only ever
exercises one condition at a time, so this is invisible to the bar.

**(b) A later codec fault preempts the refusal entirely.** The refusal is deliberately deferred to end-of-scan
(comment at `inventory.py:244`) so every offending line is collected — but codec errors still raise inline mid-scan:

```
source: line1=MIXED, line2=malformed fact
raised: JsonlCodecError -> missing field(s) in fact line: ['kind', 'ts', 'observer', 'origin', 'payload']
```

The deferral therefore only delivers its guarantee on sources that are otherwise clean. Worth deciding explicitly:
either collect codec faults alongside the refusal buckets, or state in the docstring that enumeration is
best-effort and terminates at the first structural fault.

---

## Category 3 — inventory correctness

**Read:** `inventory.py:48-268`.

I built my own fixture and hand-computed its counts before running anything (`.tmp/probe/p6_census.py`): two standalone
facts, one batch line of three rows (all `zoe`), one tick, one blank line; kinds `note`×3 / `link`×2; ids spanning
canonical ULID ×3, lowercase ULID ×1, uuid4 ×1.

```
  inv.per_kind_counts  = {'note': 3, 'link': 2}          hand: {'note': 3, 'link': 2}      OK
  inv.tick_count       = 1                                hand: 1                          OK
  inv.batch_line_count = 1                                hand: 1                          OK
  inv.observer_census  = {'zoe': 4, 'amy': 1}             hand: {'zoe': 4, 'amy': 1}       OK
  inv.id_era_census    = {'canonical-ulid': 3, 'lowercase-ulid': 1, 'uuid4': 1}            OK
  inv.total_lines      = 4    (physical lines=5; fact ROWS=5; non-blank lines=4)           see N-2
```

Batch rows are counted per-row in `per_kind_counts`, `observer_census` and `id_era_census`, and per-line in
`batch_line_count` — correct. Tick rows carry no observer in either format and correctly contribute to neither the
observer census nor the era census. Blank lines are skipped (`inventory.py:178`); I checked this against the live
reader and it matches — `engine/jsonl_store.py:895-896` `_read_lines` also drops empty lines — so it is **not** a
divergence.

### N-2 (non-blocking) — `total_lines` is not one quantity

The jsonl arm sets `total_lines` to non-blank LINES (`inventory.py:180`); the sqlite arm sets it to
`total_facts + tick_count`, i.e. ROWS (`inventory.py:142`). Same logical store, both formats:

```
SAME logical store, sqlite arm:
  total_lines jsonl = 4  sqlite = 6  <-- differ for identical content
  batch_line_count jsonl = 1  sqlite = 0
  observer_census equal: True
  id_era_census  equal: True
```

The worker's own fixture table encodes the divergence (`_fixtures.py:136` jsonl `total_lines: 8` vs `:145` sqlite
`total_lines: 9`) without flagging it, and the field's docstring says "total lines/rows" as if the ambiguity were
intended. Consequence: `sum(per_kind_counts) != total_lines - tick_count` whenever batches exist (5 vs 3 above), so no
consumer can derive a row count from the inventory without knowing which arm produced it. Either carry both
(`total_lines` and `total_rows`) or name the field for one meaning and compute it that way in both arms.

### N-3 (non-blocking) — the id-era census makes an era verdict it cannot support

`legacy_ids.py:123-129`: anything that is not a 26-char uppercase-Crockford or 26-char lowercase-Crockford string is
returned as `"uuid4"`. Probe `.tmp/probe/p4_era.py`:

```
id sample                      classify_id_era    rebirth would migrate?   verdict-supported?
----------------------------------------------------------------------------------------------
01ARZ3NDEKTSV4RRFFQ69G5FAV     canonical-ulid     False                    yes
01arz3ndektsv4rrffq69g5fav     lowercase-ulid     True                     yes
8bceae3a-ac5c-435d-8591-…      uuid4              True                     NO - 'uuid4' is a catch-all
1828da12516049ada046a9ede…     uuid4              True                     NO - 'uuid4' is a catch-all
01ARZ3NDEKTSV4RRFFQ69G5Fav     uuid4              True                     NO   (mixed-case ULID)
<empty string>                 uuid4              True                     NO
hello                          uuid4              True                     NO
0IARZ3NDEKTSV4RRFFQ69G5FAV     uuid4              True                     NO   (non-Crockford 'I')
abcdef0123456789abcdef0123     lowercase-ulid     True                     yes  (26-char lower hex; ambiguous)

inventory over 6 ids: 1 canonical, 1 lowercase, 1 mixed-case, 1 empty, 1 'hello', 1 26-hex
  id_era_census = {'canonical-ulid': 1, 'lowercase-ulid': 2, 'uuid4': 3}
  -> reports 4 'uuid4' facts; ZERO of the four are uuid4s.
```

`store.rebirth.ulid_migration` knows exactly two classes — canonical (passes) and non-canonical (rewritten) — so the
transform behaviour is unaffected. What is affected is the **claim**: an operator reading the census to decide whether
the source's eras are the ones the migration understands is told "uuid4 era" about ids that are corrupt, truncated, or
mixed-case. This is the same scope-the-claim failure as B-1, relocated into the census. A fourth bucket
(`unrecognized` / `non-canonical-other`) would keep the claim inside the evidence.

Note the overclaim is *baked into the suite*: `test_legacy_readers.py:46` asserts `classify_id_era("01A") == "uuid4"`,
so no test would resist the fix.

---

## Category 4 — hash semantics

**Read:** `inventory.py:97-98, 171, 188, 199, 231-232, 256`; `legacy_sqlite.py:63-89` against `rebirth.py:193-219`.

The sqlite arm is byte-identical to rebirth's `_content_sha256`, including the file-vs-content rationale docstring —
the distinction and its "WAL checkpoints, VACUUM, and page layout change bytes without changing content" reasoning are
preserved verbatim. The forensic `file_hash` is computed from raw bytes at `inventory.py:97-98` for both arms.

**I confirmed the two-hash distinction is genuinely load-bearing**, contrary to my initial read of the test. Mutation:
replace both `content_hash` computations with `file_hash`:

```
=== the test that names the two-hash distinction ===
>       assert inv1.content_hash == inv2.content_hash
E       AssertionError: assert 'c2bff5423ccc…' == '5780e53d8729…'
FAILED libs/migrate/tests/test_inventory.py::test_two_hash_distinction_content_hash_stable_across_vacuum
=== whole migrate suite under MUTATION B ===
FAILED …::test_content_hash_matches_between_equivalent_jsonl_and_sqlite
FAILED …::test_two_hash_distinction_content_hash_stable_across_vacuum
2 failed, 12 passed
```

Credit where due — that test holds.

### N-1 (non-blocking) — the jsonl arm's hash order is undocumented, and the cross-format equality test is a fixture accident

`test_inventory.py:52-62` asserts, as a general property, that "a JSONL store and a SQLite store carrying the exact
same sequence of rows produce identical witness-order content hashes." They do not. The sqlite arm hashes
**every fact row, then every tick row** (`legacy_sqlite.py:64`); the jsonl arm hashes **in line order**
(`inventory.py:176-238`), interleaving ticks wherever they appear. The test passes only because
`_fixtures.py:157-166` happens to write both ticks last.

Probe `.tmp/probe/p2_hash.py` — same rows, tick moved into the middle of the log:

```
jsonl facts-then-ticks content_hash : 0ad1bac69dd94f241c01c30fba946c8858977b5555b7a3a67151f7271a5aaa7b
jsonl INTERLEAVED   content_hash    : 3c60a0a96a7d18acbeece45963057792e57779ec43b8e4a50b83f4d021617918
sqlite              content_hash    : 0ad1bac69dd94f241c01c30fba946c8858977b5555b7a3a67151f7271a5aaa7b

worker's claim (facts-then-ticks == sqlite): True
SAME ROWS, tick interleaved == sqlite     : False
interleaved == facts-then-ticks           : False

jsonl with integral ts spelled as int, same numeric values:
  content_hash ==  float-spelled jsonl : False
```

The canonical jsonl store is **interleaved by construction** — `engine/jsonl_codec.py:3` opens with "One interleaved
append-only log per store" — so for essentially any real store the two arms disagree about the content hash of the
same content. The second result is a further fragility: the line codec admits an integral `ts` as a JSON int
(`row_object_fault`'s `isinstance(value, (int, float))`), while sqlite returns REAL, so `1000` and `1000.0` hash
differently across the arms even at identical order.

Neither ordering is *wrong* — line order is semantic for a log, and rowid order is what rebirth witnesses. The defects
are that (i) a test asserts a general cross-format equality the code does not provide, (ii) `inventory.py`'s module
docstring and the shared field name present both as one "witness-order content hash" while the jsonl arm's ordering
rule is written down nowhere, and (iii) WP2/WP3 must not use `content_hash` as a same-content witness across a
format change, which the current test would lead a reader to believe it can. Either document the two orderings as
arm-local identities and delete the equality test, or define one canonical order (e.g. facts-then-ticks in both arms)
and keep it.

A minor note on the hash construction itself: rows are concatenated as JSON arrays with no domain separator or type
tag, so fact and tick rows are distinguished only by arity (6/7 vs 11). Faithful to rebirth, so not a divergence — but
it is inherited, not chosen.

---

## Category 5 — test strength

The suite is 14 tests. Two of the three tests in `test_refusals.py` construct the exception objects by hand and never
touch the inventory decision, so they pin the message contract but prove nothing about detection. My judgement of the
weakest target, though, was the pair that claims the read-only property.

### N-4 (non-blocking) — the read-only tests do not test the read-only property

`test_inventory_is_strictly_read_only` (`test_inventory.py:137-147`) only re-digests the source file itself.
`test_inventory_module_contains_no_write_calls` (`:150-161`) greps the module's source text for `, "w"`, `mode="w"`,
`write_text`, `write_bytes` — it covers neither `mkdir`, nor append mode, nor `os.*`, nor `tempfile`, and it cannot see
`legacy_jsonl.py`, `legacy_sqlite.py` or `legacy_ids.py` at all. Deliverable 4 requires that the pass "never creates
any path".

**Mutation A** — insert a genuinely side-effecting write into `inventory()` after the file hash:

```python
_scratch = source_path.parent / ".migrate-scratch"
_scratch.mkdir(parents=True, exist_ok=True)
with open(_scratch / "trace.log", "a", encoding="utf-8") as _f:
    _f.write(file_hash + chr(10))
```

```
=== run the two read-only tests against MUTATION A ===
..                                                                       [100%]
2 passed, 6 deselected in 0.20s

=== and the whole migrate suite ===
E         Extra items in the right set:
E         PosixPath('…/test_mixed_observer_batch_refu0/.migrate-scratch')
FAILED libs/migrate/tests/test_inventory.py::test_mixed_observer_batch_refuses_and_enumerates_every_offending_line
1 failed, 13 passed in 0.21s
```

Both tests that name the property stay green. The only thing that catches a directory being created beside the source
is the `files_before == files_after` check *inside the refusal test* — which runs only on the refusal path. For a
source that inventories successfully, nothing in the suite would notice. Fix: assert the source directory's contents
are unchanged after every successful `inventory()` call (the refusal test already shows the shape), and drop or widen
the source-text grep — it buys almost nothing and reads as coverage that is not there.

Both mutations were applied to the committed file and reverted; `git diff` over tracked paths is empty
(verified at the end of the session, see header).

---

## Category 6 — read-only claim: VERIFIED

**Read:** `legacy_sqlite.py:42-47` (`open_legacy_sqlite`), `inventory.py:93-102, 105-107, 155-156, 176`.

`sqlite3.connect(f"file:{path}?mode=ro", uri=True)` matches `store/_conn.py::_open(read_only=True)` exactly, including
its stated purpose ("Read-only mode uses URI to avoid WAL/SHM sidecars"). The jsonl arm opens `"r"`. The connection is
closed in a `finally`. No `open(..., "w"/"a")`, `mkdir`, `unlink`, `tempfile`, or `os.*` write call exists in any of
the four production modules — I read all four in full rather than relying on the suite's grep.

The sharpest hazard here is a WAL-mode source, since a read-only URI open cannot create the `-shm` sidecar. Probe
`.tmp/probe/p5_readonly.py` builds a WAL store, writes an extra fact, and holds a second connection open so the WAL is
**not** checkpointed away:

```
files on disk before inventory: ['wal.sqlite', 'wal.sqlite-shm', 'wal.sqlite-wal']
inventory over WAL-mode store OK; facts counted: 8
files after : ['wal.sqlite', 'wal.sqlite-shm', 'wal.sqlite-wal']
new files created by inventory: []
mtime changed on: []
```

It reads the un-checkpointed row, creates nothing, and touches nothing. No finding in this category.

---

## Observations

**O-1 — the sqlite arm cannot detect GF-3 at all.** `inventory.py:149` hardcodes `batch_line_count=0` and there is no
observer-grouping check on the sqlite path. Legacy sqlite has no batch envelope, so a mixed-observer ceremony in a
sqlite source is genuinely invisible — but the inventory then reports `batch_line_count: 0` as a *fact about the
source* where the honest claim is "not represented in this format" (`None` would say that; `0` does not).
Backend-contract §04 binds the transformer for both arms, so WP2/WP3 needs a ruling on what re-grouping means for a
source whose batch structure was erased before migration ever saw it.

**O-2 — private names are the package's public API.** `__init__.py:23-31, 51-54` re-exports `_chain_head`,
`_content_sha256`, `_facts_have_signature` and `_tick_columns` in `__all__`. WP2/WP3 will import underscore-prefixed
names as package API.

**O-3 — a day-one alias.** `refusals.py:101` `MissingObserverBatchRefused = AbsentObserverBatchRefused`, commented
"backward/naming symmetry", in a package with no backward-compatibility surface. It is exported in `__all__` and
asserted in `test_refusals.py:20`, so two names for one type are now pinned by a test.

**O-4 — format routing prefers suffix over content in one direction.** `inventory.py:100`: a jsonl file named `.db` or
`.sqlite` routes to the sqlite arm and surfaces a raw `sqlite3.DatabaseError: file is not a database` rather than a
typed migrate error. (Probe: `jsonl content with .db suffix RAISED: DatabaseError file is not a database`.) Low impact —
real legacy sqlite stores are `.db` and sniff correctly by magic bytes — but the failure mode is untyped.

**O-5 — the frozen sqlite reader has a live edge to engine.** `legacy_sqlite.py:99` `from engine import tick_row_hash`,
faithful to `rebirth.py:126`. The copy is correct, but it means the "frozen" reader's chain-head output follows
engine's hashing, which the arrival arc is actively changing. Not reached by `inventory()` today (`_chain_head` is
unused by the inventory pass), so this is a note for WP2/WP3, not a defect in WP1.

**O-6 — the Rule 4 row over-grants.** `store` and `lang` are declared in `libs/migrate/pyproject.toml:8-12` and in the
Rule 4 row, but nothing in `libs/migrate/src/` imports either — the only cross-lib import in the package is
`from engine import tick_row_hash` (dead) and `engine.arrival_body` in a test. The brief mandated that exact row, so
this is contract-attributable, not worker-attributable; flagging it because a Rule 4 row is an allowlist ceiling and a
wider ceiling than the code needs is what the ratchet is meant to prevent.

**O-7 — report fidelity.** Deliverable 6 required `uv run pytest tests/architecture -q` to pass. The worker's "Final
Checks" section (log lines 348-355) pastes a narrowed command — only the two rule files it edited — and reports
"16 passed". The Rule 11 failure is disclosed in §5 of the report, so this is not concealment, but the pasted green is
not the command the brief named, and the substitution is not called out at the point of the paste. Verified here:
`tests/architecture` is 112 passed / 1 failed, the Rule 11 failure being the only one.

**O-8 — cosmetic.** `ruff check libs/migrate` passes. `ruff format --check` would reformat 4 of 12 files. CI runs
`ruff check` on `libs/custody libs/sign` only and does not gate format, so this blocks nothing; noting it because the
package is new and the drift starts here. `libs/migrate/pyproject.toml` mirrors `libs/store`'s shape correctly,
including the author metadata convention used by every other lib (I checked — the address matches the repo, it is not
a typo).

---

## What I did not verify

- **Any WP2/WP3 behaviour** — transformer, `RecordDraft` construction, outer-unsigned envelopes, minting through
  `AttestedLedger`, sink append. Not built; out of WP1's surface.
- **Scale.** All probes are tens of rows. I did not benchmark, and I did not check whether `inventory()`'s
  full-file `read_bytes()` at `inventory.py:97` is acceptable on a multi-gigabyte legacy log — it loads the entire
  source into memory for the forensic hash before streaming it a second time for the content hash. That is a real
  question for live stores but I have no data on live store sizes, so I am not calling it.
- **Property/fuzz coverage.** `hypothesis` is declared as a dev dependency and never used; I did not write a
  property suite, only the targeted probes above.
- **Era-boundary dates.** I checked `classify_id_era`'s predicates against `rebirth.py:106-154`'s semantics but did
  not correlate the era labels against any real store's actual id population — I have no legacy store to sample.
- **The refusal message's advisory prose against a ruling.** I confirmed the type name and docstring carry no remedy
  (brief ruling 2) and that the advisory lives only in the message; I did not check the wording against any ratified
  vocabulary for operator options.
- **`_chain_head` correctness.** It is byte-identical to the origin and unused by `inventory()`, so I read it but did
  not probe it.
