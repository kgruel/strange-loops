# Sol review brief — arrival-break slice 2 / WP1, round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-2 WP1 of the arrival-break arc in the loops
monorepo. Review the WP diff adversarially for correctness against the design contract.
You review and report — you do not fix, refactor, or commit. Run tests and scripts to
verify claims empirically (preferred over reading alone).

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice/arrival-backend-contract` (the slice-2 wave branch), tip `0d38c969`
  (7 commits over main `28654a96`).
- Diff spec: `git diff 28654a96...0d38c969`. 12 files (+~3300).
- Suites: per-package invocations (engine and store cannot share one pytest run —
  pre-existing conftest collision). `.venv/bin/python -m pytest libs/engine/tests -q`
  etc. from the worktree root.

## 2. Design contract (what the code must honor)

From `design:arrival-break-slice2-backend-contract` (ratified, fact
`01M177MHWHD5HM574VSTDE17X8`) §A/§D.1/§F, and the WP1 brief
(`docs/scratch/arrival-break/slice2-wp1-brief.md`):

1. `engine/arrival_contract.py`: contract types + `ArrivalLedger`/`ArrivalQuery`
   Protocols + typed refusals. **stdlib+typing only — no sqlite3, no runtime `arrival`
   import.**
2. `engine/arrival_file_backend.py`: `FileLedger`/`FileQuery` wrapping `ArrivalLog` +
   the projection. Protocol-incomplete on purpose: replicate/export declared, absent
   (WP2's); `capabilities()` must report honestly.
3. **F1**: both CAS sites (`append_marked` + `append_marked_many`) compare the FULL
   head; `following` is a `Head`; a bare int is REFUSED (`ArrivalError`, deliberately
   not `AppendRejected` so merge's retry loop cannot spin on a type error);
   `following=None` stays legal. A third caller (`ArrivalStore._ceremony_persist`) was
   found mid-WP and closed too (deviation D1): marks complete to full pins via
   `ArrivalLog.anchor`; an unvouched mark REFUSES rather than falling back unpinned.
4. Rule 18: both new modules in `_SCAN_TARGETS` + the completeness ratchet (glob
   `arrival*.py` vs the tuple, shrink-only `_NOT_SCANNED`, empty today).
5. Query-handle separation: no ledger-mutating op reachable from a query handle,
   derived from `LEDGER_MUTATIONS`, not hand-copied.

**NON-NEGOTIABLES**: the 14 arrival test files byte-unmodified (13 engine + store's
`test_arrival_merge.py`); wire codec + commitment machinery untouched (zero diff lines
in `encode_record`/`content_commitment`/`_canonical_bytes`/`build_record`); the ONLY
`ArrivalStore` behavior change is D1's pin completion; no registry module exists; no
consumer rewiring (nothing outside tests imports `arrival_file_backend`); Rule 4 holds
(no `engine`→`store` import).

## 3. Unverified fixes — verify empirically, top priority

| commit | claim | your job |
|---|---|---|
| 0d38c969 | Gate finding G1: the `anchor is None` → refuse branch survived mutation untested at BOTH sites. Fix: refusal tests at each site (engine `test_the_ceremony_refuses_an_unanchorable_mark_rather_than_unpinning`; store `test_arrival_merge_pin.py` ×3 with negative control and positive completion case) + two mutation demos (flip each raise to `return None` → named test fails). | Re-run both mutation demos yourself. Confirm the diff `70f7f7d3..0d38c969` touches only the two test files + the report. Confirm the negative control actually prevents an over-firing refusal (following=None legal). |

## 4. Prior review state (independent gate, already run)

Gate PASS, 0 blocking, at 70f7f7d3 (report `slice2-wp1-gate-report.md` on
`slice/arrival-backend-contract-wp1-gate`): all oracle items re-run from scratch —
CAS race genuine (barrier-threaded, asserted on the log), injected-failure gate
byte-wise with fsync guard, Rule 18 ratchet 4-step demo, F1 mutations site-isolated,
counts exact, contract module verified stdlib-only in a clean subprocess, Pyright
`:309` shown unreachable by construction. Dispositioned findings — do NOT re-litigate
the deferrals, but DO flag anything that makes one unsound:
- G2 (`head_at` absent from the contract Protocol — file-adapter convention) and G3
  (`NotImplementedError` outside the `ContractRefusal` root) + impl D4 (refusal-set
  gaps): DEFERRED to the slice-2 gate's contract-text package (Kyle rules with F2).
- G4 (merge partial-mark semantics): dismissed, matches pre-existing store semantics.
- Impl deviations D1 (third F1 caller, closed), D2 (projection stores no head hash —
  characterized), D3 (extra types, all consumed): verified by the gate.

## 5. Verdict format

Per §3 item: **PASS/FAIL + evidence**. New findings: numbered `S2WP1-L-<n>`, each with
file:line, severity (BLOCKING/NON-BLOCKING), concrete failure scenario, evidence.
Then one overall line: **CONVERGED** or **NOT CONVERGED** (with the blocking list).
