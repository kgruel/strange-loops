# Adoption: five Fable findings remediated

Baseline: `69852066`. Original review and independent reproductions are
checkpointed in `72fe4781`. This report describes the correction submitted
for a second Fable 5.1 review, not that review's verdict.

## Changes

1. Preparation now requires independent FACT and ARRIVAL verifiers. The SDK
   supplies custody-owned Ed25519 domain verifiers. After the two mapped
   requests, preparation verifies the anchor against the actual binding key,
   which need not be the first valid key in the captured registry. A provider's
   permissive local verifier can no longer approve invalid anchor signatures.
   The shared builder can produce a draft without a fixed preselected key;
   initialization retains its original explicit key and verification behavior.
2. Once recovery recognizes the exact anchor at S+1, it updates and persists
   phase `appended` before synchronization. Both a phase-save failure and a
   later sync failure preserve the known Commit(S,A) and appended phase.
3. Apply retains a pending intent after stale-head or contract refusal. Explicit
   recovery retires it only when Full verification of S+1 and exact comparison
   prove that another record occupies the reserved position. It then reports a
   stale refusal naming retirement; the caller must select a fresh head for a
   fresh adoption. Transient refusals retain the original recovery evidence.
4. Intent parsing validates object/string/list shapes and scalar coordinates.
   Exceptions from reused declaration helpers are translated to
   `AdoptionApplyError`; malformed JSON no longer escapes the SDK error family.
5. Preparation checks maintenance capability through an attested, nonmutating
   coordinator before resolving any signing credentials. The same capability
   checks are shared with actual synchronization. Missing maintenance, absent
   catch-up, and incompatible rebuild capability refuse before the anchor append.

## Regression evidence

- Real migration signatures and mapped keys: independently reject junk FACT
  and ARRIVAL signatures despite a permissive custom verifier; accept and
  verify adoption under the second of two captured valid observer keys.
- Lost append response followed by maintenance or phase-save failure: exact
  commit retained, phase `appended` reported.
- Different Full-verified successor: retire the old intent, preserve custody,
  and successfully prepare/apply at the new explicitly selected head through
  both engine and SDK paths. Transient recovery refusal preserves the intent.
- Malformed intent roots, descriptor/binding shapes and inconsistent exact
  drafts: typed adoption/SDK errors without custody writes.
- Missing/incompatible maintenance: no credential resolution, no catch-up
  call, no anchor append or adoption intent; opened maintenance handles close.

All fixtures and credentials are isolated and synthetic. No live migration,
new intent-authentication wire scheme, report-domain change or live coordinator
was introduced. Local intent-coordinate tamper protection beyond the existing
content-signature contract remains an explicitly separate threat-model question.
The second Fable packet includes the original findings, triage, changed code,
tests, and the supporting code omitted from the first packet.

## Second-pass follow-up

Fable's second review accepted F1–F4 and found one remaining P2: recovery
could use a registry without maintenance and append before refusing. Both apply
and recovery now preflight their actual registry immediately before append.
Failure retains the intent and returns a typed precommit recovery error.
Recovery also loads the intent under its declaration lock, exposes retained
stale intent paths, and wraps storage-open failures without obscuring any commit.
Pinned source drift requirements are documented. Luna's independent follow-up
found no remaining blockers; targeted SDK/migration checks passed (24 tests).
A final focused Fable closure pass reviews these corrections.
