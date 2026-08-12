# sol HIGH review — 0.10.0 wave round 1 (S1 + rider substrate)

Review the full diff `git diff main...feat/010-surfacing` in /Users/kaygee/Code/loops.
You are the adversarial reviewer in an established cross-family pipeline: every
finding needs a REPRODUCED failure scenario (command or test), classified P1
(blocks merge) / P2 (fix-in-wave) / note. Kill your own suspicions explicitly —
"checked X, holds because Y" is a valuable verdict.

## What the wave contains
1. S1 contract migration (5212ede, db94c42): apps/tasks off render=(ctx,data)
   onto renderer= 3-arg lenses; piped= kwarg DELETED — register IS the offered
   width (width=None = viewportless/agent, int = viewport); Rule 12 in
   tests/test_architecture.py (two tests, AST walk, anti-vacuity asserts).
2. Live-edge disclosure substrate (763c648): StoreReader.live_edge() on the
   newest chained tick's fact_cursor boundary (append axis); FoldState.edge_facts/
   edge_since stamped in vertex_fold (head-only, suppressed under at/as_of);
   Window threading + explicit --json keys + fields(Window) coverage ratchet.
3. APPS derivation (b10515f): hand tuple -> apps/*/src packages with __init__.py.
4. docs/scratch/010-wave/loops-go-grounding.md — docs only, skip unless a claim
   about code is checkably wrong.

## Attack surface, in priority order
1. RATCHETS GET THEIR OWN VERIFICATION ROUND (0.9.0 lesson: 3/4 ratchets fell
   to constructed evasions). Construct evasions for: Rule 12's run_cli/renderer
   walk and its piped-parameter scan; the fields(Window) wire-coverage test;
   the APPS derivation. An evasion that passes the suite is a finding.
2. The register collapse: any caller (including direct/library callers, hooks,
   local lenses, autoresearch re-exports) that relied on piped=False with
   width=None for human headers. Three lenses (graph/confluence/horizon)
   previously lacked the width-fallback and changed direct-call behavior —
   assess blast radius.
3. live_edge() semantics: unresolvable cursor, empty-string sentinel, pre-chain
   schema, _decl.*-only edges, aggregation vertices, WitnessFold path — does any
   path leak a head-scoped edge into a historical read, or return a lying count?
   Also: TOCTOU between the boundary query and the count query (same connection
   is not same snapshot — StoreReader has no transaction; is that a real race here?).
4. Cross-slice seam: S1's lens signature changes vs the Window/edge additions —
   any lens reading window fields it now must not assume, any json contract drift.
5. apps/tasks migration fidelity: 7 sites, task-list delegation, the dashboard
   _render_minimal truncate guard — does the guard change TTY output?

Write findings to /Users/kaygee/Code/loops/docs/scratch/010-wave/sol-review-r1.md
(create it), then print the findings summary to stdout as well.
