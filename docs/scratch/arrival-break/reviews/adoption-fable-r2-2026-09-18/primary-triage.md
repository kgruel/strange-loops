# Primary triage: Fable second pass

Reviewed checkpoint: `7ede817a`. Verdict: **REVISE**, one P2, no P1.
Native model usage confirms Fable 5.1; source drift is empty.

- F1–F4: reviewer accepts fixes; existing regressions retained.
- F5 recovery preflight: accepted. A new registry can lack maintenance after
  reservation. Add attested preflight before both apply and recovery append,
  preserving intent with a typed precommit error on failure.
- Intent replacement race: accepted despite optional reviewer classification.
  Recovery now derives the target lock from the intent filename and reads
  and validates the current intent only after acquiring that lock. It cannot
  apply an earlier parsed reservation to a newer intent file.
- Retained stale apply: expose intent_path and document recovery requirement.
- Transient registry-open error: normalize narrowly to recovery-required; do
  not catch known commit failures as precommit. SDK already normalizes
  ContractRefusal, including HeadMismatch.
- Source hashing question: `_content_sha256` reads disk. Pin drift deliberately
  refuses recovery and ordinary runtime (`SourceDrift`); restore reviewed inputs.
  This does not authorize a new source enactment policy. Document the constraint.
- Shared helper ordering and rebuild argument behavior predate this correction;
  initializer still passes an explicit public key. No new regression identified.
- Basis wording and cross-ceremony coordination remain prior optional scope
  questions. No live coordinator is introduced.

The next frozen packet includes the previously omitted backend wrapper, source
hash helper, credential domain helper and complete ArrivalLog implementation.
Fable's unaltered findings and native receipt remain alongside this disposition.
