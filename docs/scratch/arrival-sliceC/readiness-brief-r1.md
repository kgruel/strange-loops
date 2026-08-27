# Cut C readiness review r1 — gemini-3.1-pro

You are the cross-cutting READINESS reviewer for Cut C (ORDERING). EXECUTE YOURSELF — DO NOT DELEGATE. Deliver ALL sections in ONE response; never stop to ask a question — there is no one to answer.

WORKTREE (disposable, yours): /private/tmp/claude-501/-Users-kaygee-Code-loops/c86ef4b9-3805-4241-87e6-8928f83ad939/scratchpad/wt-readiness — detached at 41937923. Prefix every command with `cd /private/tmp/claude-501/-Users-kaygee-Code-loops/c86ef4b9-3805-4241-87e6-8928f83ad939/scratchpad/wt-readiness && `. First: verify `git rev-parse --short HEAD` = 41937923; if not, STOP.
The ONLY legal place to write files is /private/tmp/claude-501/-Users-kaygee-Code-loops/c86ef4b9-3805-4241-87e6-8928f83ad939/scratchpad/agy-scratch — probes, temp stores, everything.

## 1. Anchor
Repo: loops monorepo. Cut: `git diff a49997cd..41937923` (36 commits — slices C0-C5 with independent gate reports, 3 converged flash-high review scopes with zero findings, a 4-angle simplify pass). Suites: `uv run --package <pkg> pytest libs/<pkg>/tests -q` for atoms/engine/sdk/store, root `uv run pytest tests -q`. Cold-env warm-up: `uv run --all-packages python -c pass` once first. Gate reports and review ledgers live under docs/scratch/arrival-sliceC/ in the worktree — read them; do not re-litigate what they settled.

## 2. Design contract (ratified decision:design/arrival-sliceC-ordering; full text docs/scratch/arrival-sliceC/design-proposal.md — READ IT FIRST)
Spine: ordering is DECLARED, never inferred. atoms `Arrival()|ByKey(field)` + ONE totalization (sort key (K, id), id ascending, TIE-BREAK ONLY — NON-NEGOTIABLE, never semantic time). Missing-K = non-membership; mixed-type K refuses; Arrival never synthesizes. 'arrival' single-store-only; aggregates default ByKey('ts'); aggregate+Arrival refuses. CAS token = arrival head (record_ordinal, fact_id), batch rows share ordinal, _INTENT_VERSION=2, pre-bump intents refuse. Bridge module store/jsonl.py wholly dissolved, residue swept. ts lens vectors NORMATIVE byte-frozen. KEEP fences: Spec.replay_from, handle.py:752-1340 checkpoint machinery, benchmarks, ArrivalStore write path (except CAS coordinate), legacy families byte-for-byte (except two licensed refusal rewords).

## 3. Do-not-re-report (settled rulings + receipted deferrals)
(1) strict type-identity refusal incl. int/float, bool≠int; (2) None-as-absent; (3) K-but-no-id → raw accessor error; (4) G3 gate deleted; (5) store export refuse-with-pointer exit 2; (6) prefix counts visible stream, ByKey payload-only; (7) jsonl_store.py:85 stale docstring frozen; (8) one-member-aggregate axis divergence pre-existing + refusal-pinned, and the refusal wording deliberately kept; (9) is_suffix_stable in atoms; (10) sdk paged reads refuse unsupported orderings; summary/by-id/ticks/timeline out of surface; (11) DEFERRED receipted: head-walk reconcile-mark race test, ceremony world fixture arrival arm, lang non-hermetic collection, perf benchmarks (ordered(), head walk, payload json.loads) pre-ship wave-tail; (12) single_store param two-meanings note receipted as design observation.

## 4. UNVERIFIED-FIXES ENUMERATION — your primary target. These commits landed AFTER their zone's last independent review; re-verify each empirically:
- c04af0de (simplify) — combined-read rowid sort gated on Arrival instead of alias count; _fetch_combined_rows signature grew an ordering param. VERIFY: single-store default and declared-Arrival outputs still byte-identical to old rowid semantics; ByKey single-store unaffected; no caller passes a stale arg.
- 8d44561c (simplify) — B017 fix, FrozenInstanceError assertion.
- 0ebcead1 (simplify) — totalize docstring + two new ratchet pins (no-id accessor error; missing-K never reaches id accessor). VERIFY the pins pin (mutate, red).
- ac335d66 + c7c898ee (simplify) — OrderingError attribution reword + Raises-section sweep. VERIFY: no conformance vector or test depended on the old prose; the new message is true for both failure elements.
- c314a3e7 (C2 post-gate) — prefix-rides-arrival test. Verified twice already; spot-check only if cheap.

## 5. Your charge — the cross-slice seams no scoped review saw
- END-TO-END: an ArrivalStore-backed vertex read through sdk read_facts/read_state with and without declared orderings; a full edit ceremony (plan→apply) on an arrival store exercising the new CAS coordinate; checkpoint+refresh interplay with the ordering taxonomy.
- SEAM HUNT: C1's primitive is consumed by C2 (ordered), C4 (combined read), C5 (generator + dispatch predicate). Hunt for semantic drift BETWEEN consumers: does any consumer's accessor pair make (K,id) mean something different (envelope vs payload resolution differs by surface — ordered() is payload-only, generate_lens resolves ts/id from envelope; is any surface's documented rule violated by another's)?
- The unverified fixes above, empirically.
- Anything the converged rounds structurally could not see (cross-slice, post-review commits, docs-vs-code truth).

## 6. Proof-of-work bar
Per section: exact file:line ranges read + at least one personally-run probe (script in the scratch dir against constructed stores, or targeted mutation/test run) with PASTED output, constructed to fail if the defect existed. An APPROVE without proof of work will be discarded.

## 7. Verdict format
Per unverified-fix: PASS/FAIL with evidence. Findings: id, severity (blocker/major/minor/nit), file:line, claim, pasted evidence. Overall: CONVERGED / NOT_CONVERGED.
