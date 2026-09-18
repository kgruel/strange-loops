# Fable 5.1 adversarial review — primary triage

Verdict: **REVISE**. Five P2 behaviors reproduced; no P1 reported. Runtime
source remains exactly at `69852066833a87ad1d6a84fd97ae9d21ff26bdfe`.
No fixes were applied in this review pass.

## Review provenance

Claude CLI 2.1.276, model `claude-fable-5-1[1m]`, high effort, safe mode,
no tools, no session persistence. The CLI returned success and model usage
confirms `claude-fable-5-1` produced the review. The 15-token Haiku auxiliary
call is recorded separately in native model usage; it did not produce the
review. The packet contains the implementation, contract, relevant helpers,
SDK surface and tests, but omits prior review verdicts. Its source hashes
match the reviewed checkpoint. `manifest.json`, `status.json`, `result.json`
and `findings.md` preserve the exact evidence.

Fable performed static review. Primary independently executed `reproduce.py.txt`
and `sdk-signature-probe.py.txt` in temporary isolated roots, using fixture
helpers from the repository. No live source, credential or witness store was
accessed. `reproduction-results.json` and `sdk-signature-probe.json` contain
native probe results. The pre-review targeted suite still passed: 27 tests.

## Findings and dispositions

1. **P2 — ACCEPT: apply/recovery disagree about signature validity.**
   Public `sdk.adopt_arrival` accepted a custom mapped resolver returning
   junk signatures with a permissive caller-supplied verifier. The migration
   genesis used real Ed25519 signatures and real mapped binding evidence.
   Adoption returned `applied`, advanced ordinal 2 to 3, and `read_summary`
   succeeded although independent FACT and ARRIVAL verification both failed.
   A second engine reproduction demonstrates that a post-append interrupted
   adoption cannot then recover under independent public verification.
   This is a custom-provider/misconfiguration boundary; no defect was shown in
   the built-in mapped provider's signer. Preparation should independently
   verify both domains against the actually selected bound key, as recovery
   already does, instead of relying solely on the injected provider verifier.

2. **P2 — ACCEPT: reconciled known commit retains an unknown phase.**
   An append wrapper performed the real append, then raised to simulate loss
   of the response. Apply retained `append-unknown`. Recovery recognized the
   exact committed record; an injected maintenance failure then returned
   `AdoptionCommittedIncomplete`, Commit(0,1), and phase `append-unknown`.
   Reconciliation should advance its phase to known appended before sync,
   preserving the known commit even if saving that phase fails.
   Fable's suggested `after-append` hook alone would not reproduce this:
   that hook runs after the appended phase is saved. The executed probe
   exercises the actual lost-return branch instead.

3. **P2 — ACCEPT: no API resolution for a provably superseded intent.**
   Reserved adoption at S, appended a different ordinary record at S+1,
   then recovered: `AdoptionStale`, with the old intent retained. A fresh
   preparation at the new head succeeded, but apply refused because that
   same obsolete intent remained. Add a deliberate cancel/supersede path,
   or remove/archive the intent only after proving its draft cannot have
   landed. Do not blindly extend cleanup to every `ContractRefusal` merely
   because the review suggests it; transient refusals can have a different
   recovery disposition. This is a liveness gap, not silent history mutation.

4. **P2 — ACCEPT: malformed intent escapes adoption/SDK error families.**
   `[]`, `null`, a JSON string and a string-valued descriptor produce raw
   `AttributeError`. Changing a draft without updating `exact_drafts` produces
   `DeclarationApplyError` rather than `AdoptionApplyError`. Inputs remain
   unchanged; the defect is the promised error boundary. Validate JSON shapes
   and translate reused declaration-helper failures into adoption failures.

5. **P2 — ACCEPT, narrower impact: required maintenance is not preflighted.**
   A valid registered File adapter with its maintenance opener omitted passed
   preparation and appended an anchor. Apply and recovery then both returned
   committed-incomplete caused by `NotSupported`. This capability absence was
   knowable before append. Require the needed capability before signing, using
   an attested capability check consistent with the registry's maintenance
   boundary. Fable's claim of an unrecoverable anchor is too strong: the probe
   successfully recovered once the proper maintenance registration was supplied,
   with no duplicate append. Ordinary built-in registration includes maintenance.

## Optional and unresolved observations

- `vertex_to_documents` includes the vertex name in both singleton subject and
  payload (`libs/lang/src/lang/document.py:739`); the name-omission question is
  resolved and is not a defect.
- Ordinary declaration resolution does not independently authenticate anchor
  signatures; the real SDK probe above demonstrates the consequence relevant
  to finding 1 without assuming a reader repair or verification step.
- Whether hostile editing of local intent coordinates must be prevented
  cryptographically remains a threat-model question. Content signatures do not
  bind S or all local binding metadata. This review does not authorize a new
  wire payload or extra signature domain to resolve that question.
- Basis semantics, cross-ceremony pending intents and extra fault coverage
  remain review suggestions, not additional confirmed blockers in this pass.

## Next work

Remediate these five findings, add reproducing regressions, and obtain a focused
Fable verification of the fixes. The previously green functional suites are
not a substitute for those failure-path checks. No source changes, new commit,
push, live migration or release were performed during this review.
