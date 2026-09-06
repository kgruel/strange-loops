# sdk-aggregate — Fable review

Effort: low. Finished: 2026-09-06T02:47:01.371490+00:00.
Packet SHA-256: `561a096fe826c18935f740993a7c9612438289e3e3478026524feca8b9f978b3`.

Static reviewer output; findings still require primary triage.

**Verdict: one blocking finding (F1), two mediums, two lows. Ordering, same-lineage retention, cycle detection, close-on-refusal and detachment are correct as written.**

**F1. High — root with descriptor whose bounded declaration is not an aggregate yields a silently empty result.**
Location: `capture_aggregate` member selection (`if effective.discover is not None ... elif node.role != "root"`), reached via `has_local_descriptor_aggregate` → `_aggregate_summary/_state/_timeline`.
Trigger: local root file has a descriptor and a local `discover` (or `combine`), but the store's adopted declaration has no `discover` (uncommitted local edit, or a ceremony that removed it). Dispatch routes on local bytes; capture opens the root, finds `effective.discover is None`, and because `role == "root"` appends no member. `resolver.children` returns `()`.
Consequence: `fact_total == 0`, empty fold sections, `read_path="arrival-aggregate"`, no refusal, while the single-store path would have returned the store's facts under the honest bounded declaration. Local uncommitted bytes decide that committed data disappears. A non-root node in the same state is correctly retained as a plain member, so only the root is affected. Expected behavior is either a refusal on local/effective shape disagreement or retaining the root as a plain member; this stage should not return a successful empty view.

**F2. Medium — a storeless leaf member contributes nothing without refusal.**
Location: `capture_aggregate`, `node.descriptor is None` branch: the refusal fires only when `local_ast.store is not None`.
Trigger: a combine/discover child with `loops` but no `store` clause and no descriptor. It is treated like a storeless composition definition: `effective = _detached(local_ast)`, no member, no children.
Consequence: if such a leaf has implicit legacy storage under the existing read contract (the handoff's "implicit storage" case and legacy `_resolve_stores`), its facts are silently omitted and its specs still merge into the parent. The mixed-storage test only covers an explicit `store` path, so this gap is untested. The check should distinguish "composition definition without storage" from "leaf declaration with implicit storage", or refuse any storeless leaf.

**F3. Medium — own-overlay semantics are wired before being resolved against the legacy read contract.**
Location: `AggregateRead.streams` and `_eligible_members` overlay branches.
Behavior as implemented: for a kind the overlay declares, the structural axis collapses to `(overlay,)`, so that kind folds in the overlay's receipt order while sibling kinds fold `ByKey("ts")` across members. Overlay facts of kinds the overlay does not declare are dropped from folding entirely, yet `_aggregate_summary_from` counts them in `fact_total` and `all_events` shows them, and shadowed child rows are likewise counted and shown but not folded (the fixture asserts `fact_total == 2` with `n == 1`).
Consequence: per-kind axis switching and undeclared-kind dropping may or may not match legacy `vertex_read` overlay behavior. The handoff explicitly asked for this to be resolved before wiring; the snapshot's design text does not state which of these is intended. Not a bug I can prove from this snapshot, but it needs a recorded decision before acceptance.

**F4. Low — snapshot leak if detachment raises after a successful open.**
Location: `capture_aggregate` visit, `_CapturedNode(node, opened, _detached(effective), ...)`.
Trigger: `_effective_declaration` succeeds, then `documents_to_vertex` inside `_detached` raises. `opened` is neither in `captured_nodes` nor closed by the surrounding `try`, which only guards `_effective_declaration`.
Consequence: one open snapshot/query/ledger handle leaks on that error path. Moving `_detached` inside the guarded block, or appending before detaching, closes the gap. Unlikely in practice since `effective_declaration_from_documents` already consumed the same rows.

**F5. Low — root definition evidence can diverge from the opened root basis.**
Location: `open_aggregate_read` with `opened_root`, called from `read_summary/read_state/read_timeline`.
Trigger: the SDK reads and parses the root file once in `_arrival_descriptor`, opens it, then `_Resolver.root` rereads and refingerprints the file. If the file changes between the two reads, the root's `DefinitionEvidence` and `descriptor` come from bytes that were not the ones opened; if the new bytes drop the descriptor, the node takes the storeless branch and the supplied `opened_root` is silently ignored (closed by the caller, not leaked).
Consequence: evidence mismatch in a narrow race. Passing the already-read bytes/AST into the planner, or comparing the reread descriptor to the opened one and refusing on mismatch, removes it.

**Not findings (scoped out or verified):**
- Same-lineage repeated occurrences: keyed by `(path, locator, role)`, both retained, both opened, both closed. Correct.
- Cycle detection uses the active stack; the two-branch case is allowed. Correct.
- `AggregateCapture.close` runs in reverse and is idempotent with `OpenedRead.close`, so double-closing `opened_root` is safe.
- `members`/`definitions` return fresh detached ASTs on every access; `AggregateRead.root` and `_eligible_members` therefore rebuild the root AST per kind. Cost only, not correctness.
- `read_facts`, `read_ticks`, `read_fact_by_id`, `search_facts`, `resolve_entity` refuse or fall to legacy for aggregates; that is the stated deferral, not a defect here.
- No ordinary open bypasses rollback checks; `open_read` is the only entry.

Recommendation: F1 blocks acceptance. F2 and F3 need a decision recorded before the composition stage is called done.
