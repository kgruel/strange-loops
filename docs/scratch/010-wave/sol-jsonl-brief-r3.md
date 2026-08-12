# sol HIGH review — JSONL-canonical store, round 3 (convergence check)

Repo: /Users/kaygee/Code/loops, branch feat/010-surfacing.
Scope: ONLY the four commits since your r2 (`git diff b310e71...HEAD`):
87cb907 (reconcile before tick mint + doc residue), 1da3d6d (tasks writers
resolve the declared locator), b456ab8 (rebuild source read-only), 5874767
(fmt only). Everything before b310e71 is converged per your r2 (remediations
2/3/4/6 pass; simplify behavior-identical). Do not re-open converged ground
unless one of these commits regresses it.

Per-finding verification, empirically:

1. Your r1-blocker's tick variant (r2 finding 1): new seam
   `SqliteStore._sync_derived_state()` no-op, overridden in JsonlStore with
   `_reconcile()`, called at the top of `append_tick` before prev_row/
   fact-cursor/signed-era reads. Re-run your injection (fail _stamp after
   tick 2's fsync, mint tick 3): three ticks, true predecessors, verify
   clean, reopen clean. Also adjudicate the two documented non-guards:
   `append()` (reads no chain state; _write reconciles pre-INSERT) and
   `current_chain_head()` (only production caller absorb_genesis inside
   BEGIN IMMEDIATE, which refuses on jsonl-canonical anyway) — are those
   arguments sound, and is there any OTHER chain-state read path that mints
   or links from an unreconciled index (peer/forward/witness paths included)?

2. r2 finding 2: tasks writers now read the declaration through
   `_declared_store(name)`; deliberate split — declaration answers store
   KIND (extension), cwd answers WHERE (per-workspace contract, pinned by
   chdir tests). Verify the .jsonl-declared workspace write goes through
   the authority switch (canonical log gets JSON text, sibling .db derived),
   and check the split doesn't leak: any tasks path that resolves the
   packaged vertex dir for WHERE while claiming the declaration for KIND
   inconsistently.

3. r2 finding 3: rebuild_jsonl now validates the whole source read-only
   first (torn tail = ValueError, evidence unchanged; undecodable line =
   JsonlCodecError), creates the target only after clean parse, unlinks
   target+wal/shm on any failure. Re-run your two probes (torn-tail
   truncation; partial-target FileExistsError retry). Also check the
   validate-then-build gap: can the source change between _validate_log and
   construction in any supported flow, and does that matter for a
   migration-scoped tool?

4. r2 finding 5 doc corrections: accurate now?

Full sweep is green at HEAD (engine 1258, loops 2421+1xf, store 110, tasks
262, arch 59 + the rest). Scratch dirs only; do NOT touch .loops/data/.
Report: per-item verdict, any new findings file:line + severity + scenario,
and an explicit CONVERGED / NOT CONVERGED call for the whole arc.
