# sol HIGH review — JSONL-canonical store (S1–S4), round 1

Repo: /Users/kaygee/Code/loops, branch feat/010-surfacing.
Diff under review: `git diff 71bc36c...HEAD` — 13 commits, S1→S4 of the
JSONL-canonical-store arc (design fact: `design/architecture/jsonl-canonical-store`,
ratified 2026-08-11).

## Design contract (what the code must honor)

- `.loops/data/<name>.jsonl` is the canonical store: one interleaved
  append-only log of facts and ticks (`"t": "fact"|"tick"` discriminator).
  `<name>.db` is a derived, rebuildable sqlite index.
- Authority at the write site: append = one flushed+fsynced JSONL line,
  receipt (fact id) minted there, sqlite indexed after. Crash between the
  two leaves sqlite behind; catch-up on open tails forward from a byte
  offset persisted in sqlite meta; untrustworthy offset → full rebuild.
- NON-NEGOTIABLE: `payload` rides in the line as the verbatim stored TEXT
  string. All commitment hashes (JCS/RFC8785 in `engine/sqlite_store.py`)
  embed payload verbatim — any re-serialization breaks signatures. A line
  round-tripped through the codec must re-derive identical
  `_fact_row_hash`/`_tick_row_hash`/`_fact_commitment_hash`.
- Read surface unchanged: all reads resolve to the sqlite index
  (`engine/residence.py` is the single translation point; extension of the
  `store` locator is the mode switch).
- Three eras exist in live stores (pre-chain, chained, signed) and must
  survive export/rebuild byte-exactly. The migration oracle (S2) proved
  this once: source and rebuilt chain heads both
  `de489b114e4674ea2c1c699f6968e53a10518293b73b9b057e9ae92c869d2ac9`.
- History-mutating ops (`absorb_edit`/`reanchor`/`absorb_genesis`) refuse
  on JSONL-canonical stores; out-of-band direct sqlite writes are detected
  on next open (refuse, don't rebuild over them).
- Single-writer for now. Multi-machine convergence is explicitly deferred.

## Review priority — unverified final fixes

Each slice ended with a fix commit applied AFTER its last internal review,
unverified. Re-verify these specifically, empirically where possible:

1. **5622eeb** (S3 r2 fix): per-handle count cache + rebuild-vs-FTS. The r2
   findings it answers: (a) two concurrently open JsonlStore handles each
   stamping a stale cached `_facts_indexed` could permanently brick the
   store via the out-of-band count check; (b) `_rebuild`'s `DELETE FROM
   facts` resets rowids, silently invalidating `facts_fts`/`fts_state`
   keyed on rowid — search returns wrong rows.
2. **4364832** (S4 r2 fix): (a) `_require_materialized_store` in
   `commands/store.py` used the pure resolver, so fresh-clone
   materialization was skipped; (b) `JsonlCanonicalUnsupported` escaping
   `_maybe_emit_change` made `sl add`/`sl rm` traceback after the .vertex
   was already mutated; (c) apps/tasks `store_path_for` hand-resolves the
   locator and writes through a plain store (was it fixed or documented?).
3. **Earlier confirmed classes, check for siblings the fixes missed**:
   out-of-band write sites (any remaining direct `SqliteStore(...)`
   construction on a path that may be a derived index — sweep apps/loops,
   apps/tasks, libs/store, hooks), REAL-affinity byte-compare traps,
   integrity-check windows that silently pass (the 64KB backward-scan
   escape), torn-line vs corrupt-line discrimination, orphan-line
   offset-stamping after a failed sqlite INSERT.

## Also in scope

- Correctness of `engine/jsonl_codec.py` canonical-decodability posture
  (NaN/Infinity/1e999 rejection, explicit-null signature, duplicate keys).
- `engine/residence.py` resolution seam: writers must resolve the
  canonical locator, readers the materialized index — any path that
  violates the asymmetry.
- The S4 migration as performed on the live store (project.vertex now
  points at project.jsonl; project.db.pre-jsonl backup exists; .gitignore
  exception in place; log intentionally untracked at 106 MiB —
  friction:jsonl-canonical-log-exceeds-git-limit is the follow-up, not a
  defect).
- Test honesty: do the crash-window/torn-line/offset tests actually
  exercise the failure, or pass vacuously?

## Ground rules

- Verify claims against the working tree, run tests where useful
  (`uv run --package engine pytest libs/engine/tests`, same for loops/store).
- Do NOT modify the live store `.loops/data/project.jsonl` /
  `project.db`. Scratch dirs for any live experiments.
- Report findings with file:line, severity (blocker/major/minor), and a
  concrete failure scenario each. Note explicitly which of the
  priority items you re-verified and their verdicts.
