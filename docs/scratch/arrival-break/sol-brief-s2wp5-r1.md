# Sol review brief — arrival-break slice 2 / WP5 (contract-text execution), round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-2 WP5 — the slice's closing WP: it executed
the five contract-text rulings from the slice-gate sitting, plus the doc pass and
residue sweep. You review and report — no fixes, no commits. Run tests/scripts to
verify claims empirically.

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice/arrival-backend-contract` (the integrated slice-2 wave), tip `c33ce97e`.
- Diff to review: `git diff 3928632d...c33ce97e` — the arbiter's integration pin-flip
  (e7513164), WP5's six commits (f9e1ea19), and the gate-fix commit (c33ce97e).
- Suites: engine, store, lang per-package; `tests/architecture` from root.

## 2. Design contract (what the diff must honor)

The five sitting rulings, binding and quote-faithful (fact
`01M17M3RJJGC79KXH776Z4DQBR`, grep .loops/data/project.jsonl for it):

1. F2 "verification never repairs" enters backend-contract.html §06 as drafted in
   slice2-design-proposal.md §E — five sentences INCLUDING the absent⇒create carve-out.
2. Refusal root, narrow form: the five text-named conditions typed under
   `ContractRefusal`; deliberate absence typed `NotSupported` (replacing
   `NotImplementedError` at both WP1 sites); all else backend-specific by design.
3. `head_at` joins the op table — ten rows; Protocol + §03 row + §07 sentence +
   ten-row exact-equality surface literal; head_at NOT in LEDGER_MUTATIONS (it is a
   read).
4. §08 import op-row DEFERRED — no row; §08 prose tightened to state the property
   arrival_contract.py:333 cites.
5. §08 resumable-import debt marker, leading with the ruled sentence verbatim.

Plus: the doc pass may not leave any claim slice 2 did not build; residue swept in the
same change (CLAUDE.md updates, F2-question-is-open docstrings, WP4-F1 descriptor_for
clause).

## 3. Unverified fixes — verify empirically, top priority

| commit | claim | your job |
|---|---|---|
| e7513164 | ARBITER-APPLIED, no independent gate — you are its only independent verification. Integration seam: WP4's WP2-anticipating pin (`assert not isinstance(ledger, ArrivalLedger)` in test_arrival_registry.py) flipped to positive form once WP2's replicate/export made the Protocol satisfied; comment rewritten. The pre-fix state is the failing mutation (observed twice in the integrated suite). | Verify the flip is exactly one assertion + comment (diff 3928632d..e7513164); verify the positive assertion is now load-bearing (temporarily remove `replicate` from FileLedger → it fails); verify the comment's claim that the exact-surface equality lives in test_arrival_contract.py. |
| c33ce97e | WP5-gate F1: CLAUDE.md:~196 clause scoped ("adapter does not modify ArrivalStore, though the class did change in-slice"). | Confirm one file, one clause; confirm the scoped claim is true against `git diff main...c33ce97e -- libs/engine/src/engine/arrival_store.py`. |

## 4. Prior review state (gate, already run — do not re-litigate; flag if unsound)

WP5's gate PASSed 7/7 at f9e1ea19: its own strip-tags faithfulness diff of the §06
callout (verbatim match, five sentences), all five refusal subclasses verified real,
ten-row symmetric difference empty, all three mutation demos re-run (including the
rejected `compact` variant proving the impl's footnote), cross-doc sweep 3/3, the
`s2wp4-gate-f1` closure endorsed, and the raised-not-fixed wire-version finding
verified true at source and correctly left (one-surface-addition ruling). The F1
CLAUDE.md finding it raised is fixed in c33ce97e.

## 5. Seeded review targets

- The `NotSupported` change's blast: any caller anywhere (libs/, apps/, sdk/) that
  caught `NotImplementedError` from these paths and now behaves differently?
- The §08 prose tightening: does the new sentence accidentally promise import
  semantics beyond §08's default (empty replica / exact-agreement-through-head)?
- head_at's §03 row: Profile column says Authority/Replica — is that consistent with
  how the other read rows are profiled, and does FileLedger.head_at actually verify
  (not just read) the head it returns, as §07's "verified" requires?
- The debt marker: does its sentence create an obligation on the FILE backend the
  slice didn't build (it should bind "conforming limited backends" only — the file
  backend is unlimited by default).

## 6. Verdict format

Per §2 ruling: PASS/FAIL + evidence. §3 fixes: PASS/FAIL each. New findings:
`S2WP5-L-<n>`, file:line, severity (BLOCKING/NON-BLOCKING), concrete failure scenario,
evidence. Then one line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).
