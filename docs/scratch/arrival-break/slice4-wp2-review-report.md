# Slice 4 WP2 — adversarial review report (the Transformer)

Reviewer worktree: `/Users/kaygee/Code/loops-wt/s4-wp2-review` (detached at `5f5149d9`, base
main `357cd670`, 3 commits in `git diff main...HEAD`). All probes under `<worktree>/.tmp`.
Nothing committed; production diff empty after every mutation (verified below).

**Verdict: 3 BLOCKING, 5 non-blocking, 2 observations.** The cryptographic core is sound —
key-introduction grammar, M-4 tick envelope preservation and determinism all survived probes
built to break them. The failures are at the *edges the acceptance bar never looked at*: the
SQLite arm has no validation anywhere in the pipeline, and the single most common shape in
real legacy stores (`observer = ''`) produces a draft the arrival grammar refuses.

---

## Findings

### B1 — BLOCKING: `observer=''` rows produce drafts the append path REFUSES

Legacy schema is `observer TEXT NOT NULL`, which permits the empty string. Real stores on this
machine carry it in bulk:

```
~/.config/loops/identity/instances/loops/experiments/tasks/data/tasks.db    facts=190  observer=''  147
~/.config/loops/identity/instances/loops/experiments/tasks/data/project.db  facts=66   observer=''   49
~/.config/loops/identity/instances/loops/experiments/autoresearch/data/read-latency.db facts=7  observer=''  1
```

`row_object_fault` accepts `''` (it is a `str`), so the transformer emits
`RecordDraft(observer="")`. Engine refuses that record at `libs/engine/src/engine/arrival.py:483-484`:

```python
if not isinstance(record["observer"], str) or not record["observer"]:
    _bad("observer must be a non-empty string")
```

Probe `.tmp/probe4_empty_obs.py`, sqlite arm mirroring the real schema:

```
=== transform over observer='' rows ===
  k='fact' observer='' body_id='a'
  k='fact' observer='kyle' body_id='b'
  exceptions: TransformExceptions(keyless_declared_observers=(), undeclared_row_observers=('kyle',))
  NOTE: '' is NOT reported as an undeclared row observer: True

=== append the drafts to a real ArrivalLog ===
  !! REFUSED k='fact' observer='': ArrivalGrammarError: observer must be a non-empty string
  ord=1 k='fact' observer='kyle' ACCEPTED
```

Same on the JSONL arm (`transform` → `[('fact', "''")]`).

Three ways this breaks the contract at once:

1. Deliverable 1 says "the drafts must be exactly what the contract `append` path accepts in
   WP3, no privileged shapes." These drafts are not acceptable to *any* arrival append.
2. Nothing refuses them earlier (see B2), so the failure lands **mid-migration in WP3**, as an
   untyped `ArrivalGrammarError`, after N records have already been appended.
3. §G.3's exception report is blind to the cohort: `transform.py:243` and `:328` guard the
   census with `if fr.observer:` / `if obs:`, so the store's *largest* observer cohort is
   omitted from the location claim the report exists to make.

This is a design question, not just a patch: an empty observer is neither "declared" nor
"undeclared" — it is a row that names no author. Ruling 7's vocabulary has no slot for it.
Whether it becomes a third §G.3 exception edge, a refusal, or an attributed-to-custodian
rewrite is above WP2's pay grade — but shipping drafts that cannot be appended is not.

### B2 — BLOCKING: the SQLite arm has no seam defense, and no inventory gate behind it

The brief's ruling 2 premise — "Mixed-observer/absent-observer/codec-invalid lines cannot reach
the transformer (WP1's inventory refuses first); the transformer still REFUSES" — is **false for
SQLite in both halves**.

*The transformer*: `transform.py:238-296` reads rows and hands them straight to
`body_of_fact_row` / `body_of_tick_row` with no `row_object_fault` call and no refusal
accumulator. Compare the JSONL arm (`:316-323`, `:364-371`), which validates every row.

*The inventory*: `inventory.py:141-193` (`_inventory_sqlite`) only **counts**. It runs no
`row_object_fault`, raises no `LegacySourceRefused`, and at `:167` explicitly tolerates
`observer is None`. There is no refusal gate for a SQLite source anywhere in the pipeline.

Probe `.tmp/probe3_regroup_seam.py` §C:

```
=== C. SQLITE seam defense ===
  -- payload stored as INTEGER (sqlite dynamic typing)
     NO REFUSAL: 2 drafts produced          [not a defect — TEXT affinity coerces to '42']
  -- observer NULL
     !! PASSTHROUGH: engine.arrival_body.ArrivalBodyError: fact field 'observer' must not be null
  -- tick table missing the 'name' column
     !! PASSTHROUGH: builtins.KeyError: 'name'
```

`ArrivalBodyError` passthrough at the public `transform()` surface is exactly what ruling 2
forbids. The `KeyError` comes from `transform.py:272-275`, which reads `t_dict["name"]`,
`["ts"]`, `["origin"]`, `["payload"]` with `[]` while the chain fields use `.get()` — an
era-awareness that is half-applied.

Honest scoping: NULL observer is *not* reachable under `observer TEXT NOT NULL`, so that
specific probe input is synthetic. The finding is the **absent validation layer**, which B1
then walks through with a shape that *is* reachable. The tests confirm the gap — all three
seam-defense tests (`test_transform.py:389-425`) exercise the JSONL arm only.

### B3 — BLOCKING: the transformer regroups (and silently drops) under a dropping rule

`Transform.map_fact` is documented at `legacy_ids.py:61` as returning "the (possibly modified)
row, **or None to drop it**". `transform.py:508-540` handles that by re-deciding the record
kind:

```python
if not mapped_rows:
    continue                      # the whole batch line vanishes
if len(mapped_rows) == 1:
    ... RecordDraft(kind="fact", ...)   # a batch line becomes a fact record
```

Probe `.tmp/probe3_regroup_seam.py` §A, three batch lines in, a rule that drops selected rows:

```
  drop 1 of 3 rows in batch b:
     k='batch' ids=['b1', 'b2']
     k='batch' ids=['c1', 'c2']
     k='batch' ids=['d1', 'd2']
  drop 2 of 3 rows in batch b:
     k='fact' ids=['b1']
     k='batch' ids=['c1', 'c2']
     k='batch' ids=['d1', 'd2']
     !! A BATCH LINE BECAME A `fact` RECORD — regrouping
  drop ALL rows of batch d:
     k='batch' ids=['b1', 'b2', 'b3']
     k='batch' ids=['c1', 'c2']
     !! A BATCH LINE VANISHED ENTIRELY (2 records for 3 lines)
```

Against ruling 2 ("The transformer NEVER regroups — backend-contract §04 binds it, ratified
L.3") and ruling 1 ("Map every in-scope row exactly once"). The vanish is worse than the
collapse: a whole source line disappears with no entry in the exception report and no refusal.

Note `body_of_batch`'s own docstring makes the opposite call for the same situation: "A single
row does NOT collapse to a fact body here: the caller that has one row is already choosing
`k='fact'` for the envelope, and a collapse would be this module deciding a record's kind behind
it." WP2 does precisely what engine refused to do.

**Reachability, stated honestly:** both shipped rules are total — `identity()` returns the row,
`ulid_migration()` (`legacy_ids.py:120-124`) always returns a row. So this is latent today. It
is graded blocking because the collapse is *written in*, and the next slices in this arc are
deletion/adoption — which is where a filtering rule arrives. The fix is to delete the collapse
branch and decide the rule (refuse, or record the drop in the exception report), not to rely on
no one passing a dropping rule.

---

### N1 — non-blocking: green under mutation (intra-batch row order)

Reversing intra-batch row order is invisible to the entire suite:

```
MUTATION APPLIED: batch rows emitted in REVERSED intra-batch order
.............................                                            [100%]
29 passed in 0.12s
```

(Applied to `transform.py:526-529`, `for r in mapped_rows` → `for r in reversed(mapped_rows)`;
reverted, production diff empty.) `test_grouping_grammar_batch_vs_flat` asserts
`len(batch_draft.body["rows"]) == 2` and never the order — yet the brief specifies "one batch
record with **seq 0..1**", `body_of_batch` documents "rows are fact row tuples **in emission
order**", and the envelope observer is read off row 0. A deterministic-but-wrong order would
also pass WP3's verification-by-re-run.

The product is correct — probe with a 3-row batch returns `['r1','r2','r3']`. The test is what
is missing.

### N2 — non-blocking: no signed batch row anywhere in the fixture corpus

`_fixtures.py:65-87` — `BATCH_ROW_1` and `BATCH_ROW_2` are both unsigned. So ruling 3 ("inner
signatures byte-for-byte"), the work package's single most load-bearing invariant, is never
exercised on the batch path. My mutation dropping batch-row inner signatures passed 29/29 —
but *vacuously*, because the fixture cannot distinguish it. I verified the product directly
instead, with a hand-built 3-row batch mixing signed and unsigned rows:

```
batch row order + inner sigs:
   r1 -> 'INNER-SIG-ONE'
   r2 -> None
   r3 -> 'INNER-SIG-THREE'
order preserved : True
sigs verbatim   : True
```

Product correct, coverage absent. Add a signed row to `BATCH_ROW_1`.

### N3 — non-blocking: untyped refusals at the public `transform()` surface

```
missing source                             -> UNTYPED builtins.FileNotFoundError
jsonl misnamed .db                         -> UNTYPED sqlite3.DatabaseError: file is not a database
custodian absent from observers block      -> UNTYPED builtins.ValueError
unparseable .vertex                        -> UNTYPED lang.errors.ParseError
vertex of wrong type                       -> UNTYPED builtins.TypeError
```

`TypeError` is a programmer error and fine. `ParseError` is lang's own typed answer about the
declaration and defensible. The two worth fixing are the bare `ValueError` for a declaration
that does not name its own self-observer (`transform.py:193-196`) — a real operator-facing
condition — and the `sqlite3.DatabaseError`, which is N4.

### N4 — non-blocking: the format-detection suffix clause can only misroute

`transform.py:236`:

```python
is_sqlite = header.startswith(b"SQLite format 3\x00") or source_path.suffix in (".sqlite", ".db")
```

A real SQLite file already matched the magic header, so the `or` clause never *adds* a correct
routing — it only routes non-SQLite files with those suffixes into the SQLite arm, where they
die as `sqlite3.DatabaseError`. Pure downside; the line dissolves. (`inventory.py:136` carries
the same clause — same reasoning, outside WP2's fence to fix.)

### N5 — non-blocking: the sqlite facts-then-ticks order is not documented as ruled

Ruling 1 requires the sqlite order be "documented as such". The module docstring
(`transform.py:33-41`) says only "in ruled source order"; the facts-then-ticks rule survives as
two inline comments (`:241`, `:269`). A reader of the docstring cannot learn that a legacy
sqlite tick interleaved in event time lands after every fact.

---

### O1 — observation: whole-store materialization

`transform()` returns `drafts: tuple[RecordDraft, ...]` — every record of the source in memory
at once. Contract-compliant (a tuple is an iterable) but it forecloses the streaming shape, and
this arc already carries an O(n²) ingest finding. Worth a decision before slice 6 rather than
after.

### O2 — observation: what "byte-preservation" actually means here

The worker preserved the ten tick **commitment field values**, not bytes. The signature survives
because JCS is a total function on the JSON value, so re-canonicalization is byte-stable — I
confirmed `rfc8785.dumps({'ts': 1007})` and `{'ts': 1007.0}` are both `b'{"ts":1007}'`, which is
why the sqlite arm's REAL→float coercion is harmless. That is the right answer, but it holds
*because of JCS*, not because bytes were carried. Anything that ever hashes the pre-JCS form
would break. Worth stating in the docstring.

---

## Categories verified clean, with proof of work

**1. Grammar fidelity of drafts** — `transform.py:204-229` read against `arrival.py:578-591`
(`_placement_fault`'s key-introduction rules), `:1954-2060` (`verify_authorship` / `_walk_authority`),
`:630-644` (`content_commitment`), `:870-930` (`mint`). Probe `.tmp/probe1_authority.py` builds a
real Ed25519-signed log from the drafts and runs engine's own walk:

```
=== drafts ===
  [0] k='key' at=0.0 obs='cust' origin='' sig=yes body_keys=['key', 'observer']
  [1] k='key' at=0.0 obs='cust' origin='' sig=yes body_keys=['key', 'observer']
  [2] k='fact' at=1.0 obs='alice' origin='o1' sig=NONE ...
=== verify_authorship ===
  ord=0 observer='cust' key=iiUsy7+UHlMS... introduced_at=0
  ord=1 observer='cust' key=iiUsy7+UHlMS... introduced_at=0
  ord=2 observer='cust' key=iiUsy7+UHlMS... introduced_at=0
RESULT: authority walk PASSED
```

The probe also re-derives each commitment through engine's `append` and compares to the draft's
own signature — no `COMMITMENT MISMATCH` line printed, so the transformer's
`content_commitment(kind, at, observer, origin, body)` inputs are exactly engine's. Custodian is
introduced **once**, at ordinal 0 only (`transform.py:205-207` skips it), which is what
`_walk_authority:2020` requires. Body shape `{"observer", "key"}` matches `arrival.py:2047-2048`.

**2. M-4 tick envelope preservation** — probe `.tmp/probe2_tick.py` signs a real tick with
engine's own `_tick_commitment_hash` (`sqlite_store.py:177-183`) and real Ed25519, pushes it
through **both** arms, then re-derives the commitment *from the draft body*:

```
=== jsonl arm ===          === sqlite arm ===
  body ts repr : 1007        body ts repr : 1007.0
  digest matches orig : True digest matches orig : True
  signature preserved : True signature preserved : True
  SIGNATURE VERIFIES  : True SIGNATURE VERIFIES  : True
```

`tick_tuple` (`:275-287`, `:375-387`) is built in exact `TICK_FIELDS` order + signature last,
matching `_tick_envelope`'s column order. See O2 for the precise sense in which this holds.

**3. Grouping + ordering** — hand-computed interleaved JSONL fixture (fact, tick, batch, tick,
fact), probe §B:

```
  expected: [('fact','f1'), ('tick','T1'), ('batch','g1'), ('tick','T2'), ('fact','f2')]
  got     : [('fact','f1'), ('tick','T1'), ('batch','g1'), ('tick','T2'), ('fact','f2')]
  ORDER PRESERVED: True
```

Ticks are **not** re-ordered relative to facts in the JSONL arm. Batch intra-order verified in
N2's probe. §G.3 undeclared-observer rows are admitted in place, no repositioning.

**4. Determinism depth** — probe `.tmp/probe5_determinism.py`: 6 observers (2 keyless), 3
undeclared row observers, a batch, `ulid_migration()`, across five separate processes with
`PYTHONHASHSEED` ∈ {0, 1, 7, 12345, 99999}:

```
PYTHONHASHSEED=0     drafts_sha=2440c0a7...aa18e1  n=14  exc=[["zeta","bravo"],["undeclared-a","undeclared-m","undeclared-x"]]
PYTHONHASHSEED=1     drafts_sha=2440c0a7...aa18e1  ...
PYTHONHASHSEED=7     drafts_sha=2440c0a7...aa18e1  ...
PYTHONHASHSEED=12345 drafts_sha=2440c0a7...aa18e1  ...
PYTHONHASHSEED=99999 drafts_sha=2440c0a7...aa18e1  ...
  intro order: ['alpha', 'mike', 'yankee', 'delta']   (identical every run)
```

Key-introduction order is declaration order (`transform.py:204` iterates `vf.observers`, a
tuple — not a set); `undeclared_row_observers` is `sorted()`; `keyless_declared` is a list in
declaration order. No set iteration reaches the draft path. ULID mapping stable across processes.

**5. JSONL seam defense** — all three enumerated classes raise `LegacySourceRefused` (a
`MigrationRefused` subclass), no `JsonlCodecError`/`ArrivalBodyError` passthrough, no asserts.
Verified for mixed-observer, absent-observer, codec-invalid. **SQLite arm is B2.**

**7. P3 regression** — differential probe against the pre-P3 frozen original (`git show
c966d981:.../legacy_jsonl.py`) over 156 constructed cases (every field × {None, int, str, bool,
float, list, dict, NaN, absent} for both row classes, plus unknown-field, null-signature and
typed-signature cases):

```
cases=156 divergences=0
skip_fields=observer on observer-less row -> None
```

Default `skip_fields=frozenset()` makes `checked_fields == list(fields)`. **No fidelity break.**

**Rule-4 row** — landed as exactly `{engine, lang}`; real non-stdlib third-party imports across
`libs/migrate/src/migrate/*.py` are `engine`, `lang`, `ulid`. Matches.

**Final gate** (mutations reverted first):

```
128 passed in 6.17s          # uv run pytest libs/migrate tests/architecture
git status --short            # ?? .tmp/   only
git diff --stat               # empty — production tree restored
```

Quarantine grep hits are docstring provenance lines only ("copied from `engine.jsonl_codec` at
commit…"), no imports.

---

## What I did NOT verify

- **WP3's real append/replicate path** — it does not exist yet. I used `ArrivalLog.append` as
  the stand-in oracle. If the contract sink consumes `draft.signature` directly (rather than
  re-signing via an injected `Signer` as `arrival.py:1493-1500` does), the commitment agreement
  I proved is still necessary but I have not exercised that code path.
- **Slice-6 end-state verification** — whether a fully migrated `.arrival` store passes
  `verify_authorship` at real scale, and whether the inner fact-domain verifier accepts migrated
  fact bodies. I verified the tick commitment; I did not verify the *fact* inner commitment
  (`_fact_commitment_hash`) round-trips, though `arrival_body`'s docstring claims it and the
  payload-verbatim invariant I did check is its precondition.
- **Concurrency / partial-failure** — no probing of what a WP3 crash mid-append leaves behind.
- **Scale** — largest probe was 14 drafts. O1 is a read of the code, not a measurement.
- **The `.vertex` key-shape gap** — the transformer never runs `_key_shape_fault` on declared
  keys, so a malformed declared key produces a draft that WP3 refuses at append. Real stores all
  carry base64 raw-32 keys (verified against `.loops/project.vertex`), so I could not reach it
  with a realistic input and did not raise it as a finding.
- **`.vertex` files with observer names that are not valid record observers** (e.g. empty-string
  observer names in the declaration) — not probed.
