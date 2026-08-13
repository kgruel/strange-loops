# S5 impl report — bounded, cursor-bearing generic fact query

- **Branch**: `slice/s5-bounded-fact-query` (off `libs-handoff-wave` @ a39028e8)
- **Worktree**: `/Users/kaygee/Code/loops/.claude/worktrees/agent-a8e4642a8728b0406`
- **Commit**: single feat commit (this report amended in): `feat(engine): bounded, cursor-bearing generic fact query — StoreReader.query_facts + FactPage`

## What shipped

`StoreReader.query_facts(*, limit, before, after, kind, observer, include_internal, order)`
→ `FactPage(items, next, truncated, order)` in `libs/engine/src/engine/store_reader.py`,
plus `vertex_reader.vertex_query_facts(...)` and `engine` exports (`FactPage`,
`vertex_query_facts`).

Key contract decisions (per the hard constraints):

1. **The page cursor IS the shipped 0.8.0 `WitnessPosition`** — no second
   cursor type (Sol's `FactCursor` sketch not implemented). Ordering
   authority is the witness axis (`rowid`, append order). Fact ids are never
   ordered or compared (A3 — mixed uuid4/ULID eras); they enter only as
   primary-key lookups when resolving the next-page position.
2. **`before`/`after` are exclusive rowid bounds** (`rowid <` / `rowid >`),
   composable into a window. Each incoming cursor is A10-verified via the
   shipped `verify_position_for_store` before its rowid is applied — foreign
   unadopted cursors refuse with `WitnessLineageMismatch`; same-lineage
   sibling-store cursors re-resolve. (Verification runs outside the read
   transaction; safe because rowids are immutable in an append-only store.)
3. **One read snapshot**: the page SELECT and the next-cursor resolution run
   inside one `BEGIN DEFERRED`, joining an enclosing `StoreReader.snapshot()`
   bracket when the caller holds one (checked via `conn.in_transaction`) —
   the same-connection-is-not-same-snapshot bug class stays dead. Truncation
   is a `limit+1` over-fetch; `next` is the last item's `WitnessPosition`,
   `None` when the walk is complete.
4. **Filters** all applied in SQL so `limit` bounds *matching* rows: `kind`
   uses the `facts_between` dotted-subtree rule; `observer` implements
   `observer_matches` namespacing semantics with a wildcard-free suffix
   compare (`substr`), immune to LIKE/GLOB metacharacters in names;
   `_decl.*` excluded by default (SPEC §9.4), `include_internal=True` defeats.
5. **Aggregates**: no meaningful aggregate cursor exists in 0.8.0 — confirmed
   (A1/A9: witness order is per-member; aggregate `at=` reads refuse in
   `vertex_fold`/`vertex_facts`). `vertex_query_facts` therefore **raises**
   the typed `WitnessAggregateUnsupported` rather than returning a result
   object. The task wording says "return a typed unsupported result"; raising
   the shipped typed exception is the deliberate call — hard constraint (1)
   says the shipped 0.8.0 contract wins, and that contract signals aggregate
   refusal by raising this exact type at every existing seam.

## Deviations / extensions to name

- **`witness.py` extended (additively)**: `group_boundary` gained an
  `"allow"` mode (default `"refuse"` untouched; `"floor"` untouched). A
  pagination cursor is a read-progress token, not a fold cut — with
  `include_internal=True`, a page may legitimately end ON a `_decl.*`
  ceremony row, where `"refuse"` would make the page unaddressable and
  `"floor"` would snap and create dups/gaps, breaking the pagination oracle.
  Documented in the mode's docstring with an explicit "never use for a fold
  cut" warning. Pinned by `test_internal_pagination_equivalence`.
- `query_facts` calls the module-private
  `witness._resolve_witness_position_on_conn` cross-module — deliberate: it
  is the existing shared-connection/shared-snapshot seam (extracted for
  exactly this purpose in 0.9.0 S6), and calling the public
  `resolve_witness_position` would open a second connection = second
  snapshot, reintroducing the race the slice exists to avoid.
- `FactPage.order` echoes the walk direction so a consumer holding only the
  page knows whether `next` feeds `before` (newest) or `after` (oldest).

## Oracle results

`libs/engine/tests/test_query_facts.py` — 24 tests, all green:

- **Pagination-vs-full-scan equivalence on mixed id eras**: store of 53
  facts whose ids are constructed so lexicographic id order is the exact
  REVERSE of append order (alternating uuid4-shaped / ULID-shaped ids), and
  ts is non-monotonic (every 7th fact backdated). Paged walks (pages of
  1/7/10/53/100, both orders) equal the full scan exactly — no dups, no
  gaps. A companion test asserts the adversarial construction actually
  bites (id order ≠ append order ≠ ts order) and that the full scan IS
  append order.
- **Snapshot consistency**: inside one `snapshot()` bracket, a concurrent
  `SqliteStore` writer appending 5 facts mid-walk is invisible — the page
  stream equals the pre-write full scan, both orders. Plus: a `newest` walk
  is cursor-immune to appends even *without* the bracket (new rows land at
  higher rowids than any `before` cursor).
- Filters (kind subtree, observer namespacing both directions, internal
  exclusion/inclusion), before+after window composition, exact-limit
  non-truncation, A10 foreign-cursor refusal, invalid-arg refusal,
  vertex-level instance/aggregate/missing-store behavior.

## Test runs

- `uv run --package engine pytest libs/engine/tests` → **1309 passed, 4 failed** —
  all 4 failures are `test_topology.py::TestTopologyCacheResolution`, verified
  **pre-existing** by `git stash -u` on the clean base tree (same 4 fail there;
  environmental — worktrees are emptier than the main checkout).
- `./dev check` (root — architecture ratchet, `uv run pytest tests/`) → **59 passed**.
- New file alone: 24 passed.
