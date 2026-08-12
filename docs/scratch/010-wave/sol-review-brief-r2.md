# sol HIGH review — 0.10.0 wave round 2 (verification)

/Users/kaygee/Code/loops, branch feat/010-surfacing. Round 1 found 0 P1 / 5 P2 / 1 note
(docs/scratch/010-wave/sol-review-r1.md — YOUR findings). The fix round landed as
merge 'merge(010-fix-r1)' (commits 922c9f4, a13ffc1, 0944b4e, bba7c48).
Diff to verify: git diff b10515f...HEAD

This is the VERIFICATION round. For each r1 finding:
1. Re-run your original repro/evasion — confirm it now FAILS (is caught).
2. CONSTRUCT NEW EVASIONS you did not use in r1. A hardened ratchet that survives
   only its known evasions is regression-shaped. Specifically attack:
   - live_edge single-statement: is the statement-count ratchet itself evadable
     (e.g. a single statement that still reads incoherently, executescript,
     a second cursor)? Is the PRAGMA-drift argument sound?
   - Rule 12 scope model: new alias forms (tuple unpacking, walrus, dict/getattr
     indirection, decorator wrapping, functools.partial), scope-resolution edge
     cases (class bodies, comprehension scopes), import resolution >4 hops,
     the _RENDERER_BINDING_EXCEPTIONS allowlist mechanics (shrink-only enforced?).
   - Window wire fidelity: sentinel scheme blind spots (fields where the encoder
     applies a transform the sentinel survives coincidentally).
   - APPS derivation: remaining exclusion holes (nested namespace dirs, src
     layouts without src/, case sensitivity).
3. Verdict per finding: CLOSED / PARTIAL (what remains) / NOT-CLOSED (repro).

Also assess the two flagged residues (verdict + priority, no fix needed):
- vertex_fold() same-class snapshot race (thread:vertex-fold-snapshot-coherence)
- the RATCHETS.md generalizations ("a documented known boundary is an advertised
  hole"; "cannot-resolve must be loud") — sound doctrine or overreach?

Write to /Users/kaygee/Code/loops/docs/scratch/010-wave/sol-review-r2.md and print
a summary to stdout. All suites must be green when you finish (run them).
