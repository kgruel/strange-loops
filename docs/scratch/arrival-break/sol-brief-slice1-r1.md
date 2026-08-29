# Sol review brief — arrival-break slice 1, round 1 (per-slice, LOW)

You are the cross-family reviewer for slice 1 of the arrival-break arc in the loops
monorepo. Review the slice diff adversarially for correctness against the design
contract below. You review and report — you do not fix, refactor, or commit. You may
run tests and scripts to verify claims empirically (preferred over reading alone).

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice/arrival-wire-v1`, tip `c63ae5fd` (5 commits over main).
- Diff spec: `git diff 68c7aa57...c63ae5fd` (main tip 68c7aa57). 23 files.
- Suites: run from the worktree root with its venv (`.venv/bin/python -m pytest ...`
  or `uv run pytest`). Per-package invocations for engine and store (they cannot share
  one pytest run — pre-existing `tests.conftest` collision, verified on main).

## 2. Design contract (what the code must honor)

From `decision:design/arrival-wire-v1-seam-triage` (parent, 2026-08-26): **body.t
DROPS** from arrival bodies (outer `k` discriminates; the LEGACY codec keeps `t` — the
slice-4 migration sidecar needs it); **tick envelope observer RE-SPELLED**; **dual
signature KEEPS, untouched**.

From the sub-ruling (fact `01M172M74FZ9E27V34QKDF7Y77`, 2026-08-29), binding:

1. **Candidate A**: tick envelope observer becomes a custody-producer label.
   Fact/batch/genesis/key envelope observers UNCHANGED — the field remains
   signer-selection plumbing for signed kinds (`fact_signer_for` resolves the AUTHOR's
   per-observer key by it; `_resolve` verifies against it). No re-keying of anything.
2. **The label = the destination log's genesis observer**, at BOTH mint sites in one
   change: `engine/arrival_store.py` (the fact/tick ternary in `_write`) AND
   `store/merge.py` `_entry_for` (second, independently-encoded mint site).
3. **Tick outer signatures DEFERRED explicitly** — wire v1 pins with ticks
   outer-unsigned ON PURPOSE. No tick signing may have been added.
4. **Batch same-observer grammar ENFORCED** — "all rows in a batch share one observer"
   is a wire-grammar refusal at the arrival seam (arrival-only; deliberately NOT added
   to the legacy line codec).
5. **Outer-sig law**: the outer signature is the PER-LINEAGE arrival-content signature;
   the inner fact-domain signature is what travels through re-custody. protocol.html §06
   was rewritten to state this.

**NON-NEGOTIABLE**: no preserved inner signature may be invalidated. Inner fact
commitments never covered `t` or the envelope observer. `content_commitment`,
`arrival.py`, and `libs/custody/` must be absent from the diff.

Non-goals (finding if violated): fact/batch/genesis/key observer semantics; tick
signing; commitment shape; `arrival_ordinal`/`arrival_seq` renames; legacy codec's `t`;
`FileStore`/`file_writer.py`; anything from `.loops/`.

## 3. Unverified fixes — verify these empirically, top priority

| commit | claim | your job |
|---|---|---|
| 8aa4c619 (pre-slice, on main) | Arbiter-applied, no independent gate yet: engine tests' masked dependency on `sign` fixed by declaring it in engine `dependency-groups.dev` + `tool.uv.sources`; runtime injection boundary untouched. Arbiter mutation-verified in a minimal `UV_PROJECT_ENVIRONMENT` closure. | This is the arc's first sol brief, so you are this fix's only independent verification. Confirm the dep declaration exists, engine tests import sign successfully, and the RUNTIME engine package does not depend on sign. |
| c63ae5fd | Gate finding GF-1: docstring of `test_encode_decode_encode_is_byte_stable` claimed to pin "key order" while asserting under `sort_keys=True`; docstring corrected, no code change. | Confirm the commit touches only the docstring and the new text matches what the assertion actually checks. |

## 4. Prior review state (independent gate, already run)

An independent gate re-ran the full oracle from scratch and PASSed the slice: all
suites green with reconciled counts (engine 1937p+1s, store 177, architecture 98,
others baseline), all three mutation demonstrations reproduced (batch-rule revert → 2
named failures; merge-site revert and store-site revert → 1 named failure each, in
different packages), NON-NEGOTIABLE verified empirically and structurally, docs pass
verified. Its report: `docs/scratch/arrival-break/slice1-gate-report.md` on branch
`slice/arrival-wire-v1-gate`. Non-blocking findings GF-2 (Rule 18 completeness
ratchet, deferred to slice 2) and GF-3 (mixed-observer batch re-mint boundary,
deferred to slice 4) are already dispositioned — do not re-litigate their deferrals,
but DO flag anything that makes a deferral unsound.

## 5. Seeded review targets (static analysis surfaced these; assess, don't assume)

- `engine/arrival_body.py` — Pyright: body handled as `object` (`.get` on `object`,
  `Optional` flowing unnarrowed into `len`/`enumerate`/`set()` around lines 213–238).
  Question: is the type-looseness masking a real input-validation hole — e.g. a batch
  body whose `rows` is None, a non-list, or rows that are non-dicts: does the grammar
  REFUSE cleanly with the typed error, or crash with TypeError? Construct the inputs
  and check.
- `engine/jsonl_codec.py:499` — Pyright: unreachable code. Real dead branch introduced
  by the refactor, or analysis artifact? If real: is it residue of the
  `_validate`→`row_object_fault` fault-returning refactor?
- `store/merge.py:766` — Pyright: `origin` argument typed `Unknown | None` passed to a
  parameter typed `str` on the `Entry` constructor. Can a None origin actually reach it
  at runtime (what feeds that field on the merge path)?

## 6. Verdict format

Per item in §3: **PASS/FAIL + evidence** (command output where empirical).
New findings: numbered `SOL1-L-<n>`, each with file:line, severity
(BLOCKING/NON-BLOCKING), a concrete failure scenario, and the evidence you used.
Then one overall line: **CONVERGED** (no blocking findings, contract honored) or
**NOT CONVERGED** (with the blocking list).
