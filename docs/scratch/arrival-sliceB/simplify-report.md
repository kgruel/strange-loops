# Cut B (projections) — 4-angle simplify pass, apply report

Branch `slice/arrival-projections-simplify`, worktree `~/Code/loops-wt/arrival-simplify`,
from `4ea1f44a`. Five commits, one per numbered move. Quality only: no move
changes intended behavior, and the one behavior DELTA that does exist (move 5)
is stated explicitly below rather than buried.

Suites after every commit, all green and equal to the pre-pass baseline:

| suite | baseline | after each move |
|---|---|---|
| `--package engine pytest libs/engine/tests` | 1739 passed, 1 skipped | 1739 passed, 1 skipped |
| `--package store pytest libs/store/tests` | 175 passed | 175 passed |
| `pytest tests/architecture` | 98 passed | 98 passed |

The corpus-dependent hypothesis failure the brief warned about never appeared;
the run was clean on every pass. `apps/` and `spec/` are diff-empty against
`4ea1f44a`, verified with `git diff --stat 4ea1f44a..HEAD -- apps spec`.

---

## MOVE 1 — one classifier for both projections (`648273aa`)

`libs/engine/src/engine/arrival_projection.py`

`rows_of_record` and `line_of_record` each spelled the same four-line classify:
structural kind to an empty result, unrecognized kind to a refusal, row-class
kind to a terminal codec call. Two near-identical refusal messages meant the
agreement between the index and the derived log was maintained in parallel
rather than stated once.

Now a single `_projects(record) -> bool` answers "does this record project, and
may we project it" — including the refusal — and each public entry is that call
plus its own terminal encoding (`records_from_object` vs `serialize_object`).
Both public names, both contracts, and both empty values (`[]` vs `None`) are
unchanged.

The refusal message unified, as sanctioned. It keeps the ordinal and the
refusing-rather-than-dropping content; it now says "this store's projections"
where the two copies said "this index" / "this projection". Checked first: no
test and no doc pinned either spelling (`grep` over `*.py` / `*.md` found the
two production sites and nothing else).

## MOVE 2 — the shared test scaffolding has one home (`d5affa1b`)

`libs/engine/tests/conftest.py`, `libs/store/tests/conftest.py`, five suites.

Engine: the byte-identical `keys` / `signer` fixture pair sat in three of the
five arrival suites. It joins the arrival test kit already living in that
conftest, where fixtures auto-discover, and the three copies are gone along
with the `Custodian` imports they were the only user of.

Store: `libs/store/tests/conftest.py` is new and takes the duplicated stub-key
and stub-signer from `test_arrival_merge.py` and `test_derived_log_merge.py`.
They are exported under the same names the engine kit uses — `STUB_KEY`,
`stub_sign` — rather than the underscore-private spellings the two copies had,
because importing a `_`-prefixed name across modules is the worse shape and
because matching the engine kit means the same scaffolding reads the same from
either side of the seam. Both `tests/` directories are packages, so the
existing `from tests.conftest import ...` pattern carries over unchanged.

Lint discipline: this move's first attempt used an unbounded string replace
that mangled `fact_signer` into `fact_stub_signer` and, worse, a directory-wide
`ruff --fix` that touched six unrelated store suites. Both were reverted whole
and redone with word-boundary substitution against only the fenced files.
`ruff check` over the three touched store files reports exactly the six
findings it reported before the pass (two `I001`, one unused `Path`, two
`F841`) — all pre-existing and all left alone.

## MOVE 3 — the codec's encode side is an object too (`a4b14924`)

`libs/engine/src/engine/jsonl_codec.py`, `arrival_store.py`,
`libs/store/src/store/merge.py`

**(a)** The decode side already had the pair — `deserialize_records` is the
line load composed with `records_from_object` — but the encode side offered
only a line, so consumers wanting the OBJECT (which is exactly what an arrival
record's `body` is) dumped a row to a string and immediately parsed it back.
`object_of_fact_row`, `object_of_tick_row` and `object_of_batch` are that
missing half, exported in `__all__`; the three `serialize_*` keep their names
and contracts as encode-then-dump compositions. `object_of_batch` keeps the
one-row collapse to a plain fact object, so `serialize_batch` stays a pure
composition rather than growing a second arm.

**No relaxed rules.** The same `_validate` runs, because it always ran inside
`_encode_obj`; only the `_dump` is skipped. That dump could not have rejected a
validated object: every field is validated to be a string, or a numeric that
`_validate` has already range-checked and proven finite, so `allow_nan=False`
has nothing left to refuse. Confirmed empirically as well — for a fact row, a
chainless tick row and a two-row batch, `object_of_*(x) == json.loads(serialize_*(x))`
including key order.

**(b)** The round-trip sites now call the encoder directly:
`arrival_store._write` (its injected parameter is now the object encoder, used
for both the pre-flight and the body) and `merge._entry_for`'s three. The
pre-flight comment's claim that it is not dead work still holds and for the
same reason: sqlite's column affinity coerces on the way in, so the
committed-row encode would accept a row the codec refuses, and the pre-flight
is what fails at the append site where it is attributable.

Beyond the four sites the brief listed, `arrival_store._ceremony_persist` held
a fifth instance of the identical pattern (`json.loads(line)` over a
just-serialized batch or fact). It is in-fence and byte-identically the same
dead work, so it was swept in the same commit rather than left as residue of a
dissolution. Flagging it because it was undirected. Both modules' now-unused
`import json` went with it.

**(c)** `merge._entry_for` no longer counts tick columns by hand. The codec
exports `TICK_CHAIN_FIELDS` and builds `TICK_FIELDS` as base-plus-chain, so the
chain names have one spelling (the nullable set derives from it too) and merge
derives the strip width as `len(TICK_FIELDS) - len(TICK_CHAIN_FIELDS)` instead
of a literal `row[:6]` and five hand-written `None`s. The division the brief
asked for holds: merge keeps the DECISION to null the chain columns, with its
custody reasoning intact in the docstring, and the codec owns the COUNT.
`_read_index_source` stops padding its 6-tuples up to full arity, which was
pure dead work — `_entry_for` stripped them right back on the next line. The
stripped tuple now rides one short of full arity, which drops the signature
exactly as an explicit trailing `None` did.

## MOVE 4 — one spelling of the lock-acquire preamble (`63568b24`)

`libs/engine/src/engine/arrival.py`

`append_marked_many` and `_append_under_lock` opened with the identical five
lines — mkdir the lock directory, open the lock file append-mode, `flock`,
truncate a torn tail, read the head — and only then diverged.
`_locked_head` is that preamble as a contextmanager yielding the head record.

It yields the head alone, not `(lock_fh, head)`: neither caller uses the
descriptor after acquisition, and yielding it would invite someone to. The
`flock` still releases exactly when the block closes the descriptor, and both
callers' log writes remain inside the block. Chaining semantics, the
compare-and-swap pin, and the torn-tail rule are untouched.

## MOVE 5 — catch-up answers "nothing to do" without the write lock (`ee46c64f`)

`libs/engine/src/engine/arrival_store.py`

The docstring claimed the already-current open stayed a lock-free read, but the
race fix that escalated the consume window to `BEGIN IMMEDIATE` sat above every
path — so every opener serialized behind every other, for a case that consumes
nothing. Catch-up runs on every open, so that is the case that has to be cheap.

The fast path is hoisted back above the escalation and BELOW the two refusal
guards, so the empty-log and rows-without-a-mark refusals still fire first.

### The predicate, and why it has two halves

The brief specified the predicate `_reconcile` uses: `mark is not None and
mark.arrival_offset == self._log.size()`. **That predicate alone is wrong, and
the suite says so.** Implemented literally, exactly one test goes red:

```
>       assert meta(db, "own_lineage") == log.lineage()
E       AssertionError: assert None == '01M0BK23MZ8M4FTGQ4S1ZGJYSE'
libs/engine/tests/test_arrival_projection.py:292: AssertionError
FAILED libs/engine/tests/test_arrival_projection.py::test_the_ceremony_crash_window_recovers_on_the_next_open
1 failed, 1738 passed, 1 skipped in 46.40s
```

The reason is that `_restore_own_lineage` is part of what catch-up DOES, not
just part of how it consumes. A fast path that skips the consume must also
establish that there is nothing to restore. So the shipped predicate is the
conjunction of both halves of the method's work:

* **nothing to consume** — the mark names the log's exact end (`_reconcile`'s
  predicate), and
* **nothing to restore** — `own_lineage` is present, which is exactly the
  condition under which `_restore_own_lineage` returns without staging.

This is completing the brief's predicate, not narrowing it. Folding the restore
INTO the fast path was rejected: staging a write needs the very transaction the
move exists to avoid. Consulting `licensed_own_lineage` on the read path so
that unabsorbed stores could also fast-path was rejected too: it would
duplicate `_restore_own_lineage`'s licensing logic outside it, to buy a
transient early state. A minted-but-unabsorbed store therefore still takes
`BEGIN IMMEDIATE` on every open — not a regression, since every open did before
this move.

### (i) Why the race fix survives

The escalation exists because two processes catching the same BEHIND index up
would both read the pre-consume mark, both replay, and the loser's INSERT would
collide on the primary key and be misreported as index state the log cannot
account for. The fast path cannot reintroduce that, because it fires only when
the mark and the log AGREE — offset equals size, so there is nothing to replay
and no INSERT to collide.

The gap path proves the other direction. `_write` reaches `catch_up` precisely
when the mark and the log disagree: its own record is already durable in the
log, so the log has grown strictly past the offset the mark was reconciled
against, and `mark.arrival_offset < self._log.size()` there by construction.
Every caller with real work still takes the lock; only callers with none skip
it.

### (ii) Why a stale "synced" is benign

A writer landing a record between the `size()` read and the return makes the
returned "synced" momentarily untrue. That is the SAME staleness `_reconcile`
has always accepted on the same predicate — it short-circuits `catch_up` and
returns a mark that another process may already have moved past. It is benign
for the same reason in both places: the position is re-read on every append,
and an append whose own arrival coordinate does not follow the reconciled one
rolls back its staged INSERT and consumes everything forward, interloper
included. A missed record is deferred to the next reconcile, never lost, and no
stamp can claim consumption that did not happen.

### The one real behavior delta

A mark whose lineage or ordinal is bogus but whose offset happens to equal the
log size, in a store whose marker is present, now opens `"synced"` instead of
being refused at open time. Before the fast path, `walk_marked` would reject
such a mark inside the transaction and catch-up would raise. The refusal is
deferred, not lost: the next real catch-up — the first append, or any open once
the log moves — still runs `walk_marked` and still refuses. No test pins the
open-time timing of that refusal; the literal-predicate probe above showed
exactly one failure, and it was the marker one.

The `"Escalated HERE and not at the top"` comment block was rewritten, not just
the docstring: it became false the moment the fast path existed. The docstring
now describes the final shape and counts the fast path's cost honestly
(`store_meta` reads plus one stat — the wording was corrected by amending
`ee46c64f`, a prose-only change; the predicate is byte-identical to the one
every proof below ran against).

### MUTATION PROOF 1 — the concurrent race tests, 4x

Run after the commit, against the shipped predicate.

```
--- run 1
1 passed in 0.46s      libs/store/tests/test_arrival_merge.py::test_concurrent_merges_never_double_append
--- run 2
1 passed in 0.19s
--- run 3
1 passed in 0.17s
--- run 4
1 passed in 0.16s
```

That test drives three real subprocesses through one gate file and asserts the
target log carries each of 61 ids exactly once, so a pass is evidence the
compare-and-swap pin and the retry loop still converge. The engine-side
process-racing pair (the appender shapes) was run 4x as well:

```
2 passed in 0.31s   test_gate_concurrent_append_keeps_ordinals_dense
2 passed in 0.30s   test_gate_two_processes_racing_genesis_produce_exactly_one_log
2 passed in 0.30s
2 passed in 0.29s
```

### MUTATION PROOF 2 — break the predicate, watch the net catch it

The predicate was replaced with `if True:` (always-true fast path), so catch-up
never consumes, never builds and never refuses. Engine suite:

```
FAILED libs/engine/tests/test_arrival_store.py::test_a_reopened_store_tails_records_appended_out_of_band
FAILED libs/engine/tests/test_arrival_store.py::test_an_absent_index_builds_forward_from_the_log
FAILED libs/engine/tests/test_arrival_store.py::test_a_record_landing_between_reconcile_and_append_is_never_skipped
FAILED libs/engine/tests/test_arrival_store.py::test_a_mint_landing_inside_the_gap_is_consumed_not_crashed
FAILED libs/engine/tests/test_arrival_store.py::test_a_ceremony_racing_an_interloper_refuses_before_any_byte
FAILED libs/engine/tests/test_arrival_store.py::test_the_stamped_mark_is_the_ratified_three_fields_and_exact
FAILED libs/engine/tests/test_arrival_store.py::test_a_rejected_insert_never_orphans_a_record
FAILED libs/engine/tests/test_arrival_store.py::test_rows_without_a_mark_refuse_rather_than_rebuild
FAILED libs/engine/tests/test_arrival_store.py::test_a_mark_the_log_rejects_refuses_rather_than_rebuilds
FAILED libs/engine/tests/test_arrival_store.py::test_an_index_without_its_log_refuses
FAILED libs/engine/tests/test_arrival_projection.py::test_rederivation_reproduces_the_index_it_discarded
FAILED libs/engine/tests/test_arrival_projection.py::test_an_absent_index_is_built_rather_than_refused
FAILED libs/engine/tests/test_arrival_projection.py::test_rows_without_a_mark_are_resolved_by_the_verb
FAILED libs/engine/tests/test_arrival_projection.py::test_a_mark_the_log_rejects_is_resolved_by_the_verb
FAILED libs/engine/tests/test_arrival_projection.py::test_the_ceremony_crash_window_recovers_on_the_next_open
FAILED libs/engine/tests/test_arrival_rederivation_rowids.py::test_rederivation_reproduces_every_rowid
FAILED libs/engine/tests/test_arrival_rederivation_rowids.py::test_a_durable_handle_survives_because_it_never_named_a_rowid
FAILED libs/engine/tests/test_arrival_rederivation_rowids.py::test_rederivation_preserves_receipt_group_contiguity
FAILED libs/engine/tests/test_arrival_rederivation_rowids.py::test_verify_chain_passes_after_rederivation
FAILED libs/engine/tests/test_arrival_derived_log.py::test_payload_rides_as_verbatim_stored_text
20 failed, 1719 passed, 1 skipped in 47.88s
```

Store suite under the same probe:

```
FAILED libs/store/tests/test_arrival_merge.py::test_concurrent_merges_never_double_append
FAILED libs/store/tests/test_arrival_merge.py::test_merge_appends_into_arrival_in_source_ordinal_order
FAILED libs/store/tests/test_arrival_merge.py::test_merge_never_writes_the_index_directly
FAILED libs/store/tests/test_arrival_merge.py::test_a_row_the_target_already_holds_appends_nothing
FAILED libs/store/tests/test_arrival_merge.py::test_a_re_run_merge_is_a_no_op
FAILED libs/store/tests/test_arrival_merge.py::test_a_fact_body_rides_verbatim_with_its_own_signature
FAILED libs/store/tests/test_arrival_merge.py::test_merged_tick_carries_no_foreign_chain
FAILED libs/store/tests/test_arrival_merge.py::test_a_partly_deduped_ceremony_appends_its_remainder
FAILED libs/store/tests/test_arrival_merge.py::test_dry_run_appends_nothing_and_reports_the_counts
FAILED libs/store/tests/test_arrival_merge.py::test_a_sqlite_source_replays_facts_then_ticks_in_rowid_order
FAILED libs/store/tests/test_arrival_merge.py::test_a_fresh_clone_with_no_index_yet_is_a_merge_target
FAILED libs/store/tests/test_arrival_merge.py::test_a_target_that_cannot_account_for_its_log_refuses
FAILED libs/store/tests/test_arrival_merge.py::test_rederivation_reproduces_every_rowid_over_a_merged_store
FAILED libs/store/tests/test_arrival_merge.py::test_an_interrupted_merge_leaves_a_re_runnable_store
14 failed, 161 passed in 11.26s
```

The tailing case (`test_a_reopened_store_tails_records_appended_out_of_band`)
and both gap cases (`..._landing_between_reconcile_and_append_is_never_skipped`,
`test_a_mint_landing_inside_the_gap_is_consumed_not_crashed`) are in the net, as
required, alongside the build case, all four refusals and the whole
re-derivation family.

Restored with `git checkout --`; `git diff -- libs/engine/src libs/store/src`
is empty and `git status --short` is clean. All three suites re-run green after
the restore (1739/1s, 175, 98).

---

## Skips, honored

Not applied, per the brief: `_reconcile`'s "one meta read" docstring undercount
(pre-existing cut A, already receipted); folding the two dedup SELECTs into a
single `UNION ALL`; anything touching the `_create`-self-enforce residue.
