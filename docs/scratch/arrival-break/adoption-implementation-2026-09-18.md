# C9 explicit declaration adoption

Implementation: engine ceremony, SDK composition and isolated integration
rehearsals. The companion [review](adoption-review-2026-09-18.md) records
independent findings and their dispositions. User-facing SDK usage is in
[ADOPTION.md](../../libs/sdk/ADOPTION.md).

## Result

`sdk.adopt_arrival` now bridges a migrated, structurally valid history to the
ordinary Arrival runtime. It accepts the selected full head S, reviewed
declaration text/hash, separately published authority text, adopting observer,
and pre-created mapped credentials. It validates declaration meaning, identity
collisions, registry-forming signatures and existing observer keys, then appends
one `_decl.genesis` fact whose ID equals the physical lineage. The initializer
and adoption share the anchor builder.

The two snapshot forms must have equal declaration documents; residence may
differ because migration changed the store descriptor. This slice deliberately
does not adopt a different declaration or change observer keys. FACT and
ARRIVAL authorship requests are distinct and verified. Migration report
signature/domain/provenance format remains unchanged; callers verify the report
at S before the adoption append.

A durable intent reserves the exact signed draft before append. Apply uses
the full-head compare-and-swap, explicitly synchronizes projection through A,
and reconciles the existing published cache without rewriting it. Typed SDK
errors retain intent/head/commit evidence for refused, unknown, unwitnessed and
committed-incomplete outcomes.

Recovery verifies the selected prefix and registry again, validates the
reviewed documents and public binding evidence, and verifies the reserved
FACT and ARRIVAL signatures. It resolves no signing credentials. It either
appends at S or recognizes the exact anchor at S+1. A later tip remains
separate from the exact adoption head; a reconstructed commit identifies its
recovery-derived durability evidence rather than inventing the original
append receipt.

## Acceptance evidence

The repository workflow covers synthetic JSONL and SQLite originals copied
into isolated rehearsal roots. SQLite uses the backup API. It verifies the
migration report at S, confirms pre-adoption declaration reads refuse, adopts
the reviewed snapshot, checks reads/inspection at A, emits a signed/witnessed
mapped fact and exports an exact captured prefix. Original source and vertex
bytes, copied source bytes, migration-prefix bytes and report bytes are
preserved.

Two real child-process exits occur immediately after durable intent and after
append. Recovery succeeds with the credential directory moved offline and
provider lookup disabled, preserves reserved signature bytes and appends no
duplicate. Both boundaries also refuse modified public binding evidence,
modified inner signature and modified outer signature even when the duplicate
draft encodings are updated consistently. Restoring the authentic intent then
recovers successfully. These are process-exit checks, not arbitrary power-loss
claims.

Luna's independent review found the two intent-authentication gaps in the
initial implementation; the final recovery verifier addresses them. Root also
required exact Commit(S,A) reconstruction and preservation of typed outcomes
when phase persistence fails. Full suite counts and final review disposition
are recorded in the current orchestration entry.

## Remaining work

The SDK operation and synthetic rehearsal are not a live migration coordinator.
Next is a reusable offline copy-rehearsal workflow with retained source/report
provenance and an explicitly selected representative store. Existing live
stores, credential roots and writers were untouched. Source-execution CLI
transition, legacy writer retirement, live adoption and release remain open.
No push, merge or release was performed.
