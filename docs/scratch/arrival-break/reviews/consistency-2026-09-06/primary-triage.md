# Fable-low recommendations/worklist review — primary triage

Status: completed September 6, 2026. One tool-free Fable 5.1 review ran at
**low** effort on frozen, hashed recommendation documents and selected source.
No implementation changes were made. Raw output is retained in
[the findings](recommendations-worklist-findings.md); reviewer conclusions
below are adjudicated against current source and root's focused checks.

Fable's overall judgment was favorable, with six proposed findings. These are
not six newly confirmed production bugs. The useful additions are same-height
read-basis checking, precise failure-phase/cause preservation, a conservative
boundary-name reservation, an explicit credential request prerequisite, and
collector/coordinator error separation. The aggregate-routing allegation was
based on an incorrect assumption about an omitted helper.

## Dispositions

| Finding | Disposition | Resulting recommendation |
| --- | --- | --- |
| F1: normalization loses pre-mutation refusal; replace sync agreement with equality | Partly accepted. Cause/phase preservation is needed; the claimed newly introduced regression and exact-equality remedy are overstated. | C2 now requires phase/cause/effect design before widening normalization. Preserve legitimate newer projection coverage; do not equate a coverage boolean with a full content audit. |
| F2: C3 also needs same-height hash equality | Accepted as a source-confirmed and synthetically reproduced interface discrepancy. The broad helper extraction and extra exception claim are not accepted as stated. | C3 adds equal-ordinal hash disagreement across reads/runtime/declaration preparation, retaining continuation semantics separately. |
| F3: timeline chooses local aggregate shape before effective history | Rejected. Omitted helper explicitly excludes descriptor-bearing roots; summary/state use the same storeless-routing predicate. | No new aggregate routing rewrite. Existing C7 still covers both inspection guards. |
| F4: boundary-bearing-only collision rule is insufficient | Accepted as a useful strengthening/clarification of D4, which already noted passive-loop hydration. | Initial recommendation reserves vertex name from all loop names for Arrival runtime/proposed declarations; explicit compatibility restriction, not a wire-label change. |
| F5: key mapping requires a non-path credential request | Accepted prerequisite; rejected suggestion to bind every identity to genesis observer or require it to equal vertex name. | New D0 distinguishes custody namespace + exact observer + domain selection from lineage/position verification context, including bootstrap. |
| F6: source bookkeeping errors are misattributed; cleanup incomplete | Root probes confirm these behaviors for custom iterators and injected ID failure. Durability consequence is narrower than reviewer suggested. | C8 split: initializer re-raise with C3; stream ownership, primary-error preservation and paired fact/ID evidence next. |

### F1 — Existing uncertainty and diagnostic loss are different issues

`engine.arrival_maintenance.sync_projection` validates role, registry open,
target/capabilities and initial snapshot before its mutation-attempt wrapper
(lines 192–242). Failures there do not all become `ProjectionSyncError`.
After entering `maintenance.catch_up`, the wrapper conservatively retains
target, before, observed-after and `cause` (lines 244–294). File-adapter
preflight refusals can occur within that call before row mutation; existing
tests already expect `ProjectionSyncError` for unwatermarked rows and foreign
identity markers. Thus the top-level uncertainty is already present in the
engine contract; merely using the existing SDK mapping does not create it.

There is nevertheless a real diagnostic concern: `sdk.errors._identity_details`
does not serialize that underlying cause. SDK normalization would lose details
that an in-process caller can currently inspect through `ProjectionSyncError.cause`.
`arrival_search.sync_search_index` also wraps failures after target selection,
including projection preflight before `maintenance.build`. The next slice must
distinguish known phase/effect evidence before choosing a public category.
It must not infer zero mutation solely from `NotAuthority` or another nested
exception type, since those can also arise during post-write validation.

Reject the suggested `projected_after == target` replacement for sync success.
An independently validated projection can legitimately advance beyond target;
the engine deliberately reports that actual prefix. Root reran
`test_later_maintainer_advance_is_reported_as_successful_actual_prefix` successfully.
The ordinal coverage predicate follows custody validation; it is not used as
its replacement. Documentation should call it coverage and avoid claiming
full row-content agreement.

### F2 — Hash disagreement at one ordinal is a useful missing check

`arrival_consumer.open_read` resolves the observed watermark but, on a fresh
non-continuation read, accepts a different hash at the captured ordinal into P.
`runtime_write._current_write_basis` explicitly refuses that combination.
Declaration preparation also lacks that equality check while independently
assembling basis. Root's synthetic `AttestedLedger` subclass reports captured
`Head(L,3,old)` and then resolves the watermark to `Head(L,3,replacement)`:
read opening accepts inconsistent H/P while runtime basis construction raises
`RuntimeWriteRefused`.

This is a disposable interface-substitution probe, not a reproduced concurrent
filesystem attack or proof of full projection integrity. It is sufficient to
add the consistency case to C3. Keep a narrow membership/basis helper; neither
the complete read opener nor continuation lifecycle belongs inside every writer.

The reviewer also asked whether `ProjectionBehind` is a declaration preparation
error. It is a `ContractRefusal`; `prepare_declaration_edit` catches it in its
generic `Exception` arm and wraps it in `DeclarationPreparationRefused` with
exception chaining. It does not simply leak out as asserted in one alternative.
Any cause/detail standardization belongs to C2, not a second unproven high-priority
correctness finding.

### F3 — The omitted helper disproves the proposed trigger

`sdk.aggregate.has_local_descriptor_aggregate` (lines 402–427) explicitly returns
False when `descriptor_for(root_ast, root)` exists. It routes only storeless
composition with Arrival descendants. `read_summary`, `read_state`, and
`read_timeline` all use it. Descriptor roots first capture effective history;
`arrival_aggregate.capture_aggregate` expands children from that effective AST.

Root reran both SDK regressions for effective-discover versus cached children
and unadopted local-discover versus effective single-store shape: both passed.
No contradictory aggregate rewrite was added to the worklist.

### F4 — Reserve the ambiguous namespace initially

Hydration uses `_loops.get(tick.name)` for every owned tick, then independently
checks `tick.name == vertex.name`; `Loop.replay_boundary` can reset state/counts
without a loop boundary trigger. A loop tick can also advance the vertex period
edge. An initial rule restricted to boundary-bearing loops is therefore unsafe.

D4/C5 now recommend all loop/vertex name equality refuse at Arrival runtime
materialization and proposed-declaration validation. This is an explicit new
supported-subset restriction to test and document, including existing callers;
it is not an implemented gate or a ban on reading/exporting historical evidence.
Relaxation later requires proof that production and hydration are unambiguous.

### F5 — Request shape before mapping layout, without collapsing identities

Current `CredentialProvider.for_write(vertex: Path)` cannot express the requested
observer/domain/context and its callbacks do not expose general public-key
binding evidence. New D0 names the local binding selector and separates it from
captured lineage/position verification. Bootstrap has an explicit founding
observer and reserved intent, not a fake pre-genesis head.

Reject a universal genesis-observer mapping: multi-observer facts select their
own authors; vertex name is separate; the outer tick's custodian label is a
specific wire-profile role and its envelope remains unsigned. Inner tick
receipt-signing follows its own existing policy. No new requirement equating
founding observer and vertex name is warranted.

Repository search found only default `CustodyCredentialProvider()` construction
in source/tests; external callers of the inert `key_dir` argument are unknown.
The proposed explicit refusal still needs compatibility documentation.

Root also clarified the coordinate: declaration preparation uses
`keys_valid_at(observer, H.ordinal + 1)`, so introduction at H can authorize a
successor without retroactively authorizing the record at H. Ordinary runtime
planning invokes supplied fact/Arrival callbacks and does not perform the
declaration editor's `_signed_with_existing_key` check; the new provider's
binding-evidence guarantee remains proposed. Optional-signature policy is not
silently replaced by mandatory signatures or global trust.

### F6 — Confirmed local behavior; do not overstate persisted harm

Root invoked `_collect_one` with a disposable custom async iterator:

- Injected `id_factory` OSError becomes status `error`, with collector lifecycle
  error fields, one fact and zero IDs; `aclose` is not called.
- Collector exception after one fact returns error with one matching ID but
  still does not call the custom iterator's `aclose`.
- Cancellation propagates as cancellation, but `aclose` remains uncalled.

The first case is coordinator failure misattributed as collector failure, plus
inconsistent retained pairing. However, `prepare_collected_tier` subsequently
uses `zip(..., strict=True)` and refuses the mismatch before planning the tier.
The reviewer did not establish that a misleading lifecycle fact was appended;
root does not claim that outcome.

Moving all ID creation “outside the loop” is not by itself a sufficient design
for a streaming collector. Pair fact/ID retention atomically and separate error
provenance. Cleanup must preserve the primary exception/cancellation when close
also fails; blindly adding a finally that can mask the primary error would
repeat a previously remediated export failure pattern.

## Revised first implementation slice

1. C3: shared narrow custody/basis rule, including equal-ordinal hash agreement;
   regressions for legitimate advance, fabricated/foreign prefix, same-height
   substitution, and unchanged continuation behavior.
2. C8a: unchanged initializer exceptions propagate without a self-cause.
3. C1 can proceed independently as the registry-injection slice.

Then specify phase/cause/effect evidence for C2 before widening normalization.
C8b collector ownership/bookkeeping is a separately bounded correctness slice.
C5's name reservation and D0's credential request precede broader identity work.
No new wire format, live migration, or implementation changes occurred here.

## Review and validation record

- Fable model metadata verified: `claude-fable-5-1`, requested `--effort low`.
  One small Haiku CLI helper emitted 17 tokens; it was not the substantive reviewer.
- Fable usage: 48,896 cache-creation input; 3,264 cache-read input; 9,219 output
  tokens, including 5,913 thinking tokens. These categories are not summed.
- All packet source hashes matched when the review started. Reviewed documents
  are preserved as `*-reviewed.md`; subsequent recommendation edits are root's
  triage, not a second Fable approval.
- Root ran four targeted engine maintenance tests and two SDK aggregate tests:
  **6 passed**. These are existing tests, separate from the prior 56-test audit.
- Disposable probe source is retained as [review-probes.py.txt](review-probes.py.txt),
  with [observations](probe-observations.json). No live store/key was accessed.
- [Scope check](scope-check.json) records implementation hashes, reviewed-source
  hashes, documentation changes and link validation. No review process remains.
