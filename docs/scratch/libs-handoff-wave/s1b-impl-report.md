# S1b — Implementation report: JSONL declaration ceremonies

Branch: `slice/s1b-jsonl-ceremonies` (based on `libs-handoff-wave` @ bc7f91c5)
Contract: `docs/scratch/libs-handoff-wave/s1a-encoding-proposal.md`
(design:architecture/jsonl-declaration-ceremony-encoding, ratified)

## Deviations from the proposal

1. **Genesis crash-recovery matrix row (deliberate, pinned).** The proposal's
   matrix says a durable-but-unmarked genesis "self-heals" via the pre-marker
   adoption path (single genesis row, no marker → adopt as self) and a retry
   gets `GenesisExists`. That describes the singleton heuristic **removed as
   a hijack vector** by the absorb-closing re-review #1:
   `_own_lineage_in_txn` raises `AmbiguousGenesis` for ANY unmarked genesis
   rows; identity is claimed only by the explicit `adopt_lineage` ceremony.
   Reintroducing silent adoption would undo that ratchet, so actual behavior
   is: next open tails the row in → retry raises `AmbiguousGenesis` →
   `adopt_lineage()` heals → subsequent retry gets the honest
   `GenesisExists`. Oracle #2 is unaffected (its `GenesisExists` follows a
   *successful* genesis, marker stamped). Pinned by
   `test_fault_after_genesis_append_recovers_via_explicit_adoption`; emitted
   as `observation:implementation/s1b-genesis-selfheal-deviation`. Stale
   adoption-backfill prose in the `SqliteStore.absorb_genesis`/`absorb_edit`
   docstrings was corrected in the same change.

2. **"`_SPEC` gains one entry" — realized as a structural validator, not a
   `_Spec` row** (cosmetic). `_Spec` is field-shaped; `batch` is structural
   (rows array + cross-row rules), so it lives as `_validate_batch` +
   `_BATCH`/`_BATCH_KEYS`/`_MIN_BATCH_ROWS` beside `_SPEC`, dispatched on the
   same `"t"` discriminator, rules running in both directions as everywhere
   else in the codec.

3. **`libs/store/jsonl.py` touched (one decode site)** — outside the named
   engine surface but required: `_validate_log` (the `rebuild_jsonl`
   pre-flight) decoded via `deserialize_row` and would have refused every
   ceremony-bearing log. Switched to `deserialize_records`. Note:
   `export_jsonl` (sqlite→log direction) flattens ceremony rows to plain
   fact lines — index-equivalent, and D1's audit assertion binds batch lines
   only, so the exported log stays valid; batch grouping is a property of
   the live write path, not of exports.

4. **CLI test updated** (`apps/loops/tests/test_store_command.py`): the test
   pinning the blanket `absorb` refusal on JSONL vertices now pins the new
   reality — the ceremony runs and refuses at its own signing gate (rc 2,
   log byte-identical, no `jsonl-canonical` message).

## What landed (commits, in order)

- `feat(engine): jsonl codec batch envelope` — `serialize_batch` /
  `deserialize_records` / `_validate_batch`; ≥2 rows, fact records only
  (full `_validate` per row, verbatim payload TEXT), no ticks, no nesting,
  intra-batch dup-id refused, envelope keys exactly `t`/`rows`; same-ts NOT
  a codec rule (D1). N==1 collapses to a plain fact line. Exported via
  `engine/__init__`.
- `feat(engine): JSONL declaration ceremonies` — new `_ceremony_persist`
  seam in `SqliteStore` (no-op; called inside `BEGIN IMMEDIATE` after all
  CAS checks + staged INSERTs, before COMMIT) with both ceremonies calling
  `_sync_derived_state()` strictly BEFORE the transaction; `JsonlStore`
  overrides the seam (one plain line or one batch line, `_write`-style
  count/offset stamping from committed markers, fsync before commit) and
  drops its `absorb_genesis`/`absorb_edit` refusals; `_index_lines` and
  `_prefix_intact` expand batch rows; `reanchor` refusal kept (scope pin).
- `feat(engine,store): batch-aware audit + rebuild decode` —
  `_check_last_line` row-matches every inner row of a trailing batch;
  `_suffix_unindexed` probes by first inner row; `audit_deep` expands
  batches in order + D1 assertion (all-`_decl.*` batch with mixed ts →
  divergence, never a codec error); `store.jsonl._validate_log` decode.
- `test(engine): S1b acceptance oracle + golden fixtures` — see below.
- `docs+test: residue sweep` — root CLAUDE.md paragraph, CLI absorb test.

## Oracle results (all implemented as real tests; all pass)

| # | Test | Result |
|---|------|--------|
| 1 | `test_genesis_succeeds_and_log_carries_one_genesis_line` + `test_genesis_receipt_matches_sqlite_canonical_behavior` | pass |
| 2 | `test_second_genesis_refuses_and_log_is_byte_identical` | pass |
| 3 | `test_multi_change_ceremony_lands_as_one_batch_line_and_resolves` (round-trip via `resolve_declaration_documents` ≡ parse(edited); one ts) | pass |
| 4 | `test_single_change_ceremony_is_a_plain_fact_line` | pass |
| 5 | `test_stale_head_refuses_with_log_byte_identical` + `test_stale_head_allows_lawful_pre_cas_index_catch_up` (log sha-identical, orphan line lawfully indexed, offset == size) | pass |
| 6 | (a) `test_fault_before_append_leaves_log_untouched`; (b) `test_fault_after_append_before_commit_tails_full_ceremony` + genesis flavor (deviation pin); (c) `test_torn_batch_line_truncates_and_no_ceremony_happened` — each ends with a passing `audit_deep` | pass |
| 7 | `test_rebuild_from_log_reproduces_ceremony_rows_in_order` (identity re-derives via explicit adoption) + `test_rebuild_preserves_own_lineage_when_only_rows_cleared` | pass |
| 8 | `test_index_edit_to_any_row_of_a_trailing_batch_is_detected` (parametrized over both batch rows; audit detects, open answers with rebuild) | pass |
| 9 | `test_jsonl_golden_fixtures.py` — positive golden (genesis + 2 facts + 2-row batch + 3-row batch + sealing tick; exact record sequence, counts 8 facts/1 tick, rowid order == expanded log order, `audit_deep` ok) + 8 negative fixtures with pinned classes (empty rows, 1-row, nested, tick-in-batch, dup id, unknown key → `JsonlCodecError`; torn batch tail → truncation not error; mixed-ts `_decl` batch → audit divergence not codec error) | pass |
| 10 | `test_jsonl_store.py::test_reanchor_still_refuses_loudly` | pass |

Fixtures live in `libs/engine/tests/fixtures/jsonl/` with committed
provenance generators (`generate_golden.py` — run once, ids/ts minted;
`generate_negatives.py` — deterministic). They are the cross-language
contract for the Go conformance oracle.

## Gates

- `uv run --package engine pytest libs/engine/tests` — **1320 passed, 4
  failed**: the 4 are `test_topology.py::TestTopologyCacheResolution`
  failures **pre-existing on the wave base** (verified by stashing this
  slice's changes — they fail identically on bc7f91c5).
- `uv run --package store pytest libs/store/tests` — 111 passed.
- `uv run --package loops pytest apps/loops/tests` — 2521 passed, 1 xfailed.
- root `uv run pytest tests` (architecture) — 59 passed.
- `ruff check` over every touched file — clean.
