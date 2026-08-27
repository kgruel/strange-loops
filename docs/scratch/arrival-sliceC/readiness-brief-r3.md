# Cut C readiness review r3 — gemini-3.1-pro (focused convergence round)

Round-3 READINESS reviewer for Cut C. Rounds 1-2: docs/scratch/arrival-sliceC/readiness-r{1,2}.json. All fixes PASS. R2's single finding F2 was DISPOSITIONED REFUTED by the arbiter; your first charge is to adversarially audit that refutation. EXECUTE YOURSELF — DO NOT DELEGATE. Deliver ALL sections in ONE response; never stop to ask.

WORKTREE (disposable): /private/tmp/claude-501/-Users-kaygee-Code-loops/c86ef4b9-3805-4241-87e6-8928f83ad939/scratchpad/wt-readiness2 — detached at eefee22f (same tree as r2; the two commits since are scratch docs only). Verify HEAD first. ONLY legal write location: .../scratchpad/agy-scratch.

CONTEXT: briefs r1+r2 rulings all stand (read docs/scratch/arrival-sliceC/readiness-brief-r1.md and -r2.md). Cut diff: a49997cd..eefee22f.

CHARGE 1 — audit the F2 refutation. The arbiter's claim: fact_key_stats / key_prefixes / resolve_entity_id (store_reader.py) are FOLD-KEY surfaces — their `key` parameter arrives only from fold declarations (_get_key_field / fold_key_field at apps/loops ls.py:445, resolve.py:615/1030, sdk read.py:748/766), their documented contract is payload[key], and NO Ordering declaration routes into them; therefore payload-resolution of 'ts' there is pre-existing fold-vocabulary behavior, out of the ordering family, and F2 is not a cut defect. ATTACK THIS: trace every call path yourself; hunt for ANY path where an atoms Ordering (Arrival/ByKey) value or the family rule's key names flow into those three functions, or where a lens/ordering declaration and a fold declaration share a key that crosses vocabularies at runtime. If you find one, F2 revives — say so with the path. If not, state the refutation HOLDS with the evidence.

CHARGE 2 — zero-new-findings sweep: anything in the cut diff you have not yet credited in r1/r2, especially docs-vs-code truth (design-proposal GATE items 1-7 — check each is satisfied at eefee22f) and any surface the scoped rounds structurally missed. Do not re-report anything on the r1/r2 do-not-re-report lists or receipted deferrals.

PROOF-OF-WORK BAR: file:line ranges + at least one personally-run probe per charge with PASTED output. VERDICT: F2-refutation HOLDS/REVIVED with evidence; findings list; overall CONVERGED / NOT_CONVERGED.
