# Slice 2 / WP1 impl brief — contract surface + file adapter + F1 + GF-2 ratchet

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice2-backend-contract` @ `01M177MHWHD5HM574VSTDE17X8` (ratified) —
the full design is `docs/scratch/arrival-break/slice2-design-proposal.md` (commit 8bfb5e6a).
**Your sections: §A (all), §D.1, §F.** Read them completely; they are the contract.
Deviations are reportable (finding fact + report), never silent.

## Scope (proposal §D.1)

1. `engine/arrival_contract.py` — types (`Head`, `RecordDraft`, `Commit`,
   `DurabilityReceipt`, `Capabilities`, `VerifyScope`, `StoreDescriptor`), the
   `ArrivalLedger`/`ArrivalQuery` Protocols, typed refusals. stdlib+typing only; no
   sqlite3; no runtime `arrival` import (TYPE_CHECKING allowed).
2. `engine/arrival_file_backend.py` — `FileLedger`/`FileQuery` per the §A.2 wrap table.
   `ArrivalStore` is NOT modified; the adapter wraps `ArrivalLog` + the projection;
   the existing ResumeMark is `projected_through`.
3. **F1 closed at BOTH sites** (`arrival.py:1330` and `:1392`): `following` widens from
   `int | None` to the full head; a bare `int` is REFUSED (construction over detection).
   Known blast: `store/merge.py:307` + tests. This is the only arrival.py behavior change
   in WP1 — the wire codec and commitment machinery are untouched.
4. Rule 18: `arrival_contract.py` + `arrival_file_backend.py` join `_SCAN_TARGETS` at
   birth (`arrival_registry.py` is WP4's — do not create it), AND the §F completeness
   ratchet lands: `_NOT_SCANNED` shrink-only dict (empty today) + the glob test exactly
   as drafted in §F, house-style per Rule 15's EXCEPTIONS.
5. The query-handle separation unit test (§A.2): no ledger-mutating op name reachable
   from a query handle. Unit test, NOT a new numbered architecture rule.

## Non-goals

No registry (WP4). No admission/sqlite_store/merge changes beyond the F1 caller at
`merge.py:307` (WP3 owns that file otherwise). No replicate/export (WP2 — but your
contract module DECLARES those ops on the Protocols). No consumer rewiring anywhere
(SD-7). No coordinate-machinery moves (SD-1: it stays put). No new `_canonical_bytes`.

## Oracle (the gate re-runs from scratch; make it pass honestly)

1. All 14 arrival test files green, unmodified in intent (13 engine + store's
   test_arrival_merge.py).
2. CAS-race conformance gate with FULL-HEAD compare: two writers at one expected head,
   exactly one commit wins.
3. Injected-failure-per-append-stage gate: no partial logical group ever visible.
4. Query-handle separation test green.
5. Rule 18 green with both new modules registered; completeness ratchet
   mutation-demonstrated (unregistered `arrival_zzz.py` → fails naming the file;
   registered → green; file removed after).
6. F1 mutation demo: revert the full-head compare at EACH site independently → a test
   fails naming that site's behavior; restore; `git diff` clean.
7. Suites: engine, store, architecture green; counts reconciled against baseline
   (engine 1937p+1s, store 177, architecture 98 — yours will grow; account for every
   delta).
8. `git ls-files` shows every new file committed.

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s2wp1 -b slice/arrival-backend-contract main`
  (you CREATE the wave branch — WPs 2-4 will branch from your landed tip). Step 0:
  verify base includes 8bfb5e6a; if behind, reset onto current main.
- Report AS YOU GO: `docs/scratch/arrival-break/slice2-wp1-report.md` committed on the
  branch — design-point rationales, test-count table, mutation evidence, deviations.
- Loops emissions from the MAIN checkout cwd, moments only, payload
  `agent=s2wp1-impl slice=2 wp=1 role=implementer`. Facts only; never seal/tick;
  never stage `.loops/`.
- Commits: conventional, logical units, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip hash, files changed, per-suite counts with deltas
  accounted, mutation results one line each, design-point choices one line each,
  deviations. The report file is the record; the message is the pointer.
