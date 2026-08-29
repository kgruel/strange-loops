# Slice 2 / WP2 impl brief — replicate, export, minimal portable import

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice2-backend-contract` @ `01M177MHWHD5HM574VSTDE17X8` (ratified).
Full design: `docs/scratch/arrival-break/slice2-design-proposal.md`. **Your sections:
§A.2 (op table rows replicate/export), §D.2.** WP1's landed code is your substrate:
read `engine/arrival_contract.py` and `engine/arrival_file_backend.py` on the wave
branch, plus WP1's report (`slice2-wp1-report.md`) — its design points 1.5 (Protocol-
incomplete adapter: replicate/export declared, absent), 1.7 (max_atomic_records), and
deviation D2 (projection stores no head hash) bear directly on you. Deviations are
reportable (finding fact + report), never silent.

## Scope (proposal §D.2)

1. **`replicate(expected, records)` on FileLedger — composition, NOT greenfield** (SD-3):
   batched `ArrivalLog.append_record` (validates-never-assigns, checks supplied `rh`)
   under ONE lock acquisition, plus WP1's full-head CAS pin, plus a typed
   same-height-fork refusal (`SameHeightFork`). Do not build a second appender.
2. **`export(through, codec)`**: net-new over `scan` + `encode_record`. Dense prefix
   through a coordinate; byte-exact records.
3. **Minimal portable import** (SD-6), §08's default ONLY: into a new empty replica, or
   a non-empty target with exact prefix agreement through its head — else refuse. NO
   merge semantics (re-coordination is admission = WP3's; do not touch it).
4. `capabilities()` grows honestly with what you build (WP1's test cross-checks the
   report against the object — keep it true).

## Non-goals

No admission/merge changes. No registry (WP4). No transport/receive/slice re-expression
(slice 5). No consumer rewiring (SD-7). No new appender primitive. No projection
changes (D2 is characterized, not fixed, in this WP).

## Oracle (the gate re-runs from scratch)

1. **Three new replicate vector families** in `spec/conformance/vectors/`:
   exact-suffix accept; same-height-fork refuse; stale-replica catch-up preserves
   hashes BYTE-FOR-BYTE. Wire them into the conformance test consumers the way the
   existing families are.
2. export → import → export **byte-identical**.
3. Snapshot consistency while another writer appends.
4. Mutation demos: (a) weaken the same-height-fork refusal → its vector/test fails;
   (b) make replicate re-coordinate (assign instead of validate) → the
   hash-preservation test fails; restore, git diff clean each time.
5. All WP1 + arrival suites stay green; counts reconciled with every delta accounted.
6. `git ls-files` shows every new file/vector committed.

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s2wp2 -b slice2/wp2-replicate 0d38c969`
  (branch off the wave branch tip given in your launch message; step 0 verify
  `git merge-base HEAD slice/arrival-backend-contract` equals that tip).
- Report AS YOU GO: `docs/scratch/arrival-break/slice2-wp2-report.md` committed on your
  branch. Loops emissions from MAIN checkout cwd, payload
  `agent=s2wp2-impl slice=2 wp=2 role=implementer`; facts only; never stage `.loops/`.
- Commits conventional, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip, files, counts with deltas, mutation results,
  design choices one line each, deviations.
