# Primary acceptance of the correctness pass

This accepts the five reproduced correctness corrections within their stated
scope. It does not mark the larger Arrival implementation or the prior thirteen
review stages complete.

## Gemini review 1

- High: declaration edit preparation omitted the shared anchor validation.
  Confirmed on a real projection-only corruption fixture; fixed before
  folding/signing. Three regressions verify no signing, intent, cache, or
  custody write and retain NotAuthority as the refusal cause.
- Low: standalone shared helper accepted a wrong-kind synthetic genesis.
  Hardened. The file adapter already selects the genesis kind, and runtime
  document resolution also checked it; this was not a demonstrated normal
  file-backend runtime bypass.

## Gemini review 2

No actionable findings. Category evidence includes actual tests and six
independent adversarial probes. Root read the probes and reran all six against
the implementation with isolated test state. All passed. The two review
snapshots have clean tracked/untracked status; raw receipts and source hashes
are retained alongside this file.

Two report qualifications:

1. The declaration follow-up selector selected only two recovery tests. Root
   explicitly selected the three foreign-derived-anchor and two malformed-
   persisted-basis cases; all five passed.
2. Boundary precision comes from the runtime datetime Tick, not SQLite. Raw
   fact timestamps remain unchanged.

Root also disabled both restore row audits in a committed disposable snapshot;
the same-height fork test failed, then passed after exact restoration of the
file. A further healthy-case test accepts a lagging adopted projection and a
subsequent fully synchronized packed-fact/signed-tick projection.

## Remaining limits

- Restore now refuses mismatched projection evidence; a separate explicit
  preserve/quarantine/rebuild procedure remains a design proposal.
- The exact row audit is O(N) and runs only during restore. Ordinary read
  behavior does not become a complete audit of arbitrary projection tampering.
- Boundary closure follows the documented period semantics; no exactly-once
  command dispatch guarantee was added.
- File backend and current supported SDK/engine paths were exercised. Future
  adapters still owe the neutral snapshot/custody contracts.
- Original pending verification/pagination, custody observer guard, and export
  Fable review slots were not replaced by this bounded correctness review.

Integrated validation and current completion scope are recorded in
`../../correctness-pass-2026-09-05.md` and `validation.json`.
