# Cut B — PROJECTIONS: readiness review (whole-cut pass)

You are the readiness reviewer for cut B of the arrival substrate arc. Sharpest pass in the pipeline: cross-cutting, seam-focused, adversarial. Deliver ALL sections in ONE response; do not stop to ask questions — there is no one to answer.

WORKING DIRECTORY (throwaway worktree, detached @ 40faf27a): /private/tmp/claude-501/wt-sliceB-ready — every command prefixed `cd /private/tmp/claude-501/wt-sliceB-ready && `. Verify HEAD first; if not 40faf27a, STOP.
WRITE FENCE: the ONLY legal write location is /private/tmp/claude-501/scratch-sliceB-ready. Never write inside the worktree. EXECUTE YOURSELF — DO NOT DELEGATE.

## 1. Anchor
Repo: loops monorepo, branch feat/arrival-libs. Cut B diff: `git diff 39ea67f5..40faf27a` (exclude docs/scratch from judgment — receipts). 23 non-merge commits. Suites at head: engine 1739p/1s (one corpus-dependent hypothesis case may fail — pre-existing at base, characterized), store 175, arch 98 (one local-only prose-ratchet failure exists ONLY in the main checkout, not here), sdk 313, apps 2525+1xf. apps/ and spec/ diff-empty.

## 2. Design contract
The ratified contract is the 22-invariant list ending docs/scratch/arrival-sliceB/design-proposal.md (decision:design/arrival-sliceB-projections; [NN] lines non-negotiable). Kyle-ratified amendments since: the Rule-18 allowlist carries ONE excused entry for merge.py's refusal import (ratified over the aliasing evasion); the named restamp verb dissolves into catch-up + re-derivation; a store-lib create arm refuses when the target's arrival-log sibling exists (guard unified in _conn, three call arms). Settled — do not re-litigate: byte-sorted derived log; set-not-multiset audit; driver union key = row id; jsonl-target merge refusal; jsonl_store outside Rule 18 scan targets; the catch-up race fix escalating the consume window; no perf benchmarks (carried pre-ship item).

## 3. Unverified fixes — re-verify these, empirically where possible
Committed AFTER the three-scope flash review round (which ran at 2f2ca0c4). No independent cross-family eyes have seen them:
- 4b60d041 — review F1: audit_derived_log streams digests (was materializing both sides). Claim: peak flat in record count (probe showed 21->7MB), linear only in largest single record; missing AND extra still caught.
- 98f721ca — review F2: the no-arrival-driver rule became behavioral (driver refuses arrival-record files, raises non-conflict error, target byte-untouched; -m exits non-zero). Claim: a mutation quietly unioning unparseable lines fails the new test.
- 648273aa — simplify M1: one classifier (_projects) behind rows_of_record/line_of_record; refusal message unified.
- d5affa1b — simplify M2: fixtures hoisted to engine conftest + NEW libs/store/tests/conftest.py.
- a4b14924 — simplify M3: codec grew object_of_fact_row/object_of_tick_row/object_of_batch (serialize_* now compositions); five json-string round-trip sites switched (incl. an UNDIRECTED fifth in _ceremony_persist); merge derives tick strip width from TICK_FIELDS/TICK_CHAIN_FIELDS; _read_index_source padding dropped (stripped tuple rides one short of full arity — verify the codec accepts that shape everywhere it lands).
- 63568b24 — simplify M4: _locked_head contextmanager preamble shared by append_marked_many/_append_under_lock.
- ee46c64f — simplify M5, THE ONE TO SCRUTINIZE HARDEST: catch_up fast path hoisted above BEGIN IMMEDIATE, predicate = mark-offset-equals-log-size AND own_lineage-present. DISCLOSED BEHAVIOR DELTA: a bogus mark whose offset coincidentally equals log size, marker present, now opens "synced" — refusal deferred to the first real catch-up, not lost. Verify: (a) the race/gap suites still hold (run them; construct your own interleave if you can); (b) the crash-window recovery test passes (the own_lineage conjunct exists because a fast path skipping the restore broke it — verify the conjunct is sufficient, not just necessary: is there a state where own_lineage is present but restore/consume work remains that the fast path now skips?); (c) the deferred-refusal delta harms no verify/audit surface.
Arbiter-applied fixes: NONE this round (all fixes agent-applied and gated).

## 4. What to do
Read the whole diff. Then per unverified fix: PASS/FAIL with executed evidence (probes in the scratch dir; targeted suite runs). Then cross-cutting hunt at the seams flash-scoped review structurally missed: interactions BETWEEN the seven fixes, between cut B and cut A machinery (marks, ceremonies, CAS, witness), and unpinned semantics (as-of/ordering claims the code makes but no test pins). Standing item: candidate vocabulary-ratchet additions. Proof-of-work: file:line ranges read + at least one executed probe per unverified fix, pasted.

## 5. Verdict format
Per-fix table PASS/FAIL + evidence; new findings (id, severity, file:line, claim, evidence); overall CONVERGED / NOT_CONVERGED.
