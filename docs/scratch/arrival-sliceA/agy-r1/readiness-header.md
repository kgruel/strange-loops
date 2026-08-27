# Readiness review — <arc name>, round <N>

<!--
Skeleton for the final gemini-3.1-pro-high pass. Sections are ordered
deliberately: section 3 is what makes a verdict table possible at all.
Invoke with:

  agy --model=gemini-3.1-pro-high --sandbox --dangerously-skip-permissions \
      --add-dir="$WT_READONLY" --add-dir="$SCRATCH" --print-timeout=60m \
      --output-format=json --json-schema=<skill>/templates/findings.schema.json \
      -p "$(cat readiness-brief.md)" | tee "$SCRATCH/readiness-r<N>.json"
  git -C "$WT_READONLY" status --short    # sweep after, every round
-->

## 0. Working directory — read this first

Every command you run must be prefixed:

```
cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-readiness && <command>
```

Your shell tool does **not** start in that directory. Before anything else, run:

```
cd /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-readiness && pwd && git branch --show-current
```

Expected: `/private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-readiness` and branch `<branch>`. If either differs, **STOP** and
report it instead of proceeding. Reviewing the wrong tree is worse than doing
nothing.

**EXECUTE THIS YOURSELF — DO NOT DELEGATE.** There is no one to hand this to. If
you delegate, the review does not happen.

**Deliver ALL sections in one response. Do not stop to ask questions** — this is
print mode and there is no one to answer. If something is ambiguous, state your
assumption in `not_verified` and continue.

**Where you may write.** `/private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/agy-review` only. Do not create files anywhere under
`/private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-readiness` — no probe scripts, no patches, no scratch tests. Probes go in
`/private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/agy-review`; reference them by absolute path.

## 1. Anchor


NOTE: the worktree is DETACHED at 3d851bef (no branch name) — 'git branch
--show-current' prints nothing; verify with 'git rev-parse --short HEAD'
== 3d851bef instead. That is expected, proceed.

## 1. Anchor

- Repo (throwaway read-only worktree): /private/tmp/claude-501/-Users-kaygee-Code-loops/78d0f29f-a919-4097-b308-0b407f7e7949/scratchpad/wt-readiness
- Head 3d851bef = feat/arrival-libs; base: main (406cec31)
- Diff under review: git diff 406cec31...HEAD — the arrival wave-1 branch:
  slice 0 (arrival log primitive) + cut A (authority) + gate + r1 + s1
  simplify merges. ~30 commits, ~27 files.
- Arc: the arrival log becomes the canonical store substrate — slice 0 built
  the append-only primitive (grammar, genesis, ordinal coordinates, torn-tail,
  resume marks); cut A made it AUTHORITATIVE (residence mode, first verifier,
  ceremonies re-pointed, own_lineage as projection).
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


## 3. Unverified changes — your primary target

The 4-angle simplify pass ran AFTER the converged review round and touched
production code. A quality pass that touches code reopens the review behind
it — in a prior arc the simplify pass introduced that arc's ONLY regression,
and only the post-simplify re-review caught it. These commits have had ZERO
independent review; you are their first:

- 87d7f10c — index-currency family unified: _stamped_offset_current(index,
  log, offset_key) in jsonl_store now serves BOTH JsonlStore and ArrivalStore;
  probe collapsed _currency/_arrival_currency into one mode-dispatched
  function; _first_line_note(path, decode, label) factored under both content
  notes. RISK CLASS: a behavioral delta between the old per-store spellings
  smuggled into the shared one (timeout, empty-log ruling, error family).
- 7ad6c5b4 — _reconcile() now RETURNS the mark and both write paths consume
  it instead of re-reading; receipt pin-extras now spread from
  _genesis_payload's non-{protocol,documents} keys (arrival receipts stop
  faking chain_head/fact_cursor; legacy receipts claimed byte-identical —
  VERIFY that claim yourself); _STRUCTURAL_KINDS from grammar constants;
  _log_path field dissolved; genesis()/lineage() now route through the
  content-keyed memo (verify a TAMPERED genesis still refuses through the new
  path); walk()/walk_from() re-expressed as projections of walk_marked
  variants (verify the lazy/eager validation semantics did not shift).
- 3c265865 — test helpers deduplicated into conftest.py (verify no assertion
  weakened in the migration).
- d0770542 — the consumed-is-None gap-branch RESTORED after an overruled
  assert (a genesis mint landing in the reconcile→append gap is legal
  multi-process interleave), with a dedicated pin test. Verify the restored
  branch actually takes rollback + catch-up and the pin test pins it.

Also re-verify at this head (previously verified pre-simplify): legacy S3
byte-identity (jsonl/sqlite ceremonies unchanged vs main), apps/ diff-empty
vs main, and one adversarial pass over verify_authorship's clauses.

## 4. Known non-findings (do not report)

Rule 17 arch test fails only in checkouts with gitignored local docs
(pre-existing, filed); the ceremony fsync/COMMIT crash window (cut B's by
ruling); the is_jsonl_canonical shim + two Rule 18 allowlist entries
(accepted deviations, tripwired); adopt_lineage arrival-mode refusal (ruled);
keyless genesis deferred to the sidecar (verified not foreclosed); the
JsonlStore/ArrivalStore structural mirroring (deliberate, declared).

## 5. Verdict format

1. Findings ledger via the enforced JSON schema — each: severity (BLOCKING /
   behavior / test-strength / residue / docs / suspicion), file:line, claim,
   failure scenario, evidence (pasted command output; prose-only evidence
   caps severity at suspicion).
2. A per-commit PASS/FAIL verdict for the four §3 commits, with evidence.
3. Overall: CONVERGED or NOT CONVERGED.

Suites (run in the worktree): uv run pytest libs/engine/tests -q (expect 1679
passed, 1 skipped); tests/architecture (98 passed here); sdk 313; store 131;
apps 2525.
