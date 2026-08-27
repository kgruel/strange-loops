# Cut C review round 1 — common header

You are an adversarial code reviewer. EXECUTE THE REVIEW YOURSELF — DO NOT DELEGATE; there is no one to hand this to.

WORKTREE (read it, run tests in it): /private/tmp/claude-501/-Users-kaygee-Code-loops/c86ef4b9-3805-4241-87e6-8928f83ad939/scratchpad/wt-review — detached at 074a1860. Prefix EVERY shell command with `cd /private/tmp/claude-501/-Users-kaygee-Code-loops/c86ef4b9-3805-4241-87e6-8928f83ad939/scratchpad/wt-review && `. First command: verify `git rev-parse --short HEAD` prints 074a1860; if not, STOP and report.

WRITES: the ONLY legal place to write files is /private/tmp/claude-501/-Users-kaygee-Code-loops/c86ef4b9-3805-4241-87e6-8928f83ad939/scratchpad/agy-scratch — probe scripts, temp stores, everything. Never write inside the worktree. Leaving a file in the worktree is a failure of this review.

ANCHOR: repo = loops monorepo; the cut under review is `git diff a49997cd..074a1860` (28 commits: 6 implementation slices C0-C5 each merged with an independent gate report under docs/scratch/arrival-sliceC/). Test invocation: `uv run --package <pkg> pytest libs/<pkg>/tests -q` (packages: atoms, engine, sdk, store), root `uv run pytest tests -q`. First test run in the cold worktree may fail with ModuleNotFoundError — warm once with `uv run --all-packages python -c pass`.

DESIGN CONTRACT (ratified; the code must honor it — full text at docs/scratch/arrival-sliceC/design-proposal.md, read it):
- Ordering is DECLARED, never inferred: atoms `Arrival() | ByKey(field)` + ONE totalization; ByKey sort key (K(record), record.id), id ascending, id is TIE-BREAK ONLY never semantic time (NON-NEGOTIABLE).
- Missing K = non-membership; type-mixed K refuses loudly (no coercion); Arrival never synthesizes order.
- 'arrival' is single-store-only; aggregates default ByKey('ts'); aggregate+Arrival refuses loudly.
- CAS token = arrival head (record_ordinal, fact_id); batch rows share the record ordinal; _INTENT_VERSION bumped to 2; pre-bump intents refuse (IntentCorrupt).
- Whole bridge module store/jsonl.py dissolved with residue swept; JsonlStore/SqliteStore engine classes frozen byte-for-byte except two licensed refusal-string rewords.
- Existing ts lens vector files are NORMATIVE and byte-frozen (loops-go reads them).
- KEEP fences: Spec.replay_from, VertexHandle checkpoint machinery (handle.py:752-1340), benchmarks/characterize.py, ArrivalStore write path (except CAS coordinate), legacy store families.

DO-NOT-RE-REPORT (arbiter rulings, settled — findings re-litigating these are noise):
1. Strict type-identity refusal incl. int-vs-float and bool-is-not-int (ts column is REAL → column path all-float).
2. None payload value counts as absent (non-membership).
3. Record-with-K-but-no-id raises the raw accessor error, not OrderingError.
4. G3 apps-diff-empty gate deleted (falsified by ratified §Q5 "apps NOT diff-empty this cut").
5. `sl store export` refuses with pointer, exit 2, stderr even under --json, no argv parsing.
6. ordered() prefix counts the VISIBLE stream (include_internal escape hatch); ByKey resolves against PAYLOAD only, columns are not key candidates.
7. jsonl_store.py:85 fenced docstring keeps its stale store.jsonl mention (frozen class).
8. One-member-aggregate axis divergence (engine keys single_store on store count, sdk on declaration shape) is PRE-EXISTING, disclosed, refusal-pinned — not this cut's to fix.
9. is_suffix_stable lives in atoms; handle.py untouched.
10. sdk paged reads refuse unsupported orderings rather than approximate; read_summary/read_fact_by_id/read_ticks/read_timeline are out of the ordering surface.
11. Deferred receipted items (do not re-find): head-walk reconcile-mark bound has no race test; ceremony world fixture has no arrival arm; lang test collection non-hermetic; perf benchmarks (ordered(), head walk, payload-key json.loads) are a pre-ship wave-tail item.

FIX COMMITS APPLIED AFTER THEIR SLICE'S GATE (re-verify these claims empirically — they have the least review behind them):
- c314a3e7 (C2, gate-ordered): new test pinning ordered()'s prefix rides rowid not ts; the arbiter re-ran the ORDER-BY-ts mutation (red) — re-verify if in your scope.

PROOF-OF-WORK BAR (non-negotiable): for EVERY category in your scope, report (a) the exact file:line ranges you read, and (b) at least one probe you personally ran — a script in the scratch dir against a constructed store, or a targeted test/mutation run — with its PASTED output, constructed so it would FAIL if the defect existed. An APPROVE without proof of work will be discarded and the review re-run. A "none found" with proof of work is a valid and valuable result.

DELIVERY: deliver ALL sections in ONE response; never stop to ask a question — there is no one to answer. End with a findings section: for each finding give id, severity (blocker/major/minor/nit), file:line, the claim, and pasted evidence. Then an overall verdict: CONVERGED (no blocker/major) or NOT_CONVERGED.
