# Arrival correctness pass

User authorized this pass after primary triage of five reproduced failures.
Sol handled declaration recovery and edit preparation; Terra handled aggregate
dispatch and restore audits; Luna supplied independent boundary regressions.
Root made shared identity and boundary changes, reviewed the changes, reran the
integrated suites, and owns the remaining contract judgment.

## Implemented corrections

1. **Restore-forward:** reject a projection ahead of the receiver's actual
   starting head before mutation. Also audit exact projected fact/tick tuples,
   payload text, signatures, chain fields, receipt coordinates, and declaration
   anchor against verified custody. Audit before restoration and after append.
   Same-height forked projections now refuse too; postcommit failures retain
   the real Commit. No reads or sync operations gained repair behavior.
2. **Declaration recovery:** apply and recovery return a complete engine result
   that the SDK serializes without requiring the preparation plan. New intents
   retain the original ReadBasis; old intents report projection/generation as
   unknown. Recovery never manufactures a Commit or a semantic change list.
   Persisted CURRENT basis must match its captured head; malformed projection
   heads or generation values refuse without publishing/removing the intent.
3. **Aggregate topology:** descriptor-backed SDK reads choose their execution
   shape from the captured adopted declaration. Storeless composition uses its
   local definition. Direct engine aggregate capture also retains a plain
   descriptor root as its own member. Both directions of local/adopted drift
   have coverage; own-overlay and occurrence semantics stay intact.
4. **Pending boundaries:** each boundary name has its own closing edge. Compare
   event time and Arrival coordinate, not only timestamp or tick fact_cursor.
   A repeated capture does not re-emit its recorded close; later receipt at the
   same timestamp remains eligible. The comparison uses datetime tick precision
   to handle timestamps that round either up or down without changing facts.
5. **Declaration identity:** one validation helper checks projection anchor
   identity against captured physical lineage before reads or runtime use. It
   also covers declaration edit preparation before folding/signing, an omitted
   entry point found by Gemini. Claimed identity needs its matching genesis;
   a supplied genesis must have the genesis kind.

## Boundary semantics retained and clarified

- One matching vertex boundary closes the captured period; equal-time facts
  already present belong to that closure. A later receipt at that time can
  start a new period.
- Loop closing edges do not silently close an unrelated vertex period.
- Future-dated facts already in a tick's evidence horizon remain eligible when
  their event time is reached. The fact cursor is not a trigger identifier.
- Late facts dated before a closed event-time edge do not reopen that period.
- Count boundaries remain ingress-driven. External command dispatch has no new
  exactly-once guarantee. Tick payload and wire formats were not changed.

## Evidence

Each original reproduced failure gained a regression observed failing before
its fix. The precision probes additionally demonstrated both duplicate closes
on rounding down and lost later receipts on rounding up. A root mutation check
in a committed disposable snapshot removed both restore row audits: the
same-height fork regression failed; restoring the exact file made it pass.

Integrated root validation after implementation:

| Suite | Result |
| --- | --- |
| Engine | 2,501 passed, 1 skipped |
| SDK | 486 passed |
| Migrate | 69 passed |
| Architecture | 101 passed |
| Minimal CLI, including wheel smoke | 8 passed |

After this integrated run, an additional healthy restore regression covered
an adopted lagging projection followed by catch-up over packed facts and a
signed tick. The focused restore file then passed all 19 tests. This extra
test is not counted in the full engine result above.

Scoped Ruff on changed neutral modules/tests and `git diff --check` passed.
Legacy `vertex.py`/`declaration.py` retain existing lint debt; this pass does
not reformat those modules wholesale.

## Independent review

The requested Antigravity skill was read at
`~/.claude/skills/delegating-to-antigravity/SKILL.md`. `agy models` listed
`gemini-3.8-flash-high`. Invocation smoke tests verified the intended isolated
directory/branch. Reviews use committed disposable copies including untracked
implementation files, with dedicated probe directories. Reviewers cannot be
treated as accepted merely from their verdict; root checks evidence and scope.

First Gemini review completed with personally run category checks and a real
foreign-anchor probe. Its high finding (declaration edit preparation omitted
shared identity validation) is fixed with regressions. Its low finding
(standalone helper accepted a wrong-kind synthetic genesis) is hardened; that
case requires a nonconforming snapshot and was not a demonstrated normal file
backend bypass. The second review covers final restore audits, boundary period
semantics, aggregate dispatch, and the first review's follow-up corrections.
It completed with no actionable findings. Root independently reran all six
adversarial probes (phantom facts, altered fact signatures, altered tick chain
fields, simultaneous boundaries, successive periods, and submicrosecond ties).
Both isolated review repositories were clean at the final scope check.

Primary qualification: review 2's declaration follow-up selector only executed
the two recovery tests; it did not execute the five named malformed-basis and
foreign-anchor cases. Root ran those explicitly: all five passed. Its phrase
"SQLite microsecond precision" is also inaccurate: the precision constraint is
the runtime datetime Tick, while SQLite stores the fact timestamp as a REAL.
These corrections do not change the implementation assessment.

After the review snapshot, source-only changes were a datetime UTC alias and
line wrapping. The affected boundary/consumer checks passed (29 tests). The
additional healthy restore test and documentation updates do not change the
reviewed production behavior.

Raw prompts, results, snapshot hashes, mutation evidence, and validation counts
are in `reviews/correctness-2026-09-05/`. No Claude calls were made in this pass.

## Remaining decision

Restore now safely refuses suspect projections; it does not yet provide the
procedure that preserves and rebuilds them. See
`projection-recovery-correctness-design-2026-09-05.md` for the proposed explicit
source-aware operation. Source awareness matters because observing a source
can advance the shared lineage witness above the truncated receiver, so an
ordinary receiver-only open must continue refusing rollback.

No production commit, push, live migration, or live-store modification occurred.
The larger Arrival completion worklist remains separate and unfinished.
