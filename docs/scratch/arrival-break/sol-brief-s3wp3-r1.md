# Sol review brief — arrival-break slice 3 / WP3 (compare-on-open seam), round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-3 WP3 — the seam that makes the
head-attestation journal live: every registry open compares custody memory against
the presented store. Review the WP diff adversarially. No fixes, no commits. Run
tests/scripts to verify empirically.

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice3/wp3-seam`, tip `16ac9099` (over WP1's `9ed893fe`).
- Diff spec: `git diff 9ed893fe...16ac9099`. New `engine/arrival_head_seam.py` +
  its 50-test file, registry + file-backend edits (§0.4 lazy reader), Rule 18
  enrollment, report.
- Suites: engine per-package; architecture SEPARATELY. Tests never touch the real
  `$XDG_STATE_HOME` (autouse isolation — verify).

## 2. Design contract (design §D + the ruled dispositions on the finding folds)

1. `AttestedLedger` in `BackendRegistry.open`, ALWAYS ON. Journaling on commit →
   O(1) unchanged-open (the expensive walk only on unjournaled-writer branches).
2. **Write-after-all-refusals, structural** (gate BLOCKING-1's closure): `_observe`
   returns an `_Earned`; `AttestedLedger._write` is the open path's single write
   site; an AST ratchet (direct-name-scoped, precondition-pinned per NB-3) holds it.
   A refused open leaves journal AND index byte-identical.
3. **The posture** (arbiter-accepted): `IndeterminateComparison` proceeds under a
   labeled degradation — its own report type with NO outcome attribute, carrying the
   raised exception, writing nothing — after firing every refusal the bound soundly
   supports (rollback below; HeadFork at-the-bound-different-hash, the accepted
   extension). Proceed answers unobtainable from a bound (mutations f/g).
4. The across-time fix: a peer's commit between the journal read and the store read
   must not read as rollback — re-observe on the descending branch only.
5. §0.4: minted-log-no-index opens through the registry; `query.reader` refuses
   lazily; nothing creates an index.
6. Ordering present → binding (canonical_location) → journal → projection; custody
   first. `NotWitnessed` outside `AttestationRefusal` (committed data ≠ refused op).
   Audit's lookup non-injectable. No `__getattr__` delegation.

## 3. Unverified fixes

None outstanding — every gate finding closed and gate-re-checked at its tip
(BLOCKING-1 at 8c9a88cf with the gate's own repro; NB-3 at 16ac9099 with mutation
(i)). The gate's final stance: PASS. Its three NB findings are dispositioned in the
folds. Nine mutation demos (a-i) all gate-re-run.

## 4. Seeded review targets — the angles the gate did not take

- **Multi-host honesty**: the journal is per-machine ($XDG_STATE_HOME). A store
  synced between two machines (the gruel.network combine case) presents heads
  machine A never journaled. Walk the design: does first-contact-per-machine +
  bindings produce any SILENT acceptance a single-machine analysis hides — or is
  every cross-machine surprise a typed refusal/labeled degradation?
- **canonical_location edge cases**: symlinked store dirs, case-insensitive
  filesystems (macOS default), a store reached via two mounts — can two canonical
  forms of one location manufacture first contact past the binding?
- **The audit producer**: it journals an AUDIT entry with the covered head — can an
  audit run against a store that regressed since open (TOCTOU between open's compare
  and audit's walk) journal a head that re-raises K wrongly?
- **Trust-reset**: the ceremony entry opens a new epoch — can a reset be REPLAYED
  (same entry appended twice, or an old reset re-read) to resurrect an abandoned
  epoch's K?
- **The degraded report type**: adversarially attempt a uniform outcome read across
  degraded/normal (must AttributeError); and check every caller in the seam handles
  the degraded type explicitly rather than duck-typing past it.

## 5. Verdict format

Per §2 item: PASS/FAIL + evidence. New findings: `S3WP3-L-<n>`, file:line, severity
(BLOCKING/NON-BLOCKING), concrete failure scenario, evidence. Then one line:
**CONVERGED** or **NOT CONVERGED** (with the blocking list).
