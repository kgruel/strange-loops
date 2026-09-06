# Arrival completion stage 3B — atomic runtime batch

Date: 2026-09-05  
Status: implementation complete; adversarial review approved

## Result

`prepare_batch_write` opens one attested Authority descriptor, captures one
CURRENT projection basis, hydrates the effective declaration and fold state
once, then plans every input against an in-memory extension of that same
bounded snapshot. Each item resolves its own declaration grant. An invalid
later item raises `BatchWritePreparationRefused` with its input index, item,
effective declaration, custodian, captured basis, and cause before any custody
append.

Pending fact and tick rows are threaded into later item planning in receipt
order. Exact retries from the captured snapshot or an earlier batch item are
explicit per-item no-ops. A reused ID with different content refuses the whole
plan. Adjacent fact drafts with one observer become one signed wire `batch`;
observer changes and generated ticks split groups while all resulting drafts
remain in one logical plan. Atomic capability preflight counts these final
packed records rather than input facts.

`execute_batch_write` reopens through the registry, compares the full captured
head, and issues exactly one `ledger.append(expected, drafts)`. Backend atomic
limits are rechecked at that append. A successful result returns one shared
commit and every item identity. `BatchWriteCommitUnknown` retains the captured
head, ordered items, all fact and tick IDs, drafts, and original cause when an
unexpected append failure cannot prove no mutation. A distinct
`BatchPostCommitProjectionFailed` retains the durable commit and the same
identity set when explicit postcommit maintenance fails.

SDK error normalization maps the batch preparation refusal to the admission
category with item address, and maps batch unknown/postcommit failures to the
existing stable committed outcome families while serializing plural identities
without record payloads.

## Acceptance coverage

Real temporary fixtures mint a signed physical genesis, append a declaration
genesis whose ID equals the physical lineage, explicitly synchronize its file
projection, then run supported registry preparation and execution. Coverage
includes same-observer packing and signature verification, mixed-observer
drafts under one commit, per-item grants, an invalid later item with zero
append, existing and within-plan duplicate equality/difference, three boundary
ticks with committed and projected chain/window/signature/period evidence,
packed-record atomic limit preflight and append-time recheck, stale CAS,
durable-then-raise unknown identity, and durable postcommit failure identity.

Final validation:

- Runtime batch, ordinary, and SDK error focused set: `45 passed`.
- Full engine suite: `2,396 passed, 1 skipped`.
- Full SDK suite: `384 passed`.
- Ruff over runtime batch and SDK error source/tests: passed.
- Rule 18 architecture suite: `35 passed`.

The required Fable 5.1 static review returned `APPROVE`. All source-backed
nonblocking observations were corrected and covered locally; details and exact
model metadata are recorded in
`reviews/runtime-batch-fable-2026-09-05.md`.
