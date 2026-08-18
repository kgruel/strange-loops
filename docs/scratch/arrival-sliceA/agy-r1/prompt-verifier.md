WORKING DIRECTORY: /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-verifier
Every command you run MUST be prefixed: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-verifier && <command>
First action: run `cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-verifier && pwd && git log --oneline -1` and confirm the
head commit message mentions arrival/sol brief. If the directory or head is not
as expected, STOP and report — editing the wrong tree is worse than doing
nothing.

EXECUTE YOURSELF — DO NOT DELEGATE. There is no one to hand this to; if you
delegate, the work does not happen.

ROLE: adversarial REVIEWER of already-written code. You are the cross-family
reviewer (the implementer was a Claude agent): your job is to find what the
author family characteristically misses. You produce FINDINGS, not fixes.

FENCE: you may run suites, write scratch probe scripts under /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-verifier/probe_*,
and temporarily mutate production code to demonstrate a test gap — but every
mutation MUST be restored, and your final pasted evidence must include
`cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-verifier && git status --porcelain` and `git diff --stat` output showing a
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

SUITES available: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-verifier && uv run pytest libs/engine/tests -q (expect
1678 passed, 1 skipped) ; uv run pytest tests/architecture -q (expect 98
passed in this worktree).

OUTPUT: your prose review (evidence transcript), then the findings ledger via
the enforced JSON schema. Findings each: id, severity (BLOCKING / behavior /
test-strength / residue / docs / suspicion), file:line, claim, failure
scenario, evidence. End prose with VERDICT: CONVERGED (zero findings) or NOT
CONVERGED.

SCOPE A — THE VERIFIER AND THE GRAMMAR GROWTH (libs/engine/src/engine/arrival.py).

Review the cut-A diff of arrival.py: cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-rev-verifier && git diff 3b303d5d..HEAD -- libs/engine/src/engine/arrival.py
Plus its tests: git diff 3b303d5d..HEAD -- libs/engine/tests/test_arrival_grammar.py libs/engine/tests/test_arrival_authority.py libs/engine/tests/test_arrival_gate.py

Attack surfaces, in priority order:
1. verify_authorship and the key-validity clause. Two arbiter-accepted
   deviations live here and deserve your hardest probes:
   - D5: the verifier binds keys to OBSERVERS (additive beyond the ruled
     positional clause). Probe: same key introduced for two observers; key
     rotation for one observer (old key verifying post-rotation records?);
     an introduction record whose BODY observer disagrees with its ENVELOPE
     observer; genesis-key impersonating a later observer; a record signed
     by a key introduced at the SAME ordinal (must refuse: < N, not <= N).
   - D3: genesis crypto self-certification is verify_authorship's FIRST ACT,
     not in _placement_fault. Probe whether any code path adopts/walks a
     genesis WITHOUT passing through verify_authorship — placement passes,
     crypto never checked. The impl report claims double-enforcement; find
     the single-enforcement path if one exists.
2. The grammar growth: mint's {protocol, lineage, key} body; _placement_fault's
   new genesis rules; whether a slice-0-era arrival file (genesis body WITHOUT
   key) is handled coherently (refused with teaching, or accepted — which, and
   is that choice stated anywhere, and does it foreclose the DEFERRED keyless
   question?).
3. New adoption sites in the diff: any read that takes an on-disk record as a
   premise without _authority_fault-equivalent validation at the site.
4. The O(n) residual: confirm no new whole-prefix walk landed on an O(1) path
   (append/head/resume complexity unchanged) and no new path pretends
   chain-to-genesis is proven when it is not.
5. Any new cache/memo: key must be validated input bytes.
