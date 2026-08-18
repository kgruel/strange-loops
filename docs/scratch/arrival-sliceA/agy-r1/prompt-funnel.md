WORKING DIRECTORY: /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-funnel
Every command you run MUST be prefixed: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-funnel && <command>
First action: run `cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-funnel && pwd && git log --oneline -1` and confirm the
head commit message mentions arrival/sol brief. If the directory or head is not
as expected, STOP and report — editing the wrong tree is worse than doing
nothing.

EXECUTE YOURSELF — DO NOT DELEGATE. There is no one to hand this to; if you
delegate, the work does not happen.

ROLE: adversarial REVIEWER of already-written code. You are the cross-family
reviewer (the implementer was a Claude agent): your job is to find what the
author family characteristically misses. You produce FINDINGS, not fixes.

FENCE: you may run suites, write scratch probe scripts under /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-funnel/probe_*,
and temporarily mutate production code to demonstrate a test gap — but every
mutation MUST be restored, and your final pasted evidence must include
`cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-funnel && git status --porcelain` and `git diff --stat` output showing a
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

SUITES available: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-funnel && uv run pytest libs/engine/tests -q (expect
1678 passed, 1 skipped) ; uv run pytest tests/architecture -q (expect 98
passed in this worktree).

OUTPUT: your prose review (evidence transcript), then the findings ledger via
the enforced JSON schema. Findings each: id, severity (BLOCKING / behavior /
test-strength / residue / docs / suspicion), file:line, claim, failure
scenario, evidence. End prose with VERDICT: CONVERGED (zero findings) or NOT
CONVERGED.

SCOPE C — THE FUNNEL, DISPATCH, RATCHET, AND THE UNREVIEWED r1 COMMITS.

Review: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-funnel && git diff 3b303d5d..HEAD -- libs/engine/src/engine/residence.py libs/engine/src/engine/probe.py libs/engine/src/engine/compiler.py libs/engine/src/engine/preflight.py libs/engine/src/engine/witness.py libs/store tests/architecture/test_rule_18_arrival_vocabulary_denylist.py libs/engine/CLAUDE.md libs/engine/tests/test_residence.py libs/engine/tests/test_probe_arrival_matrix.py libs/engine/tests/test_arrival_store.py
And specifically the two commits nobody has independently reviewed:
git show 9ec762fb ; git show bba86e70

Attack surfaces, in priority order:
1. Commit 9ec762fb (test-type fixes): verify it changed NO test semantics — a
   type-narrowing that weakens an assertion (e.g. an int() coercion that
   masks a None, a narrowed branch that skips an assert) is a real finding
   class. Diff each hunk against the assertion it feeds.
2. canonical_mode()/canonical_for(): the three-arm dispatch. Probe: a
   .arrival locator whose sibling .db does not exist; a path with BOTH
   .arrival and .jsonl siblings at every entry point (probe/residence/
   preflight/compiler) — exactly ONE custody holder must be identified,
   arrival wins, and all entry points must AGREE (the half-migrated matrix
   test claims this; find the entry point it missed). A caller that still
   assumes the old .jsonl/.db bijection.
3. The funnel sweep completeness: grep the libs tree for retired idioms —
   is_jsonl_canonical callers outside the sanctioned shim, direct
   suffix-comparison against ".jsonl"/".db" that bypasses canonical_mode,
   log_path_for stragglers. Residue findings are exactly what adversarial
   rounds miss.
4. Rule 18: _SCAN_TARGETS grew (residence, probe, arrival_store); exactly two
   commented _ALLOWED entries. Probe the ratchet: does it actually bite on
   each new target (introduce a denied term in a scratch copy, run, restore)?
   Is the D1 shim's allowlist entry scoped to the shim line only?
5. probe.py's .arrival corroboration: stays within pure-inspection (no
   constructor traps, no file creation — verify with strace-level reasoning
   or targeted probes); derived_log classification correctness.
