# sol MEDIUM review — 0.10.0 wave, Track B batch (loops-go coordination)

Two repos, one batch, first review round.

- /Users/kaygee/Code/loops, branch feat/010-surfacing.
  Diff under review: `git diff 2cc0568...92451e0` (3 commits: 799c0a3 ledger
  doc, d296e08 generator relocation, 92451e0 family-3 generator).
- /Users/kaygee/Code/loops-go, branch feat/track-b-batch (off 94f7987).
  Diff under review: `git diff 94f7987...76c8378` (2 commits: bcb2308 residue
  sweep, 76c8378 tie vector + tie_test.go).

Context (read before the diff):
- docs/scratch/010-wave/loops-go-grounding.md — the batch's grounding; the
  ledger doc's claims must trace to it or to new evidence.
- docs/scratch/010-wave/track-b-impl-report.md — the implementer's own report.
  Its claims are the TARGET of this review, not its authority. Verify the load-
  bearing ones empirically; refute where you can.

SANDBOX NOTE: your write sandbox is the loops workdir + /tmp. loops-go is
READ-ONLY for you. To run or perturb Go tests: `cp -R /Users/kaygee/Code/loops-go
/tmp/tb-scratch` and work there with `GOCACHE=/tmp/gocache go test ./internal/conform/
-count=1 -v`. Never write the real loops-go tree.

## What to verify (adversarially, empirically where possible)

1. THE NEGATIVE CONTROL. The report claims tie.db discriminates (ts,id) replay
   from rowid replay, with expected + expected_rowid_order both shipped and the
   test asserting MATCH against one and MISMATCH against the other. In the /tmp
   scratch copy, re-run the implementer's own experiment: patch store/sqlite.go
   `ORDER BY ts, id` -> `ORDER BY rowid`, confirm all three facets go RED with
   the reported diffs; also try `ORDER BY id` (id-only sort — the report claims
   TIED/w pins ts as primary, so this must fail too) and an ORDER BY ts (no
   tie-break) run. If any perturbation stays green, that's a P1.
2. THE SELF-RETIRING SKIP. TestSameTSIDTieBreakTopNEviction claims to FAIL
   (not keep skipping) if Go's TopN ever starts agreeing with Python on the
   §4.6 eviction. Read its logic and construct the scenario: if the gap closed
   tomorrow, does this test actually notice, or can it skip forever? A skip
   that can't notice its premise expiring is a finding.
3. Q6's IMPOSSIBILITY CLAIM. The report asserts arrival order is recoverable
   from NEITHER the target map NOR the payload (_ts injected, id dropped), so
   no content-derived rule can close the §4.6 gap without a protocol change.
   Check atoms/decode.go + fold.go + store/sqlite.go: is there genuinely no
   channel carrying the id (or an order surrogate) into the fold layer? If a
   fix WAS available, the skip is mis-scoped.
4. GENERATOR RELOCATION FIDELITY. d296e08 claims move-not-rewrite (parity
   evidence in the commit message) and claims the sys.path hack is gone with
   no residue: grep BOTH repos for the old paths (`Code/loops-go/tools`,
   `sys.path.insert`, `Path.home()`), and check the moved code has no remaining
   hardcoded cross-repo guesses (the loops-go checkout must arrive as
   --loops-go/$LOOPS_GO_REPO). Run at least one generator against a /tmp
   destination to confirm they execute from committed state.
5. ARCH-RATCHET CONTACT. Top-level tools/ claims to sit outside every
   derivation the hardened arch suite walks. You hardened that suite (r1-r5) —
   is tools/ an evasion-shaped hole? Specifically: could production code
   under libs/ or apps/ import from tools/ without any rule noticing, and does
   anything ALREADY import tools/? If the containment story relies on "imported
   by nothing," check whether that's enforced or merely true today.
6. THE LEDGER DOC (docs/dev/loops-go-protocol-queue.md). Claim-check it against
   the grounding: five members with correct statuses/blockers, families table
   with the witness-reader prerequisite for 1/2/4/5, the four settled verdicts,
   Q1-Q3+Q5 recorded as OPEN, Q4 recorded as settled, plus the two new entries
   (Q6, fixture-schema drift). Flag anything it asserts that the grounding or
   the code contradicts, and anything material it silently drops.
7. SPEC.md EDITS. Verify the "status parentheticals only, no normative change"
   claim: read the loops-go SPEC diff hunk by hunk and classify each edit.
8. TIE FIXTURE INTERNALS. Ids are claimed 26-char with one ordering letter;
   ULID-shaped enough for any consumer? Check tie.expected.json is engine-
   generated (not hand-written) by regenerating via
   `uv run python tools/gen_tie_fixture.py --loops-go /tmp/tb-scratch` in the
   loops repo and diffing against the committed artifacts (provenance keys
   python_commit/generated_by may differ; anything else differing is a finding).

## Output

Write docs/scratch/010-wave/sol-review-track-b.md (no trailing whitespace):
per-item verdict (CONFIRMED / REFUTED / FINDING) with evidence, findings ranked
P1/P2/P3, and an overall verdict (MERGE-READY / FIX-ROUND-NEEDED). Print a
summary to stdout. Run `uv run pytest tests/ -q` in loops and the Go suite in
your scratch copy to confirm green at close. Change nothing outside your report
file and /tmp.
