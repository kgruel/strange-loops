# Gate report — slice C3, CAS token = arrival head

**VERDICT: PASS.** No blocking findings. Three non-blocking advisories at the end.

Target: `slice/c3-cas-arrival-head` @ `1711b4a2`. Gate worktree built fresh from
that pointer; the implementer's worktree and the main checkout were not touched.
The implementer's report was treated as the review target throughout — every
claim below was re-derived here, and the gate item was answered with a parse
that shares no code with the implementation.

---

## Item 1 — Scope. PASS

Merge-base is the wave tip itself, so the mid-slice rebase is clean and the
three-dot diff is the whole slice with no phantom C1 deletions:

```
$ git merge-base feat/arrival-libs HEAD
6596b564458fdad1e931dd3afbcd6416913a4934
$ git rev-parse feat/arrival-libs
6596b564458fdad1e931dd3afbcd6416913a4934

$ git diff feat/arrival-libs...HEAD --stat
 libs/engine/src/engine/arrival_store.py          |  59 +++
 libs/engine/src/engine/ceremony.py               |  14 +-
 libs/engine/tests/test_arrival_cas_head.py       | 466 +++++++++++++++++++++++
 libs/engine/tests/test_ceremony_orchestration.py |  32 ++
 4 files changed, 568 insertions(+), 3 deletions(-)
```

Exactly the four named `libs/engine` files. `sqlite_store.py`, `jsonl_store.py`,
`arrival.py`, `arrival_projection.py`, `handle.py`, `atoms/spec.py` and
`benchmarks/` are all absent — the KEEP fences hold by construction, not by
inspection. No `apps/`, no `spec/`, no `docs/`. New test file is tracked:

```
$ git ls-files libs/engine/tests/test_arrival_cas_head.py
libs/engine/tests/test_arrival_cas_head.py
```

`ceremony.py` is the only production file besides the store, and its two hunks
are the `_INTENT_VERSION` constant (with its comment) and the `IntentCorrupt`
docstring. No ceremony write-path drift, no change to `_write_intent` or the
recovery refusal.

## Item 2 — Suite re-run here. PASS

The report's cold-worktree `ModuleNotFoundError` caveat reproduced, and its
remedy worked: one `--all-packages` run warms the env, after which the
acceptance command is green. Counts match the report exactly, with no
reconciliation needed.

```
$ uv run --package engine pytest libs/engine/tests -q
1747 passed, 1 skipped in 51.31s

$ uv run --package engine pytest libs/engine/tests/test_arrival_rederivation_rowids.py -q
5 passed in 0.19s

$ uv run --package engine pytest libs/engine/tests/test_absorb_edit.py -q -k receipt_axis
1 passed, 16 deselected in 0.06s
```

The rowid-survival ratchet holds, and the legacy `test_cas_token_rides_the_receipt_axis`
pin is green alongside its arrival successor — the arbiter's KEEP ruling is
satisfied and the legacy families are untouched.

## Item 3 — GATE ITEM: the token agrees with an independent walk. PASS

The shipped `test_the_token_agrees_with_a_from_scratch_walk_of_the_log` is
near-definitional, exactly as the implementer flagged, so this was answered with
a separate script that **imports no engine code for the walk**: it constructs a
store, then reads the `.arrival` file's bytes and parses them with plain
`json.loads` per line, reading `ord` / `body` / `rows` directly. Two scenarios,
each with a two-change ceremony (one batch record carrying two `_decl` rows) and
a backdated declaration landed by a second writer.

```
### backdated id=01ZZZZZZZZZZZZZZZZZZZZZZZZ
raw-bytes walk : (4, '01ZZZZZZZZZZZZZZZZZZZZZZZZ')
declaration_head: (4, '01ZZZZZZZZZZZZZZZZZZZZZZZZ')
AGREE
  ord=1 t=fact  id=01M0ENFYPDZRJZHKW93ACWE3R3 ts=1787198700.24292
  ord=3 t=batch id=01M0ENFYPMHYS5A928AMEH6YCM ts=1787198700.244257
  ord=3 t=batch id=01M0ENFYPMHYS5A928AMEH6YCN ts=1787198700.244257
  ord=4 t=fact  id=01ZZZZZZZZZZZZZZZZZZZZZZZZ ts=1.0

### backdated id=01AAAAAAAAAAAAAAAAAAAAAAAA
raw-bytes walk : (4, '01AAAAAAAAAAAAAAAAAAAAAAAA')
declaration_head: (4, '01AAAAAAAAAAAAAAAAAAAAAAAA')
AGREE
  ord=1 t=fact  id=01M0ENFYTA0T8J095R4N78JQGX ts=1787198700.365543
  ord=3 t=batch id=01M0ENFYTECT8R6B1PZ28D19FG ts=1787198700.366935
  ord=3 t=batch id=01M0ENFYTFSR43CFFZWQF42NQ4 ts=1787198700.366935
  ord=4 t=fact  id=01AAAAAAAAAAAAAAAAAAAAAAAA ts=1.0
```

Three contract claims fall out of this directly, all read off the raw file
rather than taken from the implementation:

- **Batch rows share the record ordinal.** Both ceremony rows sit at `ord=3` in
  the file itself. The coordinate counts records, not rows.
- **The axis is arrival, not `(ts, id)`.** The backdated row carries `ts=1.0`,
  the oldest timestamp in the log, and is still the head because it arrived last.
- **The axis is arrival, not lexicographic id.** The second scenario is the
  discriminator the shipped tests do not have in this exact form: the winning id
  `01AAAA…` is the *smallest* in the log, and it still wins, because the ordinal
  is the first coordinate and the id only breaks ties within one.

## Item 4 — Independent power proofs. PASS (three, all novel)

All three use break mechanics the report did not use, applied to the production
tree and reverted from a pristine copy after each run.

**P1 — return a fixed ordinal** (`candidate = (0, fact_id)`):

```
FAILED test_cas_token_rides_the_arrival_axis
FAILED test_the_ordinal_is_the_records_not_a_row_counter
FAILED test_rows_of_one_batch_share_an_ordinal_and_tie_break_by_id
FAILED test_the_token_agrees_with_a_from_scratch_walk_of_the_log
FAILED test_own_genesis_participates_as_the_head
5 failed, 1 passed
```

**P2 — off-by-one the ordinal** (`candidate = (ordinal + 1, fact_id)`). The
sharpest of the three: it preserves ordering entirely and corrupts only the
coordinate's absolute value, so it tests that the tests pin the *value* and not
merely the *rank*.

```
FAILED test_the_ordinal_is_the_records_not_a_row_counter
FAILED test_rows_of_one_batch_share_an_ordinal_and_tie_break_by_id
FAILED test_the_token_agrees_with_a_from_scratch_walk_of_the_log
FAILED test_own_genesis_participates_as_the_head
4 failed, 2 passed
```

**P3 — give each row of a batch a distinct ordinal** (`ordinal * 100 + row_index`),
i.e. reintroduce a row counter under an arrival-shaped name:

```
FAILED test_cas_token_rides_the_arrival_axis
FAILED test_the_ordinal_is_the_records_not_a_row_counter
FAILED test_rows_of_one_batch_share_an_ordinal_and_tie_break_by_id
FAILED test_the_token_agrees_with_a_from_scratch_walk_of_the_log
FAILED test_own_genesis_participates_as_the_head
5 failed, 1 passed
```

Production tree restored exactly after the last run: `git status --short` and
`git diff --stat` both empty.

## Item 5 — Stale-intent refusal. PASS

```
$ uv run --package engine pytest libs/engine/tests/test_ceremony_orchestration.py -q -k pre_bump
2 passed, 47 deselected in 0.08s
```

Read the test rather than trusting the claim: the intent file is **real**. It is
produced by `apply_declaration_update(preview, ..., write_file=_boom)` — the
actual ceremony through the actual interrupt seam — and only its `"v"` field is
then wound back from 2 to 1. Nothing is hand-forged, so the file is byte-for-byte
what the pre-bump code would have written. The test asserts the shape that
survives the bump (`old_decl_head` is still `[int, str]`, which is *why* the
version has to be the discriminator), that recovery raises `IntentCorrupt`
naming both the unsupported version and v2, and that the file is left exactly as
found. Both `jsonl` and `sqlite` arms pass.

## Item 6 — Full diff read line by line. PASS

**The lineage predicate is verbatim-equivalent to the base's.** Side by side,
the base (`sqlite_store.py:1448`) and the override differ in the coordinate and
in nothing else — same own-genesis-participates-by-id branch, same
`json.loads` guarded by `(JSONDecodeError, TypeError)` with `continue` on
failure, same `payload.get("lineage") != lineage_id` exclusion, same
`candidate > best` tuple accumulation. The one non-obvious step is the kind
filter: the base uses SQL `kind GLOB '_decl.*'` and the override uses
`kind.startswith("_decl.")`. These are equivalent — in SQLite's GLOB, `_` is a
literal (unlike LIKE) and `*` matches any sequence including empty, so the
pattern is exactly a `_decl.` prefix match. Selecting only `kind_of_row ==
"fact"` rows correctly mirrors the base's `FROM facts`. Row indices are right
against the codec's `FACT_FIELDS = ("id", "kind", "ts", "observer", "origin",
"payload")`: `row[0]` id, `row[1]` kind, `row[5]` payload.

**The walk is bounded at the reconciled mark.** `mark = self._read_mark()`, then
`if ordinal > mark.arrival_ordinal: break`. Sound as a bound because
`ArrivalLog.walk()` guarantees ordinals dense and ascending from 0 (verified in
its docstring and its per-record checks), so the first record past the mark ends
the walk. The rationale is right and worth keeping in the docstring: judging a
record another writer landed mid-ceremony belongs to `_ceremony_persist`'s
`following=` refusal, and two mechanisms judging the same interloper differently
is worse than one.

**No write-path drift.** `_declaration_head_in_txn` is a pure read — no INSERT,
no `_stamp_mark`, no log append. The base's public `declaration_head()` and
`absorb_edit` reach it polymorphically, which is why the legacy families keep
their rowid token with zero mode-qualification machinery. The only added import
is `json`. `ArrivalStore`'s write path, catch-up and `_ceremony_persist` are
untouched.

## Item 7 — Cruft. PASS

The gate's scratch copy of the production file was removed; the gate worktree is
clean apart from this report.

---

## Advisories (non-blocking, none affect the verdict)

1. **The report's line counts are one behind the branch.** It quotes 465 lines /
   567 insertions; the tip is 466 / 568. The evidence block predates the third
   commit `1711b4a2`, which tightened the from-scratch-walk test. Cosmetic — the
   file list and every substantive claim match.

2. **Gap #1 in the report is confirmed honest.** Removing the reconciled-mark
   bound and re-running leaves all six tests green (`6 passed in 0.11s`), exactly
   as the implementer said. The bound rests on argument, not evidence. Per the
   arbiter's standing ruling this is DEFERRED to wave-tail, since a race test
   reaches into the KEEP-fenced ceremony transaction window. Recorded as
   reporting accuracy, not as a finding.

3. **`_read_mark()` returning `None` short-circuits to `None`.** Noted while
   reading, not pursued: a `None` mark means nothing has been indexed, in which
   case the base implementation over an empty index would return `None` too, so
   the behaviours agree. The write path that could produce a torn mark/index
   state is KEEP-fenced this slice.

The implementer's remaining named gaps (no perf number; no end-to-end
plan→apply→recover over an arrival vertex, since the ceremony `world` fixture
has no arrival arm) match the arbiter's existing deferrals to C4/C5/wave-tail
and are not held against this slice.
