# Slice 4 WP3 — adversarial review report (the ArrivalSink)

Reviewer worktree: `/Users/kaygee/Code/loops-wt/s4-wp3-review` at `ab9ba7c1` (base main `68cc829f`) — verified.
Under review: `libs/migrate/{__init__.py,refusals.py,sidecar.py}` + `libs/migrate/tests/test_sidecar.py`
(1811 insertions). All probes ran under `TMPDIR=<worktree>/.tmp`, `--basetemp=<worktree>/.tmp/pt`; probe test
files were created inside `libs/migrate/tests/` to reach the package fixtures and **deleted after** — final
`git status --short` is `?? .tmp/` only, and the worker's own gate re-runs green:

```
$ uv run pytest libs/migrate tests/architecture -q
154 passed in 3.75s
$ git status --short
?? .tmp/
```

Settled, not re-litigated: lineage-named staging (M-2), derived resume / no cursor files, refuse-don't-repair
(F2), report-beside-target (M-3), and `finding/s4wp3-replicate-instead-of-admission`. Two findings below are
**downstream consequences** of that self-coordination and are marked as such — the gate sizes the root blast
radius; these say what else it costs.

**Verdict: 3 BLOCKING, 5 non-blocking, 4 observations.** The sink's *data* path is sound — every crash window
I could reach leaves the legacy store authoritative and the target resumable. The failures are all in what the
code *claims*: a publish gate that verifies the wrong half of its own edit, a resume gate whose binding check
is a tautology, and refusal types that assert conditions nobody checked.

---

# BLOCKING-1 — the publish gate never asserts the location it wrote; cutover can silently no-op onto the legacy store

`sidecar.py:245-362`, gate at `:293-346`.

`edit_vertex_store_clause` rewrites the first line matching `^[ \t]*store\b.*$` (`:273-280`, `re.MULTILINE,
count=1`) and then "verifies by re-parse". The verification asserts `post_ast.store_backend ==
BackendDecl(name=backend)` (`:303`) and that fourteen non-store fields are unchanged (`:311-339`). **It never
asserts `post_ast.store`** — the one field the edit exists to change.

The regex is line-oriented and comment-blind; the loader is neither. Two admissible `.vertex` shapes make the
regex edit a line that is not the effective store clause, while the *real* clause already carries
`backend="file"` — so the backend assertion passes, field equality passes, and the function returns success
having changed nothing that matters:

1. **Duplicate `store` nodes.** `libs/lang/src/lang/loader.py:790-819` has no duplicate check; `store =
   Path(...)` simply reassigns, so the **last** clause wins while the regex edits the **first**.
2. **A `store` line inside a `/* … */` block comment** — precisely what an operator writes when disabling the
   old location during a cutover.

### Probe — end-to-end through `run_migration`

```
[commented_out_decoy] run_migration RETURNED SUCCESS
[duplicate_store]     run_migration RETURNED SUCCESS

E  AssertionError: PUBLISH LIED: descriptor still points at
E    .../data/legacy.jsonl,
E  not the migrated target
E    .../data/01M1AEY9DJ7GA864W7RY0EXGW4.arrival
E   + where '.../data/legacy.jsonl' = StoreDescriptor(backend='file',
E       location='.../data/legacy.jsonl', lineage=None, role=None, query=None, witness=None).location
2 failed in 0.62s
```

In both shapes `run_migration` returns a `MigrationOutcome` naming a fully built, `Full`-verified,
journal-witnessed target with a valid signed report — and `descriptor_for(parse_vertex_file(v))` still resolves
to the **legacy store**, which ruling 9 deliberately leaves live and writable. The operator is told the
migration succeeded. Every subsequent write lands in the legacy store; the migrated lineage silently stops
being the history. This is the one failure mode a migration sidecar exists to prevent.

### Isolated-unit sweep of store-clause shapes (`.tmp/p2_dupstore.py`)

```
[dup]              PRE store=LEGACY-REAL.jsonl -> POST store=LEGACY-REAL.jsonl  *** SILENT WRONG PUBLISH ***
[comment]          PRE store=LEGACY-REAL.jsonl -> POST store=LEGACY-REAL.jsonl  *** SILENT WRONG PUBLISH ***
[continuation]     REFUSED: PublishPreconditionRefused: edited .vertex could not be parsed   (fail-closed, OK)
[slashdash]        POST store=NEW-TARGET.arrival   OK   (`/-store` decoy correctly skipped)
[indented]         POST store=NEW-TARGET.arrival   OK
[nostore]          POST store=NEW-TARGET.arrival   OK   (insert-after-`name` branch works)
[trailing_comment] POST store=NEW-TARGET.arrival   OK   (the `// keep this` trailing comment is destroyed —
                   inside the store clause, so within the stated blast radius)
```

### Fix

One assertion, resolved against the vertex dir the way `descriptor_for` resolves it:

```python
if post_ast.store is None or (v_dir / post_ast.store).resolve() != (v_dir / target_location).resolve():
    raise PublishPreconditionRefused(..., condition="vertex_store_location")
```

Worth pairing with a refusal when the source text holds more than one `^[ \t]*store\b` match — an ambiguous
edit target is a location claim the sidecar can make honestly, where "I rewrote one of them" is not.

The worker's log (`agy-s4-wp3.log:23`) states the editor "verifies all AST fields pre-edit vs post-edit." It
verifies all fields *except* the one it edits.

---

# BLOCKING-2 — the resume genesis check is a tautology; `run_migration` will adopt and publish a stranger's lineage

`sidecar.py:760-855`.

Resume opens the target with a descriptor carrying **no lineage** (`:766`), reads the head, and then assigns

```python
lineage = current_head.lineage            # :784 — derived FROM the target
```

before checking

```python
genesis_rec.get("body", {}).get("lineage") != lineage    # :814 — compared TO the target
```

Both sides come from the same file. **The check cannot fail.** No expectation external to the target is ever
consulted: not `genesis_req.custodian`, not `genesis_req.key`, not the source hash, not the report beside the
target. The only real gate is the draft prefix diff at `:833-848`, and it runs `range(1, head.ordinal + 1)` —
so on a target at **ordinal 0 it compares nothing at all.**

A genesis-only store is not a hypothetical: it is exactly what the post-mint-pre-append crash window produces
(see the crash matrix below), and staging paths are opaque ULIDs, so two migrations in flight in one
`store_dir` are one paste away from being confused.

### Probe — resume `alice`'s migration onto `mallory`'s unrelated lineage

```
FOREIGN store minted by 'mallory': 01M1AF12G6CWDRBTEWA0K64C0P.arrival head=Head(ordinal=0, ...)
run_migration ACCEPTED the foreign target. outcome.lineage=01M1AF12G6CWDRBTEWA0K64C0P
outcome.lineage == foreign lineage: True
genesis observer   = 'mallory'  body={'protocol': 1, 'lineage': '01M1AF12G6CWDRBTEWA0K64C0P',
                                      'key': 'Ifw67DMeL0L7OgsBbx+ZsA1qdBjxByz9h1yQlaz+wKM='}
ord 1 (key intro)  = observer='alice' body={'observer': 'bob', 'key': '/LxAVQyNZsXXoW0BWqzlcPAbXhJ5Y/...'}
verify(Full)       = Head(lineage='01M1AF12G6CWDRBTEWA0K64C0P', ordinal=9, ...)
.vertex published to: .../data/01M1AF12G6CWDRBTEWA0K64C0P.arrival
```

Every gate passed. The result is a published lineage whose **founding key is mallory's**, carrying a
key-introduction at ordinal 1 signed by **alice**, whose key was never introduced. `verify(Full)` accepts it
because `Full` claims grammar, density, lineage, and hash chain — not the key registry
(`arrival_contract.py:275`). The journal's first entry *is* bootstrap/MINT, so precondition 3 passes too. The
migration's real custodian identity has been discarded in favour of a stranger's, and nothing in the
five-precondition gate looks.

### This one is downstream of the replicate finding

The remaining backstop would have been admission. It is gone. Probing the ordinary path directly:

```
first draft: kind='key' observer='alice' body={'observer': 'bob', 'key': 'ejcv7mzc8ltAec/...'}
append()   -> REFUSED: NotSupported: this adapter's append builds unsigned records: its wrap target,
              ArrivalLog.append_marked_many, assigns no signature, and Entry deliberately carries no
              signer field. A record that must arrive with an a...
```

The file adapter has no signed-append path, which is *why* the worker self-coordinated onto `replicate` — and
`replicate` "assigns no coordinates … inserts an exact pre-coordinated suffix" (`arrival_head_seam.py:1688`),
so the key-chain rule at `arrival.py:104-107` ("the record must be signed by a key that is ALREADY valid at
its ordinal") never runs. Not re-litigating the root; recording the cost: **with `replicate`, the resume path
has zero defense against a foreign target, and BLOCKING-2 is the shape that exploits it.**

### Fix

Bind the genesis to the migration's own requirements — `genesis_rec["body"]["key"] == genesis_req.key` and
`genesis_rec["observer"] == genesis_req.custodian` — and refuse ordinal 0 targets that fail it. That is a real
external expectation and it costs one comparison.

---

# BLOCKING-3 — refusal types assert conditions that were never checked (content-vs-storage contract, amendment #6)

`sidecar.py:163-176` (`_is_torn_tail_error`), `:768-800` (two `except Exception` blocks).

I expected the engine to raise `ArrivalError` for a torn tail and `ArrivalCorrupt` for a tampered record. It
raises neither. Probing both scenarios against a real staged target:

```
[torn]     engine raises : StoreLost   (StoreLost <- AttestationRefusal <- Exception <- BaseException)
[torn]     message       : ....arrival presents no head, but the journal for lineage 01M1AF7H… remembers
                           01M1AF7H…/9/6a052fbf…. The witness proves what was lost, not its contents. A fresh
                           genesis here would be a replacement wearing the old name, so a re-mint is refused
                           too. Locate a replica or backup at or above the remembered head, or run the
                           explicit trust-reset ceremony
[torn]     _is_torn_tail_error -> True

[tampered] engine raises : StoreLost   (same type, same message shape)
[tampered] _is_torn_tail_error -> False
```

Both conditions arrive as **`StoreLost`** — the seam's own compare-on-open witness signal, the mechanism
amendment #4's abandoned-epoch fence is built on. `StoreLost` is imported at `sidecar.py:107` and **never
caught**. Both are swallowed by `except Exception` and re-typed by a **substring search over exception
message prose** walking the `__cause__`/`__context__` chain (`:163-176`: `"ends mid-record" in msg or "torn
tail" in msg or "truncated" in msg or "no complete first record" in msg`).

The resulting claims are false in both directions:

- `TornTailRefused` — "Asserts that the resume target file ends mid-record" (`refusals.py:198-203`). What the
  engine actually asserted: the file presents **no head at all** while the journal remembers ordinal 9. That
  is a witness claim about lost history, strictly stronger and differently located.
- `TargetMismatchOnResumeRefused` — "Asserts that records present in the resume target **diverge from the
  expected deterministic transform of the source**" (`refusals.py:179-184`). For the tampered target, **no
  record-to-draft comparison ever ran** — the store never opened. The refusal reports the result of a
  computation that did not happen. This is a verdict claim standing in for a location claim, which is the
  exact failure `decision:practice/scope-the-claim-over-widen-the-detection` names.

The worker pasted the evidence as a passing proof without seeing it (`agy-s4-wp3.log:48`):

```
E   migrate.refusals.TornTailRefused: Resume target /.../01M1AEF2ASSFT4532V8GEH8FA1.arrival
    ends mid-record: presents no head, but the journal remembers .../3/...
```

— the sidecar's false claim concatenated onto the engine's true one, in one string.

**Advisory prose is fine.** "Start a fresh migration" is *correct* under lineage-named staging: a fresh attempt
mints a new lineage at a new path, so it never re-mints under the remembered lineage that `StoreLost` forbids.
The defect is the type and the location claim, not the remedy.

### Fix, and the STOP item the worker owed

`StoreLost` should be caught by type and surfaced as its own refusal that asserts what it actually asserts —
the journal remembers a head this file does not present. Discriminating torn-from-tampered *below* that is not
currently possible from the typed surface: `arrival.py:1255` raises a **bare `ArrivalError`** for the torn
tail while `ArrivalCorrupt` (its subclass) covers complete-but-wrong records, so `except ArrivalError` catches
both and there is no `TornTail` type. **That is a gap in the engine surface, and the brief's scope fence
required the worker to STOP and report it rather than work around it with prose matching.** No STOP items were
reported. Sizing the drift hazard plainly: reword `arrival.py:1255` and torn tails silently re-type as
"records diverge from the source."

---

# Non-blocking

## NB-1 — the field enumeration is complete today, but nothing keeps it complete

`sidecar.py:311-339`. `VertexFile` uses `lang.ast`'s hand-rolled `_frozen` decorator
(`libs/lang/src/lang/ast.py:10-101`), not `dataclasses`, so its field tuple lives on `__match_args__`:

```
VertexFile fields  : ['boundary','combine','discover','emit','lens','loops','name','observer_scoped',
                      'observers','path','routes','sources','sources_blocks','store','store_backend',
                      'strict','vertices']
checked by editor  : ['boundary','combine','discover','emit','lens','loops','name','observer_scoped',
                      'observers','routes','sources','sources_blocks','strict','vertices']
NOT COMPARED       : ['path','store','store_backend']
```

`path` is trivially equal (both parses use `v_path`), `store_backend` is asserted separately, and `store` is
BLOCKING-1. So the hand-written list is **correct as of this commit** — the hazard is tomorrow's. A new
`VertexFile` field is silently unguarded, and this arc has been bitten by two-implementations drift
repeatedly.

This is a ratchet-test candidate in the CLAUDE.md sense, and it dissolves rather than grows: the enumeration
*is* `set(VertexFile.__match_args__) - {"store", "store_backend", "path"}`, so replace fourteen hand-written
comparisons with a loop over that set. Then a new field is guarded the day it is added, and no separate
allowlist test is needed. I verified the field-equality gate does work when it fires — mutating the editor to
also clobber `name` turns 5 tests red.

## NB-2 — test 7 does not test what it is named for, which is why BLOCKING-1 shipped

`libs/migrate/tests/test_sidecar.py:561-601`, docstring "(7) Publish atomicity: pre-edit parse equals
post-edit parse in every non-store field."

The test only exercises the **crash** branch: it patches `os.replace` to raise, asserts the run fails, then
asserts `v_path.read_text() == pre_text` and `post_ast.store == pre_ast.store` **on a file that was never
edited**. Asserting a parse against itself is vacuous. Deliverable (7) — "after a *successful* run, the
pre-edit parse equals the post-edit parse in every field except the store clause" — is never executed.

Mutation, the weakest sink test in isolation:

```
--- test 7 alone, under "editor writes a WRONG store location" ---
1 passed in 0.07s
```

The mutant publishes `<target>-MUTANT`, and the test named for publish verification is green. Only
`test_full_roundtrip_synthetic_store` catches it, at `:195-199`, and only on a single clean-clause fixture —
so the editor's own gate is never exercised on a shape where the regex misses. (For contrast, the byte-identity
restart test is genuinely strong: `:304` compares `read_bytes()` of the files, not parsed records.)

Test 7 should keep the crash branch *and* add the successful-publish arm the deliverable asked for, with the
store-clause shapes from BLOCKING-1 as fixtures.

## NB-3 — `verify_migration_report` collapses six distinct causes into one `False`

`sidecar.py:560-637`. Bare `except Exception: return False` at `:585-586` and `:627-628`, plus five other
`return False` paths.

```
  valid report, live target              -> True
  target_path names a MISSING file       -> False
  target moved away (report intact)      -> False
  FORGED SIGNATURE                       -> False
  report file is not JSON                -> False
  report file absent                     -> False
```

A boolean is a verdict claim. "This signature is forged" and "I could not find the target store" are different
facts about different objects, and an auditor holding the migration's only forensic artifact needs to know
which. The module gets this right everywhere else — the refusal family is typed and structured — so the
verifier is the odd one out. It should return a typed result (or raise typed refusals) naming what failed and
where. The error discipline is also mixed: `verify=None` raises `ValueError` (`:598`) while every other
failure returns `False`.

**Signature coverage itself is sound.** Every body field is bound — I tampered each in turn:

```
  body.source_content_sha256                   -> rejected
  body.source_file_sha256                      -> rejected
  body.source_inventory.total_rows             -> rejected
  body.target_head.ordinal                     -> rejected
  body.target_head.record_hash                 -> rejected
  body.exceptions (drop keyless observers)     -> rejected
  body.transform_rule                          -> rejected
  body.equivalence_diff.matched                -> rejected
  body.custodian                               -> rejected
  body.tool_version                            -> rejected
  body: ADD an unsigned extra key              -> rejected
  signature                                    -> rejected
  OUTER signer field (outside body)            -> verify=True  *** ACCEPTED TAMPER ***
  OUTER: add unknown top-level key             -> verify=True  *** ACCEPTED TAMPER ***
```

The byte recipe is documented (docstring `:52-57`) and matches the code (`:950-951`, `:594-595`). The two
accepted tampers are the **unauthenticated outer envelope**: `signature` and `signer` live outside `body`
(`:960-964`), so a reader inspecting the JSON sees `"signer": "mallory"` and the verifier never contradicts it,
and arbitrary top-level keys can be injected into the artifact. Low severity — the caller supplies
`public_key` independently — but the fix is two lines: require `report_doc["signer"] == body["custodian"]` and
reject unknown top-level keys.

**Replay against a different target is correctly prevented**: the signed body binds lineage + ordinal +
record_hash, and `:606-636` re-checks all three against the live store.

## NB-4 — the signed source hash is the one claim nothing ever re-checks (quiescence)

Hunt item 5, answered precisely. The re-check at `:867-877` and the snapshot at `:695` call the **same**
`inventory(src_path).content_hash` — same definition, content-hash on both sides, no content-vs-file mismatch.
That part is correct.

The window from the re-check (`:867`) to `os.replace` (`:356`, reached at `:980`) spans a full target scan, the
equivalence re-run (which **re-reads the source from disk**, `:373`), inventory equality, a journal read, and
report build+sign+write — seconds on a real store. The design accepts asserted-not-continuous quiescence, so
the window itself is not the finding. What I probed is what survives it:

```
  raced: appended 1 row to source inside the publish window
  publish COMPLETED: 01M1AFAY7XVTRAST9051G604PR.arrival
  source content hash at snapshot : 74cf0fe33a727786
  source content hash after       : 82e9205c6900fec7   changed=True
  report's signed source hash     : 74cf0fe33a727786
  report still verifies?          : True
```

The report carries a signed, now-false claim about the source, and `verify_migration_report` re-checks only
`target_head` — it never re-checks `source_content_sha256`. The forensic field that would detect a quiescence
violation after the fact is signed and then never consulted. Adding an optional `source_path=` re-check to the
verifier costs one `inventory()` call and turns the accepted residual into a detectable one, which is the
honest way to accept it.

## NB-5 — the module does not pass the repo's own lint; two dead imports are load-bearing signals

```
$ uv run ruff check --statistics libs/migrate/src/migrate/sidecar.py libs/migrate/tests/test_sidecar.py
33  F401    [*] unused-import
14  E501    [ ] line-too-long
 3  SIM117  [-] multiple-with-statements
 1  SIM103  [ ] needless-bool
 1  PTH105  [ ] os-replace
 1  SIM105  [ ] suppressible-exception
Found 53 errors.
```

Mostly mechanical, but two of the 33 unused imports are diagnostic rather than cosmetic: **`StoreLost`
(`:107`) and `ArrivalCorrupt` (`:80`) are imported and never caught** — the worker reached for the typed
surface, then fell back to message-sniffing (BLOCKING-3). `import rfc8785` (`:76`) is also dead; the canonical
bytes come from engine's private `_canonical_bytes`.

Separately: `_check_equivalence` takes a `custodian` parameter it never uses (`:369`), and
`_check_inventory_equality` takes an `exceptions: TransformExceptions` it never uses (`:504`) while its
docstring claims the comparison is made "**accounting for dropped units**" (`:508-509`). It is not. A
migration with any dropped unit therefore fails inventory equality unconditionally (source per-kind count
exceeds target), making WP2's `dropped_units` exception path unreachable at the sidecar surface. Fail-closed,
so not blocking — but the docstring states a behavior that does not exist, and either the accounting or the
claim has to go.

---

# Observations

**O-1 — crash windows are clean; all three I killed are resumable.** Enumerated: post-mint-pre-append,
mid-append (between chunks), mid-append (inside a `replicate` write → torn tail), post-append-pre-verify,
post-verify-pre-report, mid-report-write, post-report-pre-publish, mid-publish. I SIGKILLed real subprocesses
at three:

```
================ WINDOW: post_mint_pre_append ================    child exit: 137
  legacy store unchanged : YES     .vertex unchanged : YES
  artifacts left in data/: 01M1AF3EPVZ31SKDSERHA2J75J.arrival
================ WINDOW: mid_append ================               child exit: 137
  CHILD: appended 4/9 drafts, head ordinal=4
  legacy store unchanged : YES     .vertex unchanged : YES
  artifacts left in data/: 01M1AF3EX5A2K7PBZN2J6G0R29.arrival + .arrival.lock
================ WINDOW: post_report_pre_publish ================  child exit: 137
  legacy store unchanged : YES     .vertex unchanged : YES
  artifacts left in data/: ....arrival + .arrival.lock + ....migration-report.json
```

and then resumed each with `resume_target=`:

```
=== resume after post_mint_pre_append ===      RESUME OK head=9 published=01M1AF3EPVZ31SKDSERHA2J75J.arrival
=== resume after mid_append ===                RESUME OK head=9 published=01M1AF3EX5A2K7PBZN2J6G0R29.arrival
=== resume after post_report_pre_publish ===   RESUME OK head=9 published=01M1AF3F3CFC44AYWEEFKSVMFV.arrival
```

The legacy store stays authoritative in every window, stale `.arrival.lock` files left by SIGKILL do not block
resume, and the mid-publish window is genuinely atomic (temp + fsync + `os.replace`, `:348-362`). Two small
residuals: `os.replace` is not followed by an fsync of the **parent directory**, so the rename's durability
across power loss is filesystem-dependent (the temp file's *data* is fsynced, its directory entry is not); and
a SIGKILL between the temp write and the replace leaks a `.tmp_project.vertex_<hex>` file that the `finally`
cleanup (`:357-362`) cannot reach — harmless, since it will not match a `*.vertex` discover glob.

**O-2 — a valid signed report is not evidence that cutover happened.** The report is written at `:965` and
publish follows at `:980`. The post-report-pre-publish crash above leaves a fully valid, signature-verifying
report beside a complete target whose `.vertex` still points at the legacy store. The body has no field
describing the descriptor or the publish, so nothing distinguishes "migrated and cut over" from "migrated,
crashed before cutover." Worth a `published_to` / vertex-path field in the signed body — which would also give
BLOCKING-1 a second place to fail loudly.

**O-3 — the report is the only file written non-atomically.** `report_path.write_text(...)` at `:965-967`,
while the `.vertex` gets temp+fsync+replace. A crash mid-write leaves a truncated report beside the target,
which `verify_migration_report` reports as an indistinguishable `False` (NB-3). Inconsistent discipline in the
one artifact meant to outlive the run.

**O-4 — the `.vertex` store clause cannot carry a lineage, and omitting it is correct.** Ruling 7's "names the
new location/backend/**lineage**" is unachievable in today's grammar: the loader *refuses* unknown store
properties (`loader.py:801-803`), so a `lineage=` property would break the file, and `descriptor_for` leaves
`lineage` unset by design (`arrival_registry.py:95-98`, forcing consumer is slice 5's adopt). The
implementation is right and the ruling's third clause is the thing that needs amending, not the code.

---

# What I did NOT verify

- **The SQLite arm end-to-end under adversarial input.** All my probes used the JSONL fixture. Test 1 is
  parameterized over both arms and passes; I did not independently attack the sqlite path, including the
  carried WP2 hazard (hardcoded six base columns). Test 10 covers only the missing-column case.
- **Concurrent runs against the same `store_dir` or the same `.vertex`.** Two sidecars publishing to one vertex
  is a plausible operator error I did not probe; the temp-file name is uuid4-unique, so the last `os.replace`
  wins silently.
- **Batch/GF-3 re-mint at slice head** — WP2's territory, out of scope here.
- **Real power loss.** All crash proofs are SIGKILL, which flushes the page cache; the parent-directory fsync
  gap in O-1 is a reading of the code, not an observed failure.
- **Whether the `.arrival.lock` files left by SIGKILL ever block a *concurrent* opener** — I only showed they
  do not block a later sequential resume.
- **`transform_rule` values other than `identity()`.** Every probe used the default, so the equivalence
  re-run's independent re-derivation (`:365-498`) was never exercised against a rule that actually maps or
  drops. Note that `_check_equivalence` re-implements the unit-walk from `transform()` rather than reusing it,
  so a rule that drops units will make the two disagree by construction (see NB-5).
- **Report size/perf on a real store.** All fixtures are ~10 records; `_append_drafts_through_wrapper` chunks
  at 500 (`:209`) and was never exercised past one chunk except by my half-append injection.
