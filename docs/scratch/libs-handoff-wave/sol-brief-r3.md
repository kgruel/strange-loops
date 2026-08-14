# Sol review brief — libs-handoff-wave, round 3 (post-simplify)

## 1. Anchor

- Repo: this checkout, branch `libs-handoff-wave`.
- Since your r2 run, TWO passes landed: the r2 remediation (fix/libs-handoff-r2,
  8 commits — your six r2 findings) and a 4-angle simplify pass
  (fix/libs-handoff-simplify, 14 commits — quality refactors, several of which
  RESTRUCTURE code you previously reviewed). Diff since your last look:
  `git log --oneline` from the sol-r2-stdout commit; full context remains
  `git diff main...HEAD`.
- A simplify pass touches code, so it reopens the review obligation: in a prior
  arc the simplify pass introduced the arc's ONLY regression. Hunt there.

## 2. Contracts

Unchanged (r1 brief §2). Two contract-relevant deliberate changes to know:
- FactAttestation/TickAttestation dropped `signature_present` (kept `signed`
  only) — the two fields were provably identical; the contract's "or the write
  operation's actual result" clause now sources attestation from the append's
  own return (no post-write SELECT). Verify honesty survived the resourcing.
- probe's `canonical_writable` now means the FULL write surface (canonical +
  index-creatable + parent dir), documented; ceremony consumes probe's answer.

## 3. R2 disposition table (verify each)

| Finding | Fix | Claim |
|---|---|---|
| R2-01 blocker raw-string evasion | 4368f471 | Parser is the safety oracle: pre/post parse, exact kind-set delta + definition-equality; lexical splitter demoted to best-effort. Evasions welcome: any input class where the PARSER itself normalizes away a difference (comments? whitespace-in-values? duplicate kind names in input?) or where _verified admits a wrong delta. |
| R2-02 fourth LIKE site | d7d97481 | slice.py on the shared predicate (now engine/sql_util.kind_subtree_predicate post-simplify). |
| R2-03 sqlite leak in RTO | a017cb10 | Superseded structurally by simplify item 2 — corrupt-index rebuild now lives in JsonlStore open itself (54b994a0); preflight's branch dissolved. Verify BOTH the store-level rebuild (locked-error and missing-log re-raise guards!) and that preflight still reports honestly. |
| R2-04 write surface | 864fff4d + c2113a40, restructured by a305cc2e + 9e959a75 | probe.write_surface_reason; apply refuses typed BEFORE intent on open failure, needs-recovery mid-absorb. |
| R2-05 trailing comment | c60445b9 | Suffix preserved. |
| R2-06 docstring | 8940ffe6 | Narrowed. |

## 4. Simplify pass (PRIMARY target) — 14 commits on fix/libs-handoff-simplify

Highest-risk restructures, in order:
1. 54b994a0 — corrupt-index rebuild moved INTO JsonlStore.__init__ (sqlite3.Error
   → discard index+sidecars → rebuild from log; re-raises on locked / missing-log).
   This is recovery machinery on the OPEN path of the production store class.
   Adversarial: locked db, read-only dir (can't delete index), sqlite3.Error
   during the REBUILD itself, concurrent opener racing the discard, and the
   old preflight behaviors (AUDIT_THEN_OPEN must still refuse; audit-only must
   not trigger the rebuild since canonical_audit never opens the store — verify
   that's still true).
2. 9e959a75 — ceremony apply: currency pre-check deleted (CAS sole staleness
   authority), genesis/edit arms merged, single store open threaded before
   intent write. Verify the R2-04 two-scope race floor survived the merge and
   the mutated-nothing property still holds on open failure.
3. 4d6ae48e — attestation resourced from append's own return
   (append_attested/append_tick_attested); per-emit SELECT + PRAGMA gone.
   Verify row-honesty: is the returned state ALWAYS what the committed row
   says, including signer-returns-None, unsigned store, ceremony paths, and
   any path where commit could differ from assembly?
4. a305cc2e — write_surface_reason in probe; _backend_not_writable deleted.
5. 99524e50 — _reject_shared_line deleted (parser oracle sole detector).
6. f7eb9042 — deserialize_row redefined over deserialize_records (note: malformed
   batch lines now surface structural errors first — acceptable? your call).
7. a47c72c3 — preflight _result factory; agreed=report.ok unified; post_report
   None unless recovery ran (result-shape change — any consumer assuming
   post_report is always set?).
8. 3bab390a — signature_present dropped (public API narrowing, this wave's own API).
9. f18d742e / 4ccf36a5 / 30308497 / c41925b8 / eb11f180 — helper extractions,
   validate split, one-liners, single-handle plan.

## 5. Verdict format

Per finding: id (SOL-R3-NN), file:line, severity, claim, empirical evidence,
fix direction. End with CONVERGED / NOT CONVERGED (zero new blocker/major,
all r2 dispositions verified, simplify introduced no regression).
