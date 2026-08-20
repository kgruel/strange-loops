# Gate report — slice C2 (StoreReader.ordered + bridge dissolution)

**VERDICT: PASS.** No blocking findings. Two non-blocking advisories (one real
test gap found by a surviving novel mutation, one report-accuracy correction).

Target: `slice/c2-ordered-bridge-dissolution` @ `7d93b48e`, gated in an
independent worktree at
`/private/tmp/.../scratchpad/wt-c2-gate` (branch
`slice/c2-ordered-bridge-dissolution-gate`). Neither the implementer's worktree
nor `/Users/kaygee/Code/loops` was touched. No loops emissions.

---

## Item 1 — Scope and fences: **PASS**

`git diff feat/arrival-libs...HEAD --stat` returns exactly the report's 13
files, byte-identical to the pasted stat (also verified identical against
`7b52e190`, so the wave tip and the merge base agree):

```
 apps/loops/src/loops/commands/store.py           |  91 ++---
 docs/RECEIPT_ORDER_FOLD.md                       |  31 +-
 libs/engine/src/engine/jsonl_store.py            |  13 +-
 libs/engine/src/engine/store_reader.py           |  65 ++++
 libs/engine/tests/test_arrival_authority_gate.py |  23 --
 libs/engine/tests/test_jsonl_store.py            |   2 +-
 libs/engine/tests/test_store_reader.py           | 120 ++++++
 libs/store/src/store/__init__.py                 |   5 -
 libs/store/src/store/jsonl.py                    | 267 -------------
 libs/store/src/store/merge.py                    |   7 +-
 libs/store/tests/test_arrival_merge.py           |   2 +-
 libs/store/tests/test_jsonl.py                   | 471 -----------------------
 libs/store/tests/test_properties_merge.py        |  43 +--
 13 files changed, 250 insertions(+), 890 deletions(-)
```

**JsonlStore fence.** Read the whole file diff line by line: it is exactly two
hunks, at `:685` and `:751`, each replacing only the `store.jsonl.export_jsonl`
pointer text inside a refusal string. No signature, no control flow, no other
line. The fenced class docstring at `jsonl_store.py:85` is **absent from the
diff** — `git diff ... -- libs/engine/src/engine/jsonl_store.py | grep -c
"rebuild_jsonl"` returns **0**, i.e. the surviving `store.jsonl.rebuild_jsonl`
mention at :85 is frozen byte-for-byte as the arbiter required.

**G3-only deletion.** The `test_arrival_authority_gate.py` diff removes exactly
one function, `test_g3_apps_diff_is_empty_against_main`, plus its now-unused
`subprocess`/`pytest` imports and its `# --- G3 ---` banner.
`test_g0_*`, `test_g1_*`, `test_g2_the_verifier_consults_nothing_beside_the_log`
are untouched — no hunk touches them. Ratified per the arbiter ruling.

**Absent as required:** `SqliteStore`, benchmarks, `vertex_reader`, sdk src,
`generate_lens` appear nowhere in the diff.

**New files tracked.** `git ls-files libs/engine/tests/test_store_reader.py`
returns the path (tracked, and it is a modification not an add — the 120 lines
are appended `TestOrdered`). `libs/store/src/store/jsonl.py` and
`libs/store/tests/test_jsonl.py` return nothing — genuinely deleted from the
index, not merely untracked-in-worktree.

## Item 2 — Suites re-run independently: **PASS, all five counts reconcile exactly**

A combined `pytest libs/store libs/engine tests apps/loops libs/sdk` run does
**not** work — it dies in collection with
`ImportPathMismatchError: ('tests.conftest', .../libs/store/tests/conftest.py,
.../libs/engine/tests/conftest.py)`. That is pre-existing packaging structure,
not slice damage; suites must be run one per invocation. (Noted also because a
`| tail` pipe reports exit 0 over that failure — counts, not exit codes, are the
evidence below.)

```
=== libs/store ===   152 passed in 13.47s
=== libs/engine ===  1754 passed, 1 skipped in 51.77s
=== tests ===        110 passed in 4.38s
=== apps/loops ===   2525 passed, 1 xfailed in 11.26s
=== libs/sdk ===     313 passed in 18.32s
```

Every count matches the report's claimed 152 / 1754+1skip / 110 / 2525+1xfail /
313. Nothing to reconcile. Root `tests` green confirms Rule 17 holds over the
swept docs.

## Item 3 — Dissolution: **PASS**

Re-ran the grep myself over `libs apps docs spec` (`*.py`, `*.md`). Every
surviving hit falls in a justified category:

- `libs/engine/src/engine/jsonl_store.py:85` — the **fenced** docstring, left
  byte-for-byte (verified above). Arbiter-ruled frozen.
- `libs/sdk/tests/test_read.py:478` — `receipt_order` inside the test *name*
  `test_resolve_entity_single_member_aggregate_rides_receipt_order`. Not a
  dissolved symbol.
- `docs/RECEIPT_ORDER_FOLD.md:154` and `docs/scratch/arrival-sliceB/*` —
  substring of the Rule 17 test *filename*
  `test_rule_17_fold_order_prose_is_receipt_order.py`. Not a symbol.
- `docs/scratch/arrival-sliceC/{design-brief,design-proposal,explorers/e1-*}.md`,
  `docs/scratch/arrival-sliceB/{design-proposal,gate-report}.md` — briefs and
  receipts quoting retired vocabulary, licensed by C0's Rule 17 scan-scope
  ruling.

No hit is a live call site, import, or export. Import checks in the worktree env:

```
$ uv run --all-packages python -c "import store; store.export_jsonl"
AttributeError: module 'store' has no attribute 'export_jsonl'
$ uv run --all-packages python -c "import store.jsonl"
ModuleNotFoundError: No module named 'store.jsonl'
```

The module is gone, not merely unexported. `test_properties_merge.py`'s section
6 (the `export_jsonl → rebuild_jsonl` roundtrip property — the bridge's own
oracle) is deleted with its two imports and its docstring bullet, remaining
section renumbered 7→6, and `tempfile` / `_read_all_facts` both remain used by
sections 2/3/4 so no dead imports were left behind. Verified by grep: 16 further
live uses.

## Item 4 — Independent power proofs, NOVEL mechanics: **PASS (2 of 3 kill; the survivor is a finding)**

Baseline `pytest libs/engine/tests/test_store_reader.py -k TestOrdered` → **8
passed**. Each mutation was applied by exact-string replace with an
`assert count==1` guard (adopting the implementer's own M3 lesson about
mis-targeted replaces), the mutated line printed with `sed` before running, and
restored with `git checkout --` after. Final `git status --short` and
`git diff --stat` both empty.

**N1 — swallow `OrderingError`** (wrap `totalize` in try/except returning the
unsorted records). Novel: the report's proofs never attacked the propagation
posture.

```
FAILED ...TestOrdered::test_mixed_key_types_surface_the_refusal
1 failed, 7 passed
```
**KILLED.**

**N2 — flip `include_internal` default to `True`.**

```
FAILED ...TestOrdered::test_prefix_counts_the_visible_stream
1 failed, 7 passed
```
**KILLED**, and this independently confirms the arbiter's visible-stream ruling
is pinned in both directions (the same test also asserts the
`include_internal=True` widening).

**N3 — `ORDER BY ts ASC` instead of `ORDER BY rowid ASC`** — i.e. make the
prefix select on event time rather than arrival.

```
8 passed
```
**SURVIVED.** See Advisory A1 — this is a genuine test gap, not a production
defect.

## Item 5 — Adversarial probes: **PASS**

Constructed independently (`scratchpad/probe.py`, a real `SqliteStore` with rows
inserted directly so arrival order is under my control):

```
P1 prefix=0 -> [] | ByKey: []
P2 prefix=999 -> ['a', 'b']                       # 2-row store, no error, no padding
P3 prefix=3 ByKey(n) -> [('c', 1), ('a', 5)] | len 2
P4 ByKey('ts') -> []
P4b ByKey('kind') -> []
P4c ByKey('id') -> []
P5 prefix=2 Arrival -> ['a', 'b']
```

- **P1** `prefix=0` returns `[]` under both orderings — no off-by-one, no
  "0 means unlimited" reading.
- **P2** `prefix` larger than the store returns the whole store without error.
- **P3** is the important one. Facts are `a{n:5}, b{other:x}, c{n:1}` inside the
  window and `d{n:0}` **outside** it. Result is length **2**, and `d` — which
  carries `n` and would sort first — is **absent**. The prefix selects before
  the key projects, and non-membership shortens the result rather than
  backfilling from beyond the window. This is the single most important
  behavior in `ordered()` and it holds.
- **P4** confirms the payload-only rule against three different column names:
  `ts`, `kind`, and `id` are all stored columns, and all three return `[]` —
  columns are not key candidates, per the arbiter ruling. Payloads in this probe
  deliberately carry no `ts`/`kind`/`id` key, so `[]` is the columns rule and
  not an artifact.
- **P5** the store's `ts` values (900, 100, 500) disagree with arrival order, and
  `prefix=2` still returns `['a','b']` — arrival, i.e. rowid, as the docstring
  claims.

## Item 6 — CLI: **PASS**

```
$ uv run --all-packages loops store export /tmp/x.db
✗ store export: the sqlite-to-JSONL export bridge (store.jsonl) is gone — JSONL-canonical is a frozen legacy family and nothing produces its log any more. Canonical-log stores are arrival logs now (engine.arrival_store.ArrivalStore); a plain SqliteStore is read with `loops store` / `loops store stats`.
exit=2
$ uv run --all-packages loops store export --json /tmp/x.db
✗ store export: ...same text...
exit=2
```

Exit 2 confirmed by `echo $?`, not by reading the output. The `--json` flip
point the report flagged is real and behaves as described (stderr text, exit 2),
which the arbiter accepted.

The message names two surviving paths and I verified **both** work, on a real
sqlite store I built myself with three `note` facts:

```
$ uv run --all-packages loops store .../real.db
note         3       now  b2
exit=0
$ uv run --all-packages loops store stats .../real.db
real · 3 facts · 1 kinds · 0 ticks
exit=0
```

The refusal points somewhere true. `_refuse_store` is the module's existing
shared refusal helper (`store.py:37`), so the exit code cannot drift from the
other refusing subcommands.

## Item 7 — Docs: **PASS, R3 verified against C3's merged code**

Read the `RECEIPT_ORDER_FOLD.md` diff. **R2 has no hunk** — untouched, as
required.

R3's rewrite is checked against the actual C3 code on the wave tip, not against
the report's prose:

- `arrival_store.py:495` `_declaration_head_in_txn` returns
  `tuple[int, str] | None`, docstring *"The `(record_ordinal, id)` of the newest
  self-lineage declaration"* — matches R3's arrival-family claim verbatim.
- The same docstring states the batch-record property R3 asserts: *"the rows of
  one batch record ... share an ordinal and the tie-break falls to the fact id"*.
- Intent-version discriminator: `ceremony.py:99` `_INTENT_VERSION = 2`, enforced
  at `:737` (`if record.get("v") != _INTENT_VERSION`) — so R3's "the intent
  version is the only discriminator, which is why it bumped" is true.
- Legacy `(rowid, id)` claim unchanged from the original R3 text.

The four added "Where it is implemented" rows (arrival CAS token, the atoms
ordering primitive, `StoreReader.ordered`, and the split legacy/arrival CAS
rows) all name real paths that exist on this tip. Root `tests` suite green (110)
confirms Rule 17 accepts the swept prose.

## Item 8 — Full diff read, cruft: **PASS**

Read every hunk of the 11 modified files. The two pure deletions
(`store/jsonl.py`, `tests/test_jsonl.py`) were verified as whole-file removals
by stat totals and by `git ls-files` returning nothing for them, rather than by
reading 738 deletion lines. No debug leftovers, no commented-out code, no
TODOs, no stray prints. The deleted `_run_export` body is fully removed rather
than stubbed; the replacement docstring explains the refusal posture rather than
narrating the change. No dead imports left in `test_properties_merge.py` or
`test_arrival_authority_gate.py` (both had their now-unused imports pruned in
the same hunk).

---

## Advisories (non-blocking)

**A1 — `TestOrdered` does not pin the arrival-vs-event-time axis.** Mutation N3
(`ORDER BY ts` in place of `ORDER BY rowid`) survives all 8 tests, because
`TestOrdered._stream` inserts `ts = 100.0 + i`, monotonic with rowid, so no
fixture can tell the two axes apart. The difference is real, not theoretical:
re-applying N3 and running my P5 probe (a store whose `ts` values are 900, 100,
500) flips the answer from `['a','b']` to `['b','c']`.

```
--- P5 under N3 mutation (correct answer is ['a','b']) ---
P5 prefix=2 Arrival -> ['b', 'c']
```

Production code is **correct** — `ORDER BY rowid ASC` is what the contract and
the docstring both say. The gap is in the net: a store whose `ts` disagrees with
arrival order is exactly what `receive`/`merge` produces, so this is the case
most likely to regress. One test whose `_stream` assigns descending or shuffled
`ts` closes it. Not blocking: no behavior is wrong today, and the fix is
additive.

**A2 — the report's lint claim is a measurement artifact, and the substance is
fine.** The report says every touched file is "ruff-clean (0 findings each)".
Re-measured with `--output-format=concise`, `store_reader.py` has 18 findings
and `commands/store.py` has 28 — but these are all but one **pre-existing**.
Measured properly, by writing the `feat/arrival-libs` copy of `store_reader.py`
over the file **in place** in this worktree (so ruff resolves the same repo
config for both sides) and restoring with `git checkout --`:

```
BASE     10 UP017 · 4 UP037 · 2 E501 · 1 I001   → 17 errors
CURRENT  10 UP017 · 5 UP037 · 2 E501 · 1 I001   → 18 errors
```

The delta is **exactly one UP037**, and nothing else — the `I001` unsorted
import block was already there on the base, so this slice's added
`from atoms import Ordering` did not introduce it. Filtering the current run to
the new method's line range (195–260) confirms the same single finding and
locates it: `store_reader.py:199:33 UP037` — the quoted
`"Ordering"` annotation, which is *required style consistency*, not a defect:
the file has four other quoted TYPE_CHECKING annotations (`:38`, `:721`, `:722`,
`:855`) already. The CI lint gate scopes to `libs/custody libs/sign`
(`.github/workflows/ci.yml:65`), which this slice does not touch. No action
needed; recording it so the lint claim is not carried forward as verified when
it was not measured correctly.

**A3 — arbiter items 1–3 re-verified as implemented, not just proposed.** G3
deleted alone with G0–G2 intact (item 1, verified above); refuse-with-pointer
live with exit 2 and no argv parsing (item 2, verified above); `prefix` counts
the visible stream with `include_internal` widening it, pinned in both
directions by a test that mutation N2 kills (item 3, verified above). All three
match what the arbiter settled.

---

## Overall: PASS

The two axes `ordered()` was ruled to keep apart are genuinely apart —
`prefix` selects on arrival with `LIMIT` and nothing else, `key` orders through
`atoms.totalize`, and the P3 probe shows the composition order (select, then
project) is the ruled one rather than the convenient one. The bridge is gone at
the module level, not merely unexported, with its own property-test oracle
swept in the same change. Every refusal message that used to point at
`store.jsonl` now points somewhere I confirmed works. Five suites reconcile to
the reported counts exactly. Blocking findings: **none**.
