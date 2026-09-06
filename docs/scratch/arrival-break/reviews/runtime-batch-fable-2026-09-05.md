# Runtime atomic batch — Fable 5.1 adversarial review

Date: 2026-09-05  
Verdict: **APPROVE**

## Scope and artifacts

The static packet supplied the full runtime writer and batch tests, Arrival
body grammar, SDK error source/tests, the stage report and design, and the
ratified backend atomic-group and wire-batch excerpts. It excluded SDK batch,
CLI, initialization, source execution, and new protocol design.

Raw artifacts:

- `/tmp/loops-arrival-review/runtime-batch-prompt.txt`
- `/tmp/loops-arrival-review/runtime-batch-result.json`
- `/tmp/loops-arrival-review/runtime-batch-stderr.txt`

## Findings and dispositions

Fable returned `APPROVE` with seven nonblocking findings.

1. **Execute comparison families.** Valid. Batch execution now propagates
   `PreGenesis` and `Indeterminate` refusals like ordinary execution, rather
   than relabeling them as a stale-CAS refusal. A focused regression pins the
   exact indeterminate exception object.
2. **Non-admission item address.** Valid. Per-item runtime refusals such as
   differing IDs now become `BatchWritePreparationRefused` with item index and
   input evidence. The exception carries an explicit `admission_refused`
   category bit; SDK normalization maps admission causes to
   `AdmissionRefusal` and other planning causes to `ArrivalRefusal`.
3. **Double candidate transition.** Valid as an avoidable divergence risk.
   The internal ordinary planner gained a private batch-only mutation mode;
   batch planning now transitions its owned detached candidate once and drops
   the duplicate receive.
4. **Null generated fact ID.** Valid. SDK diagnostics now omit `fact_id` when
   preparation refused before an ID was selected.
5. **Pending multi-fact boundary window.** Valid test gap. A real `every=2`
   case verifies planner output `batch, tick, fact`, the two-row packed body,
   exact projected window commitment, period, cursor, and one shared commit.
6. **Tick time and vertex periods.** Tick timestamps were added to the existing
   three-boundary assertions. A separate vertex-boundary case was not added:
   the accepted batch obligation concerns each emitted fact's generated loop
   boundary, and the same candidate-period mechanism is exercised by the
   `every=1` and `every=2` real cases.
7. **No read repair and append-level race.** Valid test gaps. New real tests
   prove a behind projection remains byte-identical when preparation refuses,
   and an interloper inserted inside `FileLedger.append` yields `HeadMismatch`
   without landing any planned ID.

Root's parallel fixture audit also found that the declaration genesis had a
signed outer Arrival envelope but no inner fact signature. The fixture now
signs the exact `_decl.genesis` fact commitment as well.

## Model receipt

CLI model usage:

- `claude-fable-5-1`: input `2`, cache read `3,305`, cache creation `64,284`,
  output `12,802`, thinking `10,589`, context `1,000,000`, cost
  `$1.92662625`.
- preprocessing `claude-haiku-4-5`: input `46,455`, output `20`, cost
  `$0.046555`.
- total cost `$1.97318125`; duration `162,947 ms`; one turn;
  `is_error=false`.

Post-disposition validation: focused `45 passed`; full engine `2,396 passed,
1 skipped`; full SDK `384 passed`; Rule 18 `35 passed`; Ruff passed.
