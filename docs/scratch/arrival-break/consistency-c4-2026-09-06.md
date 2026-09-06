# C4 implementation — September 6, 2026

Status: complete; validated and accepted by Fable-low. Baseline:
`831698ff` on `arrival/finish`. Sol owns production and SDK compatibility
documentation, Terra owns acceptance tests, Luna independently audits and
validates, and root integrates and adjudicates the final review.

## Result and compatibility

`CustodyCredentialProvider` now raises the existing `SdkValueError` during
construction for every non-`None` `key_dir`. Previously the argument was
accepted and stored, but `for_write` ignored it and selected the default
custody keys. The error is a configuration refusal shared by Arrival and legacy
consumers, before a provider can be used for an operation. Positional and
keyword arguments have the same rule.

Both `CustodyCredentialProvider()` and `CustodyCredentialProvider(key_dir=None)`
keep their existing behavior: `for_write(vertex)` obtains fresh tick, fact and
Arrival signers from the custody resolver. No constructor path resolves keys.
The unused private `_key_dir` field is removed. `SdkValueError` already belongs
to both the SDK and Python value-error hierarchies and is publicly exported;
this slice adds no exception type or error envelope.

Repository production callers all use the default constructor. External callers
that passed an override now receive an explicit error, even if the supplied
directory exists or resembles the default location. The SDK README documents
this intentional compatibility change. Custom `CredentialProvider` injection
remains available; that protocol does not itself register public keys or define
an observer-to-key mapping.

## Scope

This completes the bounded C4 refusal from the
[consistency matrix](consistency-contract-matrix-2026-09-06.md). The broader
[D0/D2 identity decisions](identity-decisions-2026-09-06.md) remain proposals:
custody namespace, exact observer identity, domain-specific requests, persisted
bindings and public-key registration must be designed together before a mapped
override is supported. This change performs no migration, key creation,
normalization or rename and changes no signing or verification algorithm.

## Validation and review

Terra's focused emission suite passed **67 tests**. Luna's final full checks
passed **528 SDK tests** and **101 architecture tests**, with scoped SDK Ruff
clean. Default and explicit-None providers produce verifiable signatures under
the fact, tick and Arrival domains after explicit key creation. Positional and
keyword override cases cover missing and existing directories, no signer
resolution, no new configured directory, and preservation of existing content.
Existing SDK coverage also exercises custom provider injection and unsigned
Arrival preview without key creation.

See the [independent validation](consistency-c4-validation-2026-09-06.md).
One Fable 5.1 low-effort review **accepted** with no blockers. Root
[triaged its three optional notes](reviews/consistency-c4-2026-09-06/primary-triage.md):
a possible fixture-literal improvement, an overstated nested-observer coverage
claim, and help-text discoverability plus an incorrect README-placement claim.
Production, tests and SDK README remain unchanged from final validation and
review. No reviews or validation jobs remain. Raw logs and frozen review
evidence are retained with the triage.

C5's Arrival loop/vertex name collision refusal is the next bounded matrix
candidate; credential request scope and mapped custody remain separate design
work.
Changes remain uncommitted; nothing pushed or applied to live stores.
