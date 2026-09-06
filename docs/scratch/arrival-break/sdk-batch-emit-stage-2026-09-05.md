# Arrival completion stage 3B-SDK — batch emission

Date: 2026-09-05  
Status: implementation and local validation complete; Fable review queued for the 21:20 CDT quota reset

## Result

The existing `emit_batch` SDK operation now resolves an explicit Arrival
descriptor before any legacy target probe. It normalizes every input before
target resolution, prepares the complete batch from one attested CURRENT
snapshot, and calls `execute_batch_write` once. The executor compares the
captured full head and performs one atomic append of the engine's packed
records. Successful custody append injects the explicit
`sync_projection(..., through=commit.after)` maintenance boundary, so a
successful result can be followed immediately by CURRENT reads.

Each mapping input may explicitly select `admit_undeclared`; other shapes use
the explicit operation default. Mixed observers remain one logical append and
one shared commit even though their wire records cannot be packed together.
Existing and within-batch equal IDs return per-item `stored=False` receipts.
Different-content reuse, invalid later admission, stale heads, and atomic
capacity refusal happen without appending the planned batch.

`BatchEmitResult` gives Arrival and legacy callers one return shape. It carries
ordered `EmitReceipt` items, descriptor and write path, captured head, shared
commit, witness state, projection state, and explicit atomicity. Arrival item
receipts retain fact/tick IDs and duplicate status while shared commit evidence
appears once on the batch result. Commit serialization includes only heads,
record count, and durability; it does not copy backend record bodies. An
all-duplicate Arrival request is an `idempotent-noop`; empty input is an
`empty-noop` and never opens a store.

The retained legacy path returns the same wrapper with
`atomic=False`, `atomicity="legacy-sequential"`, and no invented shared commit.
If that loop stops after an observable prefix, `LegacyBatchPartialFailure`
retains all prior receipts, the failing index, and any fact ID known to have
committed. This makes retry decisions explicit without describing the
compatibility loop as atomic.

Engine batch preparation, commit-unknown, unwitnessed, and postcommit
projection failures pass through `sdk.errors.normalize_exception`. Stable SDK
diagnostics retain item index, captured head, ordered item identities, plural
fact/tick IDs, and available durable commit heads. The SDK makes one execute
attempt and never retries an unknown append result.

The stage also corrected a signing-domain defect exposed by the first real
default-custody SDK flow. `WriteCredentials` now carries an independent
optional `arrival_signer`. Inner fact rows use only `fact_signer`, outer fact
and packed-batch envelopes use only `arrival_signer`, and generated tick rows
continue to use `tick_signer` for their inner chain signature while leaving
their outer envelope unsigned. `CustodyCredentialProvider` resolves all three
callables independently. There is no cross-domain fallback: an absent Arrival
signer produces an unsigned envelope even when an inner fact signer exists.

## Acceptance coverage

Real temporary Arrival fixtures use an Ed25519 physical genesis and signed
declaration genesis. SDK tests cover same-observer wire packing and mixed
observers under one shared commit, invalid later admission with zero append,
existing and pending duplicate equality/conflict, boundary tick grouping plus
CURRENT fact/tick lookup after synchronization, packed-record atomic capacity,
stale CAS, commit-unknown one-attempt identity, unwitnessed identity,
postcommit projection failure, JSON serialization, normalization before target
probing, explicit per-item admission override, and empty input. Legacy tests
cover the uniform wrapper and retained partial-prefix failure.
One end-to-end SDK test initializes a real Arrival vertex with default custody,
emits an ordinary fact and a packed batch, verifies whole-log authorship under
`loops-arrival-v1`, verifies every inner row under `loops-fact-v1`, and proves
the inverse domain checks fail.

## Validation

- Full SDK suite: `408 passed`.
- Full engine suite: `2,404 passed, 1 skipped`.
- Final signer/domain and SDK Arrival focused set: `86 passed`.
- Scoped SDK ruff and ty checks: passed.
- Rule 18 focused architecture suite: `35 passed`.
- Full SDK ty currently reports 11 diagnostics in concurrently owned
  `declare.py` and legacy `kind.py`; the changed batch SDK files are clean.

The required capped Fable 5.1 review must not run before the reported 21:20 CDT
quota reset. Its complete static packet is prepared under
`/tmp/loops-arrival-review/sdk-batch-*`; the review receipt remains pending.
