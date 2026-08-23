# Slice D — simplify pass report

Branch `slice/D-simplify`, worktree `wt-simplify`. Seven rulings applied; six
produced changes, one (S-3) was already satisfied on the branch and is reported
as a verified no-op rather than a fabricated edit.

## S-1 — factor the coordinate-axis stamp

`libs/engine/src/engine/sqlite_store.py`. The `CREATE TABLE IF NOT EXISTS
store_meta` + `INSERT OR REPLACE ... 'coordinate_axis'` pair appeared four
times. Added `_stamp_coordinate_axis(conn, mode)` (statements only, no commit)
just above `ensure_coordinate_schema`; all four sites call it.

Transaction boundaries are unchanged and still owned by the callers:

| site | boundary kept |
| --- | --- |
| `if not existing_tables` | `conn.commit()` after the call |
| `if already_migrated` | `conn.commit()` after the call |
| verified-table final stamp | inside the caller's `BEGIN IMMEDIATE` / `COMMIT` |
| `_rebuild_table` step 10 | inside the rebuild's caller-owned transaction |

## S-2 — column index maps

Added module-level `FACT_COLUMN_INDEX` / `TICK_COLUMN_INDEX` (`{name: i}`)
next to `FACT_ALL_COLUMNS` in `sqlite_store.py`. Three derivation sites now
read them instead of calling `.index()`:

- `libs/engine/src/engine/jsonl_store.py` — the `sig_col_idx` block
- `libs/engine/src/engine/arrival_store.py` — the `sig_col_idx` block
- `libs/store/src/store/merge.py` — the six `_kind`.. `_sig` locals, now one
  tuple unpack. The F-4 / W5-1 provenance comment is kept, shortened to
  `# Derived, not hardcoded (WP-1a F-4 / WP-5 W5-1).`

`FACT_CONTENT_COLUMNS` / `TICK_CONTENT_COLUMNS` had no other use in the two
engine store modules, so their imports were replaced (not added to); the
constants themselves stay — they are the maps' source and are used elsewhere.

## S-3 — per-connection `_ensure_coordinate_schema` cache: ALREADY SATISFIED

No change made. The caching the ruling asks for is already on the branch:

- `sqlite_store.py:985` — `self._coordinate_ready = is_new` at connect time
- `_ensure_coordinate_schema` returns immediately when the flag is set, and
  sets it after a successful `ensure_coordinate_schema` call

The flag is instance state on a connection assigned exactly once (`self._conn`
at `__init__`, set to `None` only at `close()`), and the reopen paths
(`jsonl_store._open_index`, the stale-index rebuild that re-runs
`super().__init__`) go through a fresh instance, so it invalidates correctly.

Empirical receipt — spy on the module-level `ensure_coordinate_schema` across
five appends per connection:

```
new-db module-fn calls: 0      (new DBs get coordinates in the schema)
reopen module-fn calls: 1      (verified once, then cached)
```

The G-D0 hand-stamp tests (`libs/engine/tests/test_arrival_coordinate_d0.py`)
pass untouched. Nothing was weakened.

## S-4 — split the Projection cursor from the fold count (headline; resolves W3-3)

`libs/engine/src/engine/projection.py` conflated two roles in `cursor`. The
`isinstance` branches in `fold_one`, `fold_one_mut`, and `advance`'s fallback
incremented a **tuple** cursor as `(arrival_ordinal + 1, arrival_seq)` — a
coordinate no store ever minted, and one that can skip real rows (the next
arrival may be `(ordinal, seq + 1)`, which such a cursor steps straight past).

Split applied:

- `events_folded: int` — bumped unconditionally in `fold_one`, `fold_one_mut`,
  and once per event in both `advance` paths. This is the projection's own
  count and the only thing boundary accounting may read.
- `cursor` — assigned only from what a store hands back: `next_cursor` from
  `since_with_cursor`, or the int increment on the `since(n)` fallback. That
  fallback increment is kept deliberately: `since(n)` on an int-cursor
  `EventStore` **is** index arithmetic, so it is store-derived. The tuple
  branch there was the fabrication and is deleted (only `SqliteStore` and its
  subclasses use pair cursors, and they all provide `since_with_cursor`, so
  the deleted branch was unreachable for real pair-cursor stores).

`libs/engine/src/engine/vertex.py` boundary reconciliation reads
`loop._projection.events_folded`; the `NotImplementedError` typed guard is
deleted. Every replay route feeds the count — verified: the raw
`replay_cursor` and `since_raw` paths call `fold_one_mut`, the non-mut raw path
calls `fold_one`, and the full-Fact fallback goes through `Loop.receive`
(`loop.py:105-108`), which calls one of the two.

### Test changes (exact)

| test | before | after |
| --- | --- | --- |
| `test_vertex.py` W3-3 pin | asserted `NotImplementedError` on a pair cursor | rewritten as `test_replay_pair_cursor_boundary_count_is_counted_not_coordinate_read`: replay succeeds, `events_folded == 1`, `_count_since_boundary == 1` |
| `test_behavior.py::test_reset_preserves_cursor` | `cursor == 2` after two `fold_one` | renamed `..._cursor_and_count`; asserts `events_folded == 2` **and** `cursor == 0`, both preserved across `reset` |
| `test_integration.py::test_projection_cursor_tracks_events` | `cursor == 2` after two tapped emits | renamed `test_projection_counts_tapped_events`; `events_folded == 2`, `cursor == 0` |
| `test_tick.py:218/235` | advance on an int-cursor `EventStore` | unchanged, still pass |
| `test_seal_rebase_d2.py` | — | **new** `TestW3_3_CursorAndCountAreSeparateRoles` regression test |

No assertion was weakened: the two retargeted tests gained an assertion each
(they now pin both roles where they previously pinned one conflated value).
Net engine count: 1893 → 1894 (+1 new test; the rewrites are in place).

### Mutation proof

Re-introduced the tuple increment in `fold_one`:

```python
        self.events_folded += 1
        if isinstance(self.cursor, tuple):
            self.cursor = (self.cursor[0] + 1, self.cursor[1])
```

```
>       assert proj.cursor == cursor_after_advance  # pre-fix: (4, 0), a phantom
E       assert (4, 0) == (3, 0)
E         At index 0 diff: 4 != 3
libs/engine/tests/test_seal_rebase_d2.py:706: AssertionError
1 failed in 0.07s
```

Restored; suite green. The test catches the exact defect the split removes.

## S-5 — one cursor normalisation, one range query

`sqlite_store.py`. Added `_cursor_bounds(cursor) -> (int, int)` (staticmethod)
and `_rows_since(columns, cursor, table="facts")` returning the live SQL
cursor. `since`, `since_with_cursor`, `since_raw`, `replay_cursor` are now
row-shaping wrappers; `replay_cursor` still streams (it iterates the SQL cursor
rather than materialising).

**Deviation, deliberate:** the ruling named four methods; the same
normalisation block appeared a **fifth** time in `ticks_since`
(`sqlite_store.py`, ticks table). Leaving it would have been the residue the
factoring exists to remove, so `_rows_since` takes a `table` argument and
`ticks_since` uses it. All five copies are gone.

`since_raw` is **kept**: `vertex.py:932` calls it on the raw replay fast path
(plus `store/merge.py` test harnesses and `test_jsonl_store.py`). The removal
branch of the ruling does not apply.

The G-D2-5 rowid ratchet (which AST-parses this file for `rowid` in ORDER BY /
range WHERE / COUNT windows) and the Rule 17 fold-order prose ratchet both
still pass.

## S-6 — one index-behind template

`apps/loops/src/loops/commands/store.py` `_run_verify`. The two forked
paragraphs became one template with three mode-conditional terms (`log_name`,
`divergence`, `provenance`); the shared scaffolding — the "tick chain was NOT
walked" clause and the catch-up guidance — is written once. The comment above
now states the shared claim and names the per-mode difference instead of
repeating the reasoning twice.

Byte-identity checked mechanically, not by eye: both rendered strings were
compared against the originals character-for-character.

```
arrival identical: True
jsonl identical: True
```

The WP-4 tests that pin the arrival wording pass unchanged.

## S-7 — one newest-row ordering helper

Same file, `_read_absorption_state`. The `PRAGMA table_info(...)` +
`arrival_ordinal`-or-`rowid` ordering choice was written for facts and again
for ticks. One local `newest_first(table)` closure over `conn` serves both.
Kept local as ruled — not moved into the engine in this pass.

Ticks now runs `PRAGMA table_info(ticks)` twice (once for the existing
`window_hash` / `signature` probe, once inside the helper). That is one extra
schema read on a cold path, taken deliberately to keep the helper's signature
the ruling asked for.

**Line-number discrepancy (not silently corrected):** the ruling cited
`~:150-178` for `_read_absorption_state`; the function actually lives at
`:853-945`, with the duplicated probe at `~:899-922`. Same code, stale numbers.

## Suites

Run at HEAD of `slice/D-simplify`, working tree clean.

| suite | command | result | baseline |
| --- | --- | --- | --- |
| atoms | `uv run --package atoms pytest libs/atoms/tests -q` | 517 passed | 517 |
| engine | `uv run --package loops pytest libs/engine/tests -q` | 1894 passed, 1 skipped | 1893 + 1 skip (+1 = the new S-4 regression test) |
| sdk | `uv run --package sdk pytest libs/sdk/tests -q` | 324 passed | 324 |
| lang | `uv run --package lang pytest libs/lang/tests -q` | 655 passed | ~655 |
| store | `uv run --package store pytest libs/store/tests -q` | 176 passed | 176 |
| architecture | `uv run pytest tests/architecture -q` | 98 passed | 98 |
| apps/loops | `uv run --package loops pytest apps/loops/tests -q` | 2530 passed, 1 xfailed | 2530 + 1 xfail |

**Environment note on the engine suite:** the acceptance line specified
`uv run --package engine`. That environment cannot run this suite — `libs/engine`
does not depend on `libs/sign`, and `libs/engine/tests/conftest.py:67` imports
`sign` for the `Custodian` fixture, giving `10 failed, 1788 passed, 95 errors`.
Verified pre-existing: an unmodified tree (`git stash`) produces the identical
`10 failed, 1788 passed, 1 skipped, 95 errors`. Under `--package loops`, whose
environment has `sign`, the count is exactly the stated 1893 baseline, so that
is the environment used. `--with sign`, `--with-editable libs/sign`, and
`PYTHONPATH=libs/sign/src` were each tried and did not fix the `--package engine`
environment.

## Commits

```
032a3a90  S-1, S-2  coordinate-axis stamp helper + column index maps
7a0f2f1c  S-4       Projection cursor / events_folded split
5a384571  S-5       cursor normalisation + shared range query
913159f8  S-6, S-7  verify template + newest-row ordering helper
```
