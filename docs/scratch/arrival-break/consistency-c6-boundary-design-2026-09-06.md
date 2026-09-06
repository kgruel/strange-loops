# C6 — boundary continuity design

Status: accepted by root after two Fable 5.1 **high** design reviews and
source/test-backed triage. Implementation is now authorized within this design.
The follow-up raw verdict remains REVISE; its sole new blocker was disproved
by the existing params-pin gate. See the retained review triage.
Baseline `ef8b21b2` on `arrival/finish` includes
the accepted C3 continuation checkpoint. This document is the proposed decision,
not a claim that current runtime already enforces it. Sol audits engine history
and replay, Terra SDK operations, Luna independent failure cases, and root owns
the policy and review triage.

## Decision and scope

A continuing boundary keeps its recorded consumption history. An ordinary
declaration edit changes the current interpretation of facts; it does not
restart that boundary. The proposed identity for this supported subset remains
the exact local vertex name, boundary role, and boundary name. No declaration
hash, file path, projection generation, or new wire identifier becomes identity.

The recommended policy is **inherit for in-place edits**. A trigger/count,
condition, fold, parse, route, or dispatch edit keeps the existing tick edge.
This is an explicit interpretation policy, not a claim that the old tick would
have fired under the new rules. A pending fact already consumed by that edge
does not become eligible again just because a declaration changed.

Whole-loop retirement followed by same-name recreation needs separate evidence
when an old local tick exists. A tick whose loop/vertex role was ambiguous when
received also cannot become unambiguous through a later configuration edit.
Those cases refuse runtime when the target consumes that ambiguous stream.
Removing the consumer is allowed; reintroducing it re-exposes the same conflict.
Facts, ticks, and declarations
remain available as evidence; no prior row is changed or relabeled.

The user has been offered a choice between inherited in-place trigger/count
edits and a stricter interim refusal of those edits. No answer has arrived as
this draft is prepared for review; root proceeds with the recommended inherit
policy as a stated assumption. Any later answer and the adversarial design
review must be reconciled before implementation. Credential requests and persisted bindings (D0/D2), explicit
same-name restart/carry ceremonies, and durable vertex IDs are separate work.

## What the implementation actually does today

`Vertex.hydrate_snapshot` re-folds captured facts under the current declaration
in receipt order. It does **not** deserialize an old tick payload as current
fold state. A local loop tick invokes `Loop.replay_boundary`: reset to the
current initial state when reset is enabled, clear repeating-count bookkeeping,
or mark a one-shot boundary exhausted. A local vertex tick restores the vertex
period timestamp and does not reset every loop.

`plan_pending_boundaries` selects the greatest event-time/receipt edge per local
tick name. Facts at an equal timestamp precede or follow that edge by receipt
coordinate. This remains distinct from the tick's fact cursor and from
declaration receipt ordering. Count boundaries remain ingress-driven.

The grammar currently exposes `when`, `after`, and `every`; its compiler always
sets loop-boundary `reset=True`. The lower-level `Loop` supports carry, but
there is no public declaration reset/carry edit to implement in C6. Fold
overrides replace initial state and fold code, not declared boundary reset.

Consequently an in-place count edit retains the recorded boundary and replays
facts after it. The exact existing count-recovery behavior is:

| Target mode and retained evidence | Hydrated state and next behavior |
| --- | --- |
| `every M`, with an owned tick and K subsequently routed facts | Count is K, including when K >= M. Hydration does not fire. If K >= M, the next accepted routed ingress fires; otherwise M-K more routed facts are needed. |
| `every M`, with no owned tick and K replayed facts | Existing recovery sets count to K modulo M. It creates no missing historical ticks. |
| `after M`, with any owned loop tick | Inherits an exhausted one-shot boundary. New ingress does not restart it. |
| `after M`, with no owned tick and K replayed facts | Exhausted when K >= M; otherwise count is K. A fresh name can therefore already be exhausted by older facts. |
| `after` changed in place to `every M`, with an old owned tick | Current repeating mode resumes from that retained tick and subsequent routed facts, not from the declaration edit. |
| Kind-trigger edit with an owned tick | Pending evaluation retains the old event-time/receipt edge; only unconsumed facts are checked against the new trigger/conditions. |

A user wanting a fresh count or first firing is requesting a restart; C6 does
not silently provide one. Historical payloads keep their original meaning and
bytes even when current replay differs. Count-return values ignored during
hydration must not turn into retrospective dispatch or appended ticks.

Sources: `libs/engine/src/engine/vertex.py:784`, `:1260`;
`libs/engine/src/engine/loop.py:157`;
`libs/engine/src/engine/compiler.py:541`, `:890`;
`libs/lang/src/lang/document.py:463`, `:1100`.

## Contract matrix

| Situation at the bounded head | Supported result |
| --- | --- |
| Same continuously present loop, unchanged declaration | Inherit its recorded reset/count/period and pending consumption evidence. |
| Same continuously present loop, edited fold/parse/routes/trigger/count/conditions/run or presentation | Inherit the same edge and replay under the new interpretation; no implicit restart. |
| No local ticks for a loop; edit, remove/recreate, or introduce a boundary | Allowed, subject to existing checks. Older facts may replay and pending triggers may become eligible; this is not a fresh-facts cutoff. |
| Remove a loop that has old ticks | Allowed when it is absent from the proposed runtime. Preserve old ticks as evidence. |
| Reintroduce that retired runtime name after it had a local tick | Refuse ordinary declaration preparation/preview and runtime capture. A final-document comparison alone cannot detect this. |
| Add a genuinely unused loop name | Allowed. It has a distinct future tick identity, but may still consume older facts selected by current routing. This is not state carry or an explicit restart. |
| Vertex boundary list edited in place | Inherit the vertex-name edge. Declaration order remains meaningful; no new vertex identity. |
| Historical tick had `origin == name == vertex` while that loop also existed | Refuse when the target has a vertex boundary. A corrected target without that consumer may run, but adding a vertex boundary later refuses. The old row remains ambiguous. |
| Historical collision existed but produced no ambiguous local tick | Permit a collision-free append-forward correction. Preserve C5's existing accepted case. |
| Foreign or originless tick | Keep as evidence; it does not establish a local edge or a local incarnation conflict. Equal labels in another lineage prove no identity. |
| Owned tick predates the own declaration genesis | Refuse if the target consumes its loop name or vertex period: no recorded declaration establishes its role. Removing that consumer can avoid the conflict; a new name is not a historical alias. |
| Tick could belong to a generated name whose historical expansion is not recorded | Refuse the affected runtime interpretation as unprovable; current files/environment cannot provide historical evidence. |
| Explicit restart, state carry, alias, or same-name incarnation cutover | Deferred new protocol behavior; not inferred from an ordinary edit, projection rebuild, or locator move. |

Removing an explicit `cite` declaration still leaves the implicit runtime
`cite` loop. That is an in-place interpretation change, not retirement of the
runtime name. Likewise, disabling a loop's boundary leaves the loop present;
old ticks still reset it under current hydration. The declaration representation
and the effective runtime namespace must not be conflated.

## History and evidence algorithm

The shared validator is pure over one captured declaration anchor, complete
self-lineage declaration fact history, bounded ticks, and the target document
set (effective current state for runtime, proposed successor for editing).
It does not open a store, sign, read keys, consult external source files or the
environment, repair projections, or execute any source/dispatch command.

1. Validate the declaration anchor against the captured full H through the
   existing custody/projection contract. Select only the own genesis and
   self-lineage declaration overlays. Foreign and unscoped declarations remain
   inert, matching the existing resolver. Sort by receipt ordinal and sequence,
   never authored time or fact ID.
2. Reconstruct effective runtime names at the genesis and each committed
   declaration revision. Preserve retirement evidence across intermediate
   revisions; do not compare only genesis/current or before/proposed documents.
   Multiple declaration documents in one Arrival batch form one revision:
   evaluate the resulting effective set, not transient partial document states
   with no observable runtime between them. This grouping is for namespace
   continuity; document overlay order remains receipt-sequence order. Wire
   batches contain fact rows only; a CAS containing fact and tick drafts gives
   those drafts distinct record ordinals. A query reporting an owned tick and
   declaration fact at the same ordinal contradicts this shape and refuses
   with both actual coordinates. Do not invent an ordering for that adapter
   contradiction. This is not a newly legal mixed-row record format.
3. At each owned tick's receipt position, classify its role using that revision.
   A vertex-name tick with a simultaneously present loop of that name is
   ambiguous. A currently relevant loop-name tick with no provable historical
   loop membership is unproven. Tick payload shape, signature, cursor, or
   current name validity cannot recover the missing role evidence.
4. For each target runtime name with historical local ticks, require continuous
   membership since the relevant tick. A disappearance and later return
   conflicts even if its final declaration equals the earlier one. Internal
   tracking of membership intervals is evidence analysis, not a newly minted
   persistent incarnation ID. Ignore retired names that the target does not
   interpret. An ambiguous vertex-name tick matters when the target declares
   a vertex boundary; without that consumer the saved period field has no
   supported Arrival effect. Later re-enabling that boundary restores the
   refusal, not the missing role evidence.
5. Analyze the proposed successor as one additional revision with no fabricated
   fact ID, timestamp, ordinal, or Commit. This allows retirement and safe
   configuration correction even when the old runtime itself refuses. Run
   the check for no-op proposals too; no-op does not certify unsafe execution.
6. Return normally or a deterministic diagnostic naming the reason, boundary,
   and actual conflicting tick/declaration receipt where available. Do not
   manufacture an epoch/cutoff or report guessed identity as proven.

The custody-bounded query is still an adapter contract: completing a watermark
does not independently establish row agreement or prove a projected declaration
was authored by the claimed observer. C6 adds continuity analysis, not a second
custody audit or new tick-authentication rule.

The evidence read is through captured H even when event timestamps are negative
or far in the future. `TickRequest` defaults to `since=0`; the validator must
explicitly request the full timestamp range. Existing hydration/pending
timestamp selection is a separate policy and must not be widened accidentally.

Use documents as the common target input for all three entrypoints. The result
includes the target's provable runtime names and unresolved-generator flag.
Apply C5 reservation to provable names, including literal generated loops,
during declaration preview and preparation as well as runtime. Runtime also
checks names in both directions: every provable target name must be materialized
(including implicit `cite`), and every actual compiled name must belong to the
proved set or be covered by an explicitly unknown generator. An unexplained
extra or missing name refuses before hydration. Thus current parameter-file
changes between verification and compilation cannot silently remove a proved
consumer. This checks names, not arbitrary fold-code equivalence.

Unchanged wire declaration decoding remains authoritative. Prefer sharing the
existing overlay step/ordering code rather than introducing a second subtly
different definition of self-lineage history. Unknown declaration kinds retain
the resolver's forward-compatible inert treatment; malformed supported
namespace evidence refuses rather than yielding a fabricated safe history.

## Generated loop names

Only template sources with a declared `loop` generate runtime loop specs in
the current compiler. Bare paths, inline source commands, and templates without
such a loop do not create additional loop identities. They must not trigger a
blanket source-history refusal.

For a template loop, literal inline parameter rows and the stored loop document
can establish generated names without opening the template file. Match the
compiler's actual ordering and override semantics: sources sorted by recorded
order/subject, parameter rows in order, generated specs overriding explicit
specs at equal names. Variables used only by collection commands do not make a
literal loop name unprovable.

A `from` parameter file's hash pin commits to historical bytes. If bytes
available now verify against the pin recorded for a revision, those bytes can
establish that revision's parameter rows. An absent, mismatched, or unpinned
file supplies no such evidence. Environment-indirected `kind` remains unknown
even in verified rows because the resolved environment value was not recorded.
Unknown generators can produce/override any name, including the vertex name.

Keep the classifier pure with explicit `verified_params: hash -> ordered rows`
evidence. A shared caller-side collector used by runtime, preparation, and
semantic preview obtains candidate bytes from captured historical parameter
paths relative to the locator, hashes those exact bytes, and accepts them only
for matching recorded pins. Parse the same byte snapshot that was hashed;
never verify a path and reopen it to parse potentially changed bytes. Reuse an
extracted form of the compiler's parameter-text parser, preserving encoding,
header, comments, row ordering, and last-column behavior. Do not implement a
second grammar. Cache by verified content hash within this capture only.
Unknown/unavailable evidence remains unknown and only blocks a relevant proof;
an irrelevant unreadable historical source must not poison a direct loop.
No network retrieval or environment resolution supplies historical evidence.

The classifier uses the same whole-value `$NAME` indirection recognition and
`$$` leading-dollar escape as the compiler. Partial strings remain literal,
matching current behavior. Parameter indirection used only by source commands
does not make a literal `kind` unknown. This evidence collector does not replace
current runtime pin verification and compilation, which retain their own checks.

That runtime pin gate already exists: `_build_effective_arrival_candidate`
calls `effective_declaration_from_documents` with default `verify_pins=True`;
the latter calls `verify_source_pins_from_documents`, which checks both source
content and `from.params_sha256` before `compile_sources`. Do not add a duplicate
gate based on the follow-up review's mistaken claim that it is absent.
Continuity here describes the recorded declaration and its pinned expansion,
not forensic proof that every past external program obeyed that declaration.
Unknown legacy behavior or an origin label is not upgraded into authentication.

Use three-valued membership per name and revision. Direct, implicit, or literal
generated membership proves **present** even if another generator has unknown
names: an override changes its interpretation but does not remove that name.
If the name is not in the provable set and an unresolved generator could emit
it, membership is **unknown**. Otherwise it is **absent**.

For every old local loop tick that the target would interpret, membership must
be provably present at its receipt and throughout all later revisions through
the target. Unknown membership anywhere in that interval refuses: an unknown
intervening revision could conceal retirement/recreation without containing a
tick itself. Analyze every relevant tick, not just the newest pending edge;
hydration also consumes historical reset markers. A tick whose name is absent
from the target is not attached to a current loop, so that retired stream alone
does not block execution. Unknown target membership for an old tick refuses.

For a vertex-name tick consumed by a target vertex boundary, loop membership
at its receipt must be provably absent.
Present means a role collision; unknown means its role cannot be established.
The vertex identity itself continues while its boundary list is edited or
disabled, so only loop-name ambiguity at that tick changes this role proof.
Unresolved revisions before all relevant ticks do not, by themselves, create
consumption obligations. This is a conservative evidence rule, not proof that
unknown expansions actually collided. Literal generated sources and provably
continuous direct loops must remain usable. Do not compile old declarations
against current external inputs or claim that no document edit proves stability.

## Integration and effects

- Runtime: invoke the validator in the shared effective-candidate builder
  before `hydrate_snapshot`, pending-boundary planning, signer invocation, and source
  collection. Ordinary, batch, preview, and source paths inherit that one check.
  The lower-level caller-responsible planners remain internal; C6 does not
  pretend to validate an arbitrary caller-built `Vertex` against history.
  SDK credential providers may already have loaded signer capabilities before
  capture; C6 does not claim that loading never occurred or redesign providers.
  Raise `BoundaryContinuityRefused(RuntimeWriteRefused)` retaining the actual
  `basis`, `captured_head`, effective declaration, and a small immutable issue
  DTO. Expose actual `tick_id`, receipt `ordinal`, relevant declaration `fact_id`
  and `vertex` through existing C2 scalar evidence fields when known. The local
  planning attempt has phase `prepare` and custody append not entered; it does
  not erase prior successful source tiers or imply an external witness did not
  advance. The diagnostic contains no full source/record payloads.
- Declaration preparation: validate the proposed successor at the same CURRENT
  basis after history/custody checks and before key-history work that invokes
  signers or creates drafts/intents. Use `DeclarationPreparationRefused` with
  established prepare/custody-not-entered evidence and captured H. An accepted
  registry open may still advance an external witness; custody-not-entered
  refers to append, not an assertion of zero effects anywhere. Preserve the
  structured conflict as an explicit exception cause (`raise ... from ...`);
  C2 already serializes `__cause__`. A general cause parameter on every
  preparation refusal factory is unnecessary. Raise that explicit preparation
  refusal ahead of the generic basis-error wrapper, preserving a continuity
  diagnostic instead of mislabeling it as failure to capture the basis.
- SDK semantic preview: use the same bounded history/target validator, with its
  existing normalized refusal family and no invented signing/Commit evidence.
  A preview must not say applicable for a proposal that the history gate refuses.
- Reads/verify/export: do not add this execution gate to evidence reconstruction
  or ordinary read APIs. Read-state interpretation remains available and is not
  a certification of safe runtime continuity.
- Legacy attached `Vertex.replay`/`evaluate_boundaries` and `load_vertex_program`
  are outside this supported Arrival capture contract. Their separate origin
  and variable-substitution behavior remains legacy-retirement work; C6 must
  not claim to have made every historical CLI/runtime path conformant.
- Initialization has no old tick history. C5's pre-genesis name check remains;
  no pointless history pass or key migration is added.
- Existing declaration apply/recovery uses its frozen plan/durable intent.
  Runtime capture independently rejects any unsafe history imported or appended
  through other mechanisms. No recovery rewrite, automatic retry, or implicit
  transition is introduced.

## Acceptance and staged work

Engine tests must reproduce the old acceptance of a ticked remove/recreate and
of a corrected historical loop/vertex collision. Assert the refusal happens
before hydration, signing, append, pending planning, or collection as appropriate.
Use full bounded receipt histories, including intermediate retirement, batched
changes, equal/out-of-order event times, foreign declarations/ticks, a relevant
undeclared historical tick, implicit `cite`, and stale local-file disagreement.

Positive engine and real SDK scenarios must demonstrate in-place fold and
boundary-count edits retaining edges, `after` inheriting exhaustion, tick-free
changes reinterpreting older facts, retirement followed by a fresh-name
replacement, unchanged/literal template sources, and tick-free C5 repair.
Keep evidence reads/export working for refused histories and verify exact
custody prefix preservation through an accepted appended correction.

Negative source scenarios cover missing/mismatched historical parameter pins
and env-derived generated names with old ticks even when source documents are
unchanged. Positive scenarios prove historical pin-matching rows work in all
three entrypoints, direct names stay provably present despite unrelated unknown
generators, and a file replacement between read/hash/parse cannot substitute
unverified rows. A command-only source edit with provable names remains usable.
Test ambiguous-history repair without a vertex consumer, followed by refusal
when one is proposed again. Exercise every row of the count-recovery table,
including a fresh-name `after` already exhausted by old facts.

Stages: root reconciles this design and agent audits; freeze exact design and
supporting source packet; Fable 5.1 high reviews it; root triages all findings
and revises/re-reviews material contract changes. Only then assign Sol engine
implementation, Terra SDK acceptance, and Luna independent validation. Run
focused regression/baseline demonstrations followed by engine, SDK, architecture
and scoped lint checks. Finish with the established Fable implementation review
(low effort unless the user asks otherwise). No implementation starts merely
because a reviewer process exited successfully; its findings must be resolved.

An explicit boundary transition remains future design: it would append intent
and a receipt-grounded cutover, identify the relevant role/name and predecessor
evidence, define restart versus carry, and preserve all historical rows. C6
does not smuggle that new replay protocol into a routine declaration edit.
