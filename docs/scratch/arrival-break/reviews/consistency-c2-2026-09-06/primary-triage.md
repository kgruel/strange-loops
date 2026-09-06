# C2 Fable-low review triage — September 6, 2026

Status: complete. Both Fable-low reviews adjudicated; no pending reviews.
Final production/test bytes match the accepted follow-up and final validation.
Baseline `8a045f1f`. Changes remain uncommitted on `arrival/finish`.

The initial tool-free frozen packet was 195,227 bytes, SHA-256
`2975dce5a9b22a68c027e5d75f63e2d27ff01743932b6346cfd29a108d45f697`.
Fable 5.1 low completed at 2026-09-06T18:09:38Z with **needs correction**.
There was no source drift at review start. Substantive output used canonical
`claude-fable-5-1`; the CLI also used its small Haiku helper (14 output tokens).
The [raw findings](c2-findings.md) remain unmodified.

## Initial findings

1. **Preparation factory could be used after append — rejected as a current
   correctness bug.** The reviewer proposed a hypothetical recovery caller
   absent from its packet. Root and Sol inspected all repository references.
   `_validate_residence` has one caller, inside `prepare_declaration_edit`;
   `_descriptor_location` is only called by that validator. `_declaration_row`
   and `_key_draft` are called only by preparation; both call
   `_signed_with_existing_key`, whose third caller is also preparation.
   `_preparation_refused` is reached only on these paths and directly from
   preparation. Apply calls `_apply`; recovery reconstructs via
   `_plan_from_intent`, which does not call these preparation helpers. This is
   coordinator-scoped proof, distinct from a public constructor default. The
   [call-site evidence](preparation-call-sites.txt) and full declaration module
   will be supplied to the follow-up reviewer. No speculative framework change
   or test mirroring private call structure was added.
2. **Default null declaration coordinates suppress SDK caller context — fixed.**
   `DeclarationPreparationRefused` now attaches captured/projected head
   attributes only when a concrete head is supplied. The context merge can
   supply an otherwise absent captured head. We deliberately did not make
   context override explicit null globally: initialization's pre-mint unknown
   outcome must retain `captured_head=None`. SDK regressions verify both cases;
   engine constructor tests verify absent optional head attributes.
3. **Unsupported scalar coordinate becomes a misleading null — fixed.**
   Unsupported scalar identity attributes are now omitted, and unsupported
   scalar context values likewise do not add a key. The in-repository
   exception attribute audit found strings, integers and Path values for these
   fields; no Enum/value-object identity dependency was found. The payload trap
   regression checks omission without `str` or `repr` execution. Actual
   explicitly unavailable maintenance/initialization coordinates still use
   null. No arbitrary value-object conversion was added.
4. **`entered/not-attempted` contradiction accepted — fixed defensively.**
   Both impossible attempt/state pairs are now omitted by the safe serializer.
   Current coordinator producers emit neither; this tightens the additive
   serializer without inventing new effect proof. Tests cover both directions.

Focused checks after these corrections: engine 35 tests, SDK evidence plus
existing error tests 20. Owning-package Ruff passed. The earlier full run was
engine 2,547 passed/1 skipped, SDK 523, architecture 101. Final full runs after
all corrections passed: **engine 2,550 / 1 skipped (83.89s), SDK 525 (40.88s),
architecture 101 (7.07s)**. Scoped engine and SDK Ruff passed. Final source has
not changed since these runs.

## Scope retained

No new scalar outcome classification for ordinary writes, batches,
initialization, restore or structured source tiers. No global context override,
no custody claim from maintenance errors, no fabricated Commit, and no claim
that custody non-entry undoes witness or external signer effects. Shared
preparation helpers remain private and preparation-only.

## Follow-up verdict and disposition

The follow-up packet was 137,352 bytes, SHA-256
`a7e5cb6256f2626ce9b14fec614963d2bcf9bd139559e8769b0466e0070a673a`.
Fable 5.1 low completed at 2026-09-06T18:16:34Z with **accept** and no remaining
concrete regression. The reviewer verified all accepted corrections and
explicitly withdrew finding 1 after examining the full declaration module.
Substantive output used canonical `claude-fable-5-1`; its CLI helper used 21
Haiku output tokens. No source drift occurred at start or before final triage.
See the [follow-up findings](followup/followup-findings.md).

One low optional observation is **deferred as evidence enrichment**: several
other in-basis declaration refusals do not attach the locally captured head.
C2 preserves the behind-projection coordinates and any coordinates already
carried by an error; it does not complete every declaration-refusal branch.
The reviewer treated this as existing and non-blocking. Future enrichment
should attach the coordinator's own head at those sites, with tests against
substituting a caller's separate capture. No new caller-context provenance
promise is made here.

All source and test hashes are retained in [final-source-hashes.json](final-source-hashes.json).
Full final validation remains engine 2,550 passed/1 skipped, SDK 525,
architecture 101 and scoped Ruff clean. No production or test changes followed
acceptance; subsequent edits only finalize reports and triage. The runner
status files are historical execution records; [triage-status.json](triage-status.json)
is the authoritative review completion state. Nothing committed or pushed in
this pass.
