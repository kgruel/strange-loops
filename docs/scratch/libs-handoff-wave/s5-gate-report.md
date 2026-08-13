# S5 Gate Report — slice/s5-bounded-fact-query

Independent gate verification of commit 5ca29100 (base a39028e8, ancestor of
libs-handoff-wave confirmed). The impl report was treated as target, not
authority; all oracles re-run from scratch with independently written
adversarial scripts.

## Verdict table

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Full engine suite | PASS | 1309 passed, 4 failed — all 4 are `test_topology.py::TestTopologyCacheResolution` failing with `ModuleNotFoundError: No module named 'loops'`. Re-run on clean base a39028e8: identical 4 failures (environmental — `uv run --package engine` has no `loops` app on the path). Pre-existing claim VERIFIED. |
| 2 | Pagination-vs-full-scan equivalence | PASS | Own adversarial script: 211 facts, lexicographic id order strictly reverses append order, fully random ts, interleaved `_decl.*` rows, 3 observers. Both orders x page sizes 1/2/3/7/50/210/211/500, plus filtered walks (kind subtree, bare-observer, include_internal): paged == full scan == append-order ground truth every time; zero dups, zero gaps. `next` is None whenever `truncated` is False. |
| 3 | Snapshot consistency | PASS | Own test: writer appends 4 rows mid-walk on a separate connection; inside a `snapshot()` bracket the page stream equals the pre-write full scan, both orders. WITHOUT the bracket, `oldest` order tails the new appends (new row visible at end, prefix intact, no dups) — the documented "honest append-only reading", not a corruption; `newest` is cursor-immune (also pinned by the slice's own test). |
| 4 | A3 / A10 | PASS | New code's only ordering is `ORDER BY rowid {ASC\|DESC}` (store_reader.py:751); the one id comparison in the slice (test asserting `next.fact_id == last item id`) is equality, not ordering. `ORDER BY id` hits in store_reader are pre-existing lines (503/597/625), untouched. Foreign unadopted cursor: `WitnessLineageMismatch` raised (shipped test re-run + verify_position_for_store path read — before/after both routed through it before rowid is applied). |
| 5a | group_boundary pre-existing callers | PASS | Exhaustive grep: defaults stay `"refuse"` (witness.py:281,337); the only explicit `"floor"` callers are apps/loops/cli/witness_address.py:237,246, unchanged. |
| 5b | "allow" reachable only from pagination | PASS | Single call site in the codebase: store_reader.py:758 (`query_facts` next-cursor resolution). |
| 5c | Evasion: allow-cursor into fold/seal | PASS (defense in depth holds) | Constructed a real 3-row contiguous `_decl` ceremony (shared ts), minted a mid-ceremony cursor via `query_facts(include_internal=True, limit=1)` — mint succeeds (rowid 4 of span 4..6). Feeding it to `vertex_fold(at=...)` REFUSES with `MidReceiptGroupPosition`: declaration.py:322-326 re-checks `receipt_group_span` at apply time, independent of resolve-time mode. The fold path has its own guard; the allow mode cannot smuggle a partial-ceremony cut into a fold. Seal paths never consume WitnessPosition. |
| 5d | test_internal_pagination_equivalence pins the claim | **FAIL (test-strength gap, not a behavior bug)** | Mutation test: reverting the entire witness.py allow change leaves ALL 24 slice tests green — the fixture's `_decl` rows are singletons (i%11==5), and a singleton run is never mid-group, so the refuse path is never tripped. The allow mode IS load-bearing (my multi-row-ceremony walk: slice code walks 8/8 rows; reverted code raises `MidReceiptGroupPosition`), but no committed test pins it. Needed: a fixture with a contiguous multi-row `_decl` ceremony. |
| 6 | Private-symbol reach `witness._resolve_witness_position_on_conn` | PASS (report-only) | Matches the existing intra-engine seam pattern: canonical_audit.py:221 and jsonl_store.py:261 import `declaration._open_readonly`; handle.py:62 imports `declaration._read_own_lineage`. Same-package private sharing, not a cross-lib reach; the DAG ratchet is untouched. No public shape needed now; if a second module wants on-conn resolution, that is the promotion trigger. |
| 7 | LIBS_CHANGES.md P1 contract | PASS with noted deviations | Satisfied: bounded generic query, no unbounded scan, cursor preserves the store's real ordering contract (witness/rowid axis, ids never positions), items+next+truncated from one snapshot, kind/observer/include_internal/order filters, vertex composition. Deviations: (1) `FactCursor` → `WitnessPosition` — an upgrade, exactly what "avoid using IDs as witness positions" asks; one cursor species instead of two. (2) Aggregate: contract says "return a typed unsupported result"; impl RAISES typed `WitnessAggregateUnsupported`. Judgment: acceptable — consistent with the shipped 0.8.0 precedent (aggregate `at=` reads raise identically), typed and catchable; a sentinel FactPage variant would mint a second result species. CLI must catch-and-render, and the handoff reply to Sol should state the deviation. (3) `order` is `str` + runtime ValueError, not `Literal` — cosmetic. |

## Overall: PASS, with one required follow-up

Behavior verified correct under independent adversarial testing, including
the evasion probe. The single FAIL is test strength: the allow-mode behavior
that justifies touching shipped 0.8.0 witness machinery is not pinned by any
committed test (5d). Follow-up before wave merge: add a multi-row `_decl`
ceremony fixture to `test_query_facts.py` whose include_internal walk lands a
page boundary strictly inside the group, so the mutation dies.

## Addendum — blocking follow-up CLEARED (03f4d36f)

s5-impl's `test_page_boundary_strictly_inside_decl_ceremony_does_not_refuse`
independently re-verified by the gate: fixture asserts its middle `_decl` row
is genuinely mid-group (`receipt_group_span` non-None); with the witness.py
allow change reverted, exactly this test fails (`MidReceiptGroupPosition`),
24 others green; with it restored, full engine suite passes (1310 + the same
4 environmental topology failures). Item 5d flips to PASS.

**Final overall verdict: PASS, unconditional.**
