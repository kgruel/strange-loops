# Gate report — slice C4 (combined read + sdk under a declared Ordering)

**Verdict: PASS.** No blocking findings. Three non-blocking advisories at the end.

Gate worktree `wt-c4-gate` on `slice/c4-combined-read-ordering-gate` @ `e573d318`.
Pre-slice comparison worktree `wt-c4-pre`, **detached** at `7b52e190` (no branch moved).
Every number below was produced in this gate's own worktrees; nothing was taken from the
implementer's report.

---

## Item 1 — Scope: PASS

`git diff --name-only 7b52e190..e573d318` is exactly the 5 reported files:

```
libs/engine/src/engine/vertex_reader.py
libs/engine/tests/test_combined_read_ordering.py
libs/sdk/src/sdk/read.py
libs/sdk/tests/test_read_ordering.py
tests/architecture/test_rule_17_fold_order_prose_is_receipt_order.py
```

All KEEP-fenced files are ABSENT from the diff: no ArrivalStore write path, no `Spec.replay_from`,
no `handle.py`, no benchmarks, no `sqlite_store.py` / `jsonl_store.py`, no `store_reader.py`,
no `generate_lens`.

Both new test files are TRACKED (`git ls-files` returns both). Working tree clean.

**Rule 17 allowlist edit is deletions-only.** The diff removes two tuples and rewords a comment
above a surviving tuple; no tuple is added or repointed. That matches the arbiter's ratchet-forced
shrink-only ruling.

## Item 2 — Suites: PASS, all three match the report exactly

The cold worktree did need the `--all-packages` warm-up, as noted in the brief.

```
uv run --all-packages pytest libs/engine/tests -q  →  1764 passed, 1 skipped in 54.68s
uv run --package sdk    pytest libs/sdk/tests   -q  →  323 passed in 9.96s
uv run                  pytest tests            -q  →  110 passed in 3.17s
```

No mismatches to reconcile.

## Item 3 — Equivalence pin, verified INDEPENDENTLY: PASS

Own fixture, own values (`G0`–`G4`, ts `9000/5000/7000/1000/3000`), deliberately **not**
the implementer's `_INTERLEAVED`. Harness `scratchpad/gate_equiv.py` builds a combine-of-one
vertex, seeds 5 facts in a fixed insert order, and prints the fold-input payload list from
`_combined_read(..., return_payloads=True)`. Run at the **pre-slice tip** (called exactly as
old callers did — the `ordering` parameter does not exist there) and at the **slice tip**.

```
old_default         ['G0', 'G1', 'G2', 'G3', 'G4']
direct rowid (sql)  ['G0', 'G1', 'G2', 'G3', 'G4']
direct (ts,id)(sql) ['G3', 'G4', 'G1', 'G2', 'G0']
new_default         ['G0', 'G1', 'G2', 'G3', 'G4']
new_arrival         ['G0', 'G1', 'G2', 'G3', 'G4']
new_bykey_ts        ['G3', 'G4', 'G1', 'G2', 'G0']

DISCRIMINATES (rowid != ts order): True
old == direct rowid              : True
BYTE-IDENTICAL old == new_default: True
BYTE-IDENTICAL old == new_arrival: True
ByKey(ts) == direct (ts,id)      : True
```

The two BYTE-IDENTICAL lines compare the **full payload dicts** (`_id`, `_ts`, `_observer`,
`_origin` and body fields), not just the id sequence. The fixture genuinely discriminates:
arrival order and event-time order share no prefix.

**Bonus, same method, multi-store:** the old `(ts, id)` sort and the new `ByKey('ts')` default
agree on a real two-member aggregate — old `['A1','B1','B0','A0']` == new default == new
declared `ByKey('ts')`. `read_facts` on the same aggregate is unchanged old-vs-new
(`['A0','B0','B1','A1']`).

## Item 4 — Aggregate `Arrival()` refuses loudly at BOTH surfaces: PASS

Run by this gate (`scratchpad/gate_refuse.py`) against a real two-member aggregate:

| Surface | Result |
|---|---|
| `resolve_ordering(Arrival(), single_store=False)` | `OrderingError` |
| `_combined_read(multi, ordering=Arrival())` | `OrderingError` |
| `sdk.read_facts(multi, ordering=Arrival())` | `SdkValueError` |

All three carry the identical message, which names the **reason** and the **alternative**:

```
Arrival() is not available on an aggregate read: arrival ordinals are dense per-log,
so a combined view of several stores has no cross-store arrival total order.
Declare ByKey(field) instead — e.g. ByKey('ts'), the aggregate default.
```

**One-member-aggregate divergence pin — both halves confirmed as disclosed:**

- engine `_combined_read(solo, ordering=Arrival())` → **ACCEPTS**, returns `['A0','A1']`
  (arrival; ts order would be `['A1','A0']`, so it discriminates). Keys on store count.
- sdk `read_facts(solo, ordering=Arrival())` → **REFUSES** with `SdkValueError`. Keys on
  declaration shape.

This is the pre-existing axis divergence the arbiter ruled disclosed-not-changed. Verified
present and unchanged; not treated as a finding.

**Unsupported-ordering refusal (minimal-surface ruling):**
`read_facts(multi, ordering=ByKey('topic'))` → `SdkValueError: ordering ByKey(field='topic')
is not supported on a paged read this cut: this path serves ByKey(field='ts'). Declare that,
or omit ordering.` Names what IS served rather than approximating.

## Item 5 — Two power proofs with NOVEL mechanics: PASS (four run, all discriminating)

None of these mechanics appears in the implementer's five. Baseline before each:
`17 passed` (engine ordering file) / `10 passed` (sdk ordering file).

| # | Novel break | Result |
|---|---|---|
| P1 | `resolve_ordering` unconditionally returns `ByKey('id')` | **8 failed** (engine) + **6 failed** (sdk) |
| P2 | `_row_field` drops the `_ROW_COLUMNS` fast path, always parses payload | **3 failed** (engine) |
| P3 | sdk `None` path routed THROUGH the resolver | **323 passed** — see item 6 |
| P4 | native-order sort deleted from `_fetch_combined_rows` | **1 failed** — see item 7 |

P2's mechanism is worth naming so a green result could not have been misread: fact payloads
carry no top-level `ts`, so bypassing the column accessor makes `ByKey('ts')` see `None`
everywhere and exclude every record. It goes red on that, i.e. the column-backed accessor is
genuinely pinned rather than incidentally satisfied.

After all four breaks were reverted: `git status --short` clean, `git diff --stat` empty.

## Item 6 — "None reroutes nothing": PASS, verified two ways

**By reading:** `_check_declared_ordering` opens with `if ordering is None: return` (read.py:76-77),
before any resolver call or totalization. `read_facts` adds exactly two call sites (read.py:322, 388)
and nothing else on the None path. Grepping every `ordering` reference in read.py confirms no other
new execution: the remaining hit, `resolve_entity` at read.py:744, replaces a `len(store_paths) == 1`
test with the equivalent resolver-derived one and is covered by the suite.

**By experiment (P3):** forcing the None path to route through the resolver
(`ordering = resolve_ordering(None, single_store=single_store)` in place of the early return)
leaves the **entire sdk suite green — 323 passed**. Routing None through the resolver is
observably a no-op, which corroborates the byte-identical-by-construction claim rather than
contradicting it. Not a finding.

**Completeness of validation (no silent-ignore path):** read_facts' only pre-322 exit is the
pre-existing `order` check at 308. Line 322 sits inside `if info.target_type == "vertex"` and
precedes BOTH the aggregate and single-store sub-branches; line 388 catches the non-vertex
fall-through. No path accepts a declared `ordering` and ignores it.

## Item 7 — The implementer's near-miss fix has teeth: PASS

Re-did proof 4's break independently (deleted `if len(aliases) == 1: rows.sort(key=lambda r: r[6])`):

```
FAILED libs/engine/tests/test_combined_read_ordering.py::
       TestTheFetchMaterializesNativeOrder::test_one_store_is_sorted_into_arrival_order
1 failed, 16 passed in 0.15s
```

The stub-connection test returns rows in a deliberately wrong order, so it cannot be satisfied by
sqlite's incidental rowid scan — which is exactly the hole the implementer reported and closed.
The sibling multi-store test likewise asserts up front that a rowid sort *would* reorder its
fixture, so it cannot pass vacuously. Restored; diff empty.

## Item 8 — Full diff read: PASS, no cruft

Production diff read line by line. The `single_store` basis moved from `len(aliases)` to
`len(store_paths)`; these are always equal because `_open_combined` appends one alias per path
and never filters, so this is not a behavior change. `resolve_entity`'s empty-`store_paths` case
resolves to `ByKey` and short-circuits before `store_paths[0]`, so no new IndexError. Both new
test files are free of skips, xfails, and dead helpers, and each discriminating fixture carries
its own guard assertion.

**NULL-`ts` concern checked and moot:** the new aggregate default `ByKey('ts')` would *exclude*
rows with a null key where the old `(ts, id)` sort did not. `sqlite_store.py:312` declares
`ts REAL NOT NULL`, so no such row can exist. No finding.

---

## Non-blocking advisories

1. **One-member-aggregate refusal wording.** The sdk refusal for a one-member aggregate says
   "a combined view of several stores", which reads slightly off for a single member. The reason
   it names still holds and the implementer disclosed this deliberately; noting it only so a later
   cut that unifies the two axes remembers to retune the text.
2. **Wasted sort on a single store with a declared `ByKey`.** `_fetch_combined_rows` rowid-sorts
   whenever `len(aliases) == 1`, independent of the resolved ordering, so `ByKey(K)` on one store
   pays a rowid sort that `totalize` then discards. Correctness is unaffected; it is a small
   avoidable cost if declared non-default orderings on single stores become common.
3. **Payload-key orderings cost one `json.loads` per record.** Expected and documented, and both
   defaults stay zero-parse; flagging only as input to the pre-ship perf benchmark already on the
   residue list.
