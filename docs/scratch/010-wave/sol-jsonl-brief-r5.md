# sol HIGH review — 0.10.0 roll-ins, round 5 (convergence check)

Repo: /Users/kaygee/Code/loops, branch feat/010-surfacing.
Scope: ONLY the three commits since your r4 (`git diff 3963ad6...HEAD`):
196dadb (scope the offset-behind verdict), e2c8432 (pinning tests), 321698d
(absolute store= required). Item 2 converged in your r4; everything earlier
is converged/dispositioned. Full sweep green: engine 1289, loops 2442+1xf,
tasks 269, store 111, arch 59.

Verify each fix against your own r4 probes:

1. MAJOR fix (196dadb): claim-scoping, not detection-widening. Check.lag →
   Check.beyond_offset, AgreementReport.lag_only → index_behind (a location
   claim, never a benignity claim); "not evidence of tampering" removed
   repo-wide; offset-behind detail now recommends --deep to judge the
   suffix; marker-rewound-over-indexed-rows positive detection untouched.
   Re-run BOTH your r4 repros (index-only: rewind+delete-first-suffix-row+
   adjust-count+poison-later-row; log-only: same-length interior edit + one
   well-formed appended row): rc=1, no benignity language, --deep
   recommended AND --deep names the tampered row. Also probe: does any
   OTHER output path (stats/ticks gate refusal, --json shapes, painted
   lenses) still carry a benignity/innocence claim for offset-behind
   states? Grep + render, both registers (tty/piped).
2. MINOR fix (e2c8432 tests + 196dadb walk): deep walk continues past
   content divergences (collector capped at 10 reported, exact count),
   feeds every decodable row to the chain walk; undecodable line → verdict
   "chain walk aborted at line N", never ok=True over zero ticks. Re-run
   your edited-first-fact probe: divergence AND a real chain verdict.
3. MINOR fix (321698d): relative store= override now raises ValueError
   naming the vertex-dir-vs-cwd ambiguity. Check in-tree callers all pass
   absolute paths and the ratchet still holds.

Ground rules: empirical, scratch dirs, do NOT touch .loops/data/ (read-only
verify against the live store fine). Report per-fix verdict, any new
finding, and CONVERGED / NOT CONVERGED for the full roll-in scope.
