WORKING DIRECTORY: /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-store
Every command you run MUST be prefixed: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-store && <command>
First action: run `cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-store && pwd && git log --oneline -1` and confirm the
head commit message mentions arrival/sol brief. If the directory or head is not
as expected, STOP and report — editing the wrong tree is worse than doing
nothing.

EXECUTE YOURSELF — DO NOT DELEGATE. There is no one to hand this to; if you
delegate, the work does not happen.

ROLE: adversarial REVIEWER of already-written code. You are the cross-family
reviewer (the implementer was a Claude agent): your job is to find what the
author family characteristically misses. You produce FINDINGS, not fixes.

FENCE: you may run suites, write scratch probe scripts under /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-store/probe_*,
and temporarily mutate production code to demonstrate a test gap — but every
mutation MUST be restored, and your final pasted evidence must include
`cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-store && git status --porcelain` and `git diff --stat` output showing a
clean tree (probe_* files excepted). Do not commit. Do not fix anything. If you
believe something must change, that is a FINDING, not an edit.

PROOF-OF-WORK BAR: every finding carries a concrete failure scenario (inputs/
state -> wrong outcome) AND pasted command output demonstrating or supporting
it. A finding whose evidence is prose reasoning alone must say so explicitly
(severity capped at "suspicion"). No finding without a scenario. Negative
results ("I probed X this way, it held") are wanted in the prose too.

CONTRACT (the code must honor these; violations are findings):
- Record grammar (ratified): fields v,lin,ord,prev,at,k,observer,origin,body,
  sig?,rh in order; rh = sha256(JCS(record-without-rh)); prev chains rh; sig
  covers CONTENT ONLY (k,at,observer,origin,body), never the coordinate; torn
  tail truncates only under the append lock; corrupt interior always refuses;
  genesis at ordinal 0 and nowhere else, sig REQUIRED.
- Cut A (ratified 2026-08-18): adoption genesis body = {protocol, lineage,
  key}; the verifier rule VERBATIM: a key is valid at position N iff introduced
  at a position < N, OR N is the genesis position and the record is
  self-certifying; self-certification legal at ordinal 0 and NOWHERE else.
  EXCLUSIVITY: arrival keys resolve from (lineage, ordinal) coordinates ONLY —
  no libs code consults the .vertex for arrival keys; the apps-composed
  tick-chain verifier and .vertex observers{} are untouched. SEAM: a live-store
  genesis never carries a containment claim; cut A converts NOTHING — every
  ceremony change is fenced on the .arrival locator, legacy .jsonl/sqlite
  ceremony behavior identical. apps/ diff-empty vs main. The keyless-genesis
  question is DEFERRED — code/comments must not foreclose or half-build it.
- Carried: every path that ADOPTS an on-disk record as a premise validates at
  the adoption site (_authority_fault or an equivalently stated check). The
  accepted O(n) residual stays at its stated width (adoption proves decode+rh,
  placement, lineage match — NOT chain-to-genesis, NOT ordinal=physical
  position); no O(1) path silently narrows it. Caches keyed on validated input
  bytes only — path/inode/mtime keys are a known-rejected trap.

KNOWN NON-FINDINGS (do not report): Rule 17 arch test failing due to gitignored
local docs (pre-existing, filed); the ceremony crash window between log fsync
and sqlite COMMIT (disclosed, cut B's by ruling); test_jsonl_ceremonies
mechanical rename; the slice-0 minimal-genesis-body test replaced by the three
ratified body pins.

SUITES available: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-store && uv run pytest libs/engine/tests -q (expect
1678 passed, 1 skipped) ; uv run pytest tests/architecture -q (expect 98
passed in this worktree).

OUTPUT: your prose review (evidence transcript), then the findings ledger via
the enforced JSON schema. Findings each: id, severity (BLOCKING / behavior /
test-strength / residue / docs / suspicion), file:line, claim, failure
scenario, evidence. End prose with VERDICT: CONVERGED (zero findings) or NOT
CONVERGED.

SCOPE B — THE WRITE PATH AND CEREMONIES (libs/engine/src/engine/arrival_store.py, new file; plus the sqlite_store.py and jsonl_store.py hunks).

Review: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-store && git diff 3b303d5d..HEAD -- libs/engine/src/engine/arrival_store.py libs/engine/src/engine/sqlite_store.py libs/engine/src/engine/jsonl_store.py libs/engine/src/engine/ceremony.py libs/engine/tests/test_arrival_store.py libs/engine/tests/test_jsonl_ceremonies.py

Attack surfaces, in priority order:
1. The reconcile→append race fix (commit 850e679d, gate-verified once —
   fixes deserve MORE adversarial attention than first-cut code): _write's
   gap detection by the append's own coordinate (rollback + catch-up), and
   _ceremony_persist's append_marked(following=) CAS. Probe the shapes the
   fix does NOT cover: two ceremonies racing; a catch-up that itself races a
   third append; an interloper record arriving between the CAS check and the
   byte write (is the CAS actually under the append lock?); rollback leaving
   sqlite and the mark inconsistent.
2. S3 legacy identity: walk the sqlite_store/jsonl_store hunks hunk-by-hunk
   and find ANY behavior change reachable with a .jsonl or .db locator. The
   gate did this once; do it independently. absorb_genesis/adopt_lineage on
   legacy stores must be indistinguishable from 3b303d5d.
3. own_lineage as a projection: absorb_genesis stamps store_meta.own_lineage
   from ArrivalLog.lineage(). Probe: crash/partial states (log written, sqlite
   not; sqlite written, log not); re-open after each; does any state let the
   sqlite marker DISAGREE with the arrival genesis silently? (The fsync/COMMIT
   AmbiguousGenesis window is a known non-finding — probe the OTHER orderings.)
4. adopt_lineage's arrival-mode refusal: is it reachable and total (no path
   restamps), and does the refusal message stay accurate?
5. The resume mark (arrival_lineage, arrival_offset, arrival_ordinal) stamped
   from under-lock offsets: probe a stale/foreign/hostile mark at every
   consumption site; catch-up "consumes-or-refuses, never rebuilds" — find a
   path where it silently rebuilds or skips.
