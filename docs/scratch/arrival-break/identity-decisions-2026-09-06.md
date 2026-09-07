# Arrival identity decisions — September 6, 2026

Status: working architectural decisions from the consistency pass. D0/D2 now
have an accepted opt-in implementation including the directory durability
follow-up; later identity items remain as marked.
This document does not ratify a new wire format or perform an automatic
migration. Read alongside the
[contract matrix](consistency-contract-matrix-2026-09-06.md) and
[identity audit](consistency-audit-identity-2026-09-06.md).
Updated after [Fable-low review and root triage](reviews/consistency-2026-09-06/primary-triage.md).
The frozen documents reviewed by Fable are retained with that review. D0/D2
implementation and review evidence is summarized in the
[D0/D2 report](consistency-d0-d2-2026-09-06.md).

The guiding decision is to keep identity, evidence about identity, and local
ways of finding that evidence separate. An observer can interpret several
stores together without those stores acquiring one clock, one authority, or
one shared authentication namespace.

## Existing distinctions to retain

| Concept | Existing evidence / scope | What it does not establish |
| --- | --- | --- |
| Physical lineage | Genesis opens one ordered history; the Arrival declaration anchor must name that same lineage. | A filesystem location, a global observer, or the identity of every vertex that reads it. |
| Full head | `(lineage, ordinal, record_hash)` identifies a custody prefix. | The meanings of its observations or the correctness of projected rows merely claiming its ordinal. |
| Projection watermark and generation | The watermark is resolved through custody; generation detects changes to a derived view. | A watermark alone is not history proof; generation is not a durable semantic vertex ID. |
| Observer label | Exact string in the fact/envelope under its record-kind profile. | A globally authenticated person, a key fingerprint, or a local pathname. |
| Key history | One lineage's verified introductions authorize named keys for named observers at later ordinals. | Global equivalence between equal labels, or automatic revocation of older keys. |
| Origin | Opaque provenance label; current local runtime also uses exact nonempty vertex name equality to recognize its ticks. | A globally unique vertex ID or an authentication claim. |
| Descriptor binding | Backend-owned location interpretation and witness binding evidence. | Identity inferred from filename suffix, or permission to mutate merely because bytes are writable. |
| Aggregate member occurrence | A position in one captured composition with its own read basis. | A new physical lineage, a globally stable occurrence ID, or a single instant shared by members. |

Sources: `arrival_contract.py:Head`, `Watermark`, `ReadBasis`, `Continuation`;
`arrival.py:KeyRegistry.keys_valid_at`; `declaration.py:validate_arrival_declaration_anchor`;
`arrival_binding.py:BindingIdentity`; `vertex.py:_owns_tick`; and the normative
[protocol](../../architecture/arrival/protocol.html),
[wire profile](../../architecture/arrival/wire-format.html), and
[backend contract](../../architecture/arrival/backend-contract.html).
Detailed implementation references and limitations are in the identity audit.

## D0 — Name the credential-binding scope before designing its storage

**Implemented for the opt-in mapped provider:** a local binding is selected by a provider-owned
custody namespace and exact observer label, with explicit signing-domain
selection. Its value is an opaque key reference and enough public evidence to
check the requested signing claim. The custody namespace is explicit local
configuration; it is not silently derived from the vertex filename, declaration
name, or physical lineage. A provider may deliberately reuse a key reference
across namespaces/lineages, but equal observer labels do not authorize that reuse.

Separate this local selection from the verification context: an existing
lineage's captured H and the intended record position determine which historical
keys can substantiate a claim. In particular, a key introduced at H is available
for a successor at H+1, not retroactively valid for the record at H. Existing
declaration preparation uses `keys_valid_at(observer, H.ordinal + 1)`.

| Request | Identity input and evidence |
| --- | --- |
| Fact / batch authorship and author envelope | Exact input author; verification context belongs to the relevant captured lineage. Do not substitute vertex name or founding observer. |
| Declaration edit | Explicit edit author and key introduced through H, valid for the proposed successor. This is not a new administrative-grant rule. |
| Inner tick receipt signing | An explicitly selected receipt-signing capability under its established verification policy. Do not infer the signer from boundary `name` or `origin`. |
| Outer tick custodian label | Physical genesis observer under the existing wire profile; envelope remains unsigned. This label does not make every author or inner tick signer the genesis observer. |
| Initialization | The local request carries the explicit founding observer, domain and purpose. Pending lineage and reserved bootstrap intent are separate engine ceremony evidence, never provider request fields; no pre-genesis H is fabricated. Founding observer and vertex name need not be equal. |

Neutral `CredentialRequest` and public binding evidence now express this scope.
Mapped `WriteCredentials` carry a read-only resolver and domain verifier;
runtime/declaration/source coordinators resolve only after captured authority
is available. The legacy `CredentialProvider.for_write(vertex: Path)` callback
shape remains transitional, and mapped credentials are refused on legacy
engine write paths. Location remains available for ingress/legacy discovery
but is not the mapped identity input. This is an opt-in local custody
implementation, not a wire change or automatic migration.

## D1 — Observer identity survives changes of key and location

**Recommendation:** keep the exact observer label as the protocol's named
identity within its explicit verification context. Resolve local signing
material through an explicit binding for that observer and signing domain.
A key rotation, key relocation, vertex-file move, or display-name change must
not implicitly change that binding.

Cross-store authentication needs the source key history and the position at
which a claim is checked. Equal `observer="alice"` strings in two lineages
alone do not prove the same author. A vertex may group them for its own
purposes, but that interpretation should not be reported as cryptographic
identity. An application can append an explicit association with provenance
when it wants to preserve that conclusion.
Such an association remains application evidence; it is not, by itself,
cryptographic proof of cross-lineage identity.

This does not require replacing strings with global UUIDs or equating an
observer with one public key. The existing protocol supports additional keys
under the same observer. Its introduction rule is additive: old keys remain
valid under that rule. Selecting a new local signing key and revoking an old
key are separate operations; this pass does not invent revocation semantics.

**Implemented D0/D2 subset:** the provider request contains the explicit
namespace, observer, domain and purpose, and resolves an opaque key reference
internally. Captured lineage/head/position and declared receipt keys remain a
separate engine-owned authorization context and are not sent to the provider.
FACT, ARRIVAL and tick commitments stay separate. Operation-fresh credential
acquisition is preserved, and reads, previews and signer loading create no key.
The provider exposes enough public-key evidence for the engine to check the
binding against captured key history. An
arbitrary signer callback or a replacement local key alone does not establish
a valid rotation. Ordinary unsigned observations remain legal where the
operation's policy permits them. Missing receipt-observer configuration creates
no TICK request before the signed era and refuses once a signed era requires a
receipt.

## D2 — Preserve existing custody bindings explicitly

**Implemented as an explicit opt-in:** the filesystem provider has a persisted mapping
from exact observer identity to opaque key references. Keep filenames private
to that provider. This removes the need for every legal protocol label to be
representable as an exact directory spelling.

The current flat/nested resolver remains a compatibility implementation, with
deliberate refusal of ambiguous keys and filesystem aliases. Those refusals
were retained. The mapped provider now specifies:

1. How an existing flat key is bound to its existing self observer before a
   file rename can change the lookup convention.
2. How exact nested identities retain their keys, including distinct labels
   that a filesystem would otherwise alias.
3. How conflicting mappings or mismatched public material refuse without
   minting, overwriting, or silently choosing a winner.
4. How explicit creation publishes one binding and one winning private key
   under concurrent creators, and how interruptions are reconciled.

Bindings use hashed slots over exact strings and verified payloads rather than
encoded identity filenames. Provider-wide mutation locking, durable per-slot
pending intents and no-clobber publication make creation/import recoverable;
losing candidate material is retained for explicit maintenance rather than
deleted in a race. No live key files or stores were moved in this pass, and no
legacy caller is auto-imported.

Root's final durability inspection added parent-directory fsync and reconciliation
of linked-but-unsynced files on retry. The final imported-key correction and
Fable-low review are accepted. These tests check sync ordering and interruptions;
they do not claim to simulate physical power loss. See the D0/D2 report for
frozen review evidence and final 81-test custody validation.

The earlier C4 correction is also complete: the SDK rejects non-`None`
`CustodyCredentialProvider(key_dir=...)` rather than silently ignoring it.
The mapped provider is a separate explicit configuration surface and does not
reinterpret that legacy argument.

## D3 — Vertex continuity is distinct from residence and declaration version

**Recommendation:** a vertex's continued identity should survive moving its
locator and editing its interpretation. Its declaration revision describes
how that vertex interprets captured facts. Here “revision” means the bounded
declaration documents/anchor and H, not an existing public revision-ID type.
Neither physical lineage nor the
hash of that revision should automatically serve as the vertex's identity:
storeless and multi-store vertices make both substitutions inadequate.

Current support is narrower. Historized documents supply the effective name;
runtime ticks use that name as origin. `lang.document.diff_documents` already
refuses post-genesis vertex renames as routine edits, and Arrival declaration
preparation uses that function. Retain that restriction. Legacy local custody
still derives self from the locator stem, so moving a file can change
credential selection even when its declared identity stays fixed. The opt-in
mapped provider instead keeps its explicit namespace/observer binding stable
across locator moves. Any future semantic
rename also has to account for tick ownership by origin; present support is
not a durable identity/alias mechanism.

For the next bounded pass, preserve the existing semantic name and make
credential binding independent of the locator; D0/D2 now provides that opt-in
mapped path. Treat runtime identity rename
as an explicit continuity operation requiring a separate design. Do not
silently translate historical origins or reinterpret a new name as an alias.
A future durable vertex identifier needs a recorded association to existing
names and a policy for storeless vertices; it is not a prerequisite for fixing
the current credential configuration and boundary ambiguity.

## D4 — Boundary identity must be unambiguous within a runtime identity

**Recommendation for the current wire profile:** initially reserve the vertex
name from the loop-name namespace: refuse any loop whose name equals its
vertex name on supported Arrival runtime execution and proposed declarations.
This is an explicit compatibility restriction, not a new protocol label rule.
It covers both production and interpretation of indistinguishable local ticks,
including passive/reset loops and loop ticks mistaken for a vertex period edge.
Validate the effective declaration before planning; validating only
the mutable local file would leave adopted history able to bypass the rule.
Apply the same validation to new/proposed declarations. Do not silently
rename a loop or edit historical ticks.

Conceptually a boundary needs `(vertex identity, boundary role, boundary name)`.
The existing tick profile supplies `origin` and `name`, and cannot always
distinguish the role. Refusal is a bounded way to make the supported subset
unambiguous. Adding a role or a new boundary ID to the wire profile would need
an explicit compatibility decision, including old histories that contain
collisions. Existing ambiguous histories should remain available for evidence
inspection even if runtime execution refuses them.

The refusal predicate must cover both tick production and hydration: current
`hydrate_snapshot` looks up every owned tick by loop name, even if that loop
has no independent boundary trigger. Test same-named passive, count-triggered,
and other boundary forms. Any later relaxation of the initial name reservation
needs evidence that those configurations cannot be interpreted ambiguously. Share
the semantic validator across supported Arrival construction/capture and
declaration preparation; do not make it a guard only in one SDK command.

The recent origin guard is retained: foreign and originless ticks are visible
evidence but do not consume a local boundary. Event timestamp and receipt
position retain their distinct roles; a tick's fact cursor is not a global
consumption cutoff.

## D5 — Declaration edits preserve history; reset must be explicit

**Recommendation:** editing a fold or its presentation appends a new
interpretation. It does not rewrite prior facts/ticks or automatically mint a
new observer, lineage, or boundary. Capture records the effective declaration
used for that operation; a later read may apply a later declaration and reach
a different conclusion honestly.

The accepted [C6 boundary design](consistency-c6-boundary-design-2026-09-06.md)
defines that continuity policy; the [implementation](consistency-c6-2026-09-06.md)
is complete and accepted after Fable-low review. An ordinary
in-place trigger/count/mode, fold, parse, route, or presentation edit inherits
the existing boundary's recorded consumption. Current replay folds facts under
the new interpretation; it does not deserialize old tick payloads as state.
An old tick can therefore exhaust a newly selected `after` mode, while a changed
repeating count resumes from that recorded edge and subsequent routed facts.
The C6 conformance table states these behaviors without inventing a restart.

A runtime name removed and later recreated cannot silently consume ticks from
its former membership interval. History analysis includes intermediate
self-lineage declaration revisions, implicit `cite`, and generated names whose
membership can be established from recorded literals or verified pinned
parameter bytes. Environment-derived historical names remain unproven.
A historical loop/vertex collision refuses when the target consumes its
ambiguous vertex-period stream. A corrected target without that consumer can
run; reintroducing the consumer does not recover the missing role evidence.
Evidence reads remain available.

Explicit restart, state carry, same-name incarnation cutover, and semantic
vertex rename still need a separately recorded transition design. A fresh loop
name establishes a distinct future tick identity but no cutoff for old facts.
Do not substitute a declaration hash as boundary identity: unrelated or cosmetic
edits must not reopen consumed observations. The existing post-genesis vertex
rename refusal remains. Credential-request and persisted-binding work in D0/D2
is now implemented separately from this boundary policy.

## D6 — Result identity describes evidence and actions separately

**Recommendation:** keep one outcome vocabulary across public operations, with
operation-specific evidence. A known actual Commit is retained; an unknown
append outcome is not a refusal or a successful retry. A recovered operation
may be complete without the recovering invocation possessing its original
Commit. It may also find an already-published cache without writing it.

Read bases, projection observations, durable append receipts, witness state,
and artifact-publication state answer different questions. They should be
consistently named and serialized, not flattened into a universal success
boolean. The matrix defines the intended comparison points and proposed
cross-operation checks.

Normalization must preserve evidence of a known pre-mutation refusal when it
exists, including the underlying cause and the operation phase. An exception
type alone cannot prove no write: the same refusal type might follow a
maintainer invocation or a post-write check. Unknown derived effects remain
unknown until adapter/coordinator evidence resolves them. Align that evidence
before mechanically routing more public calls through a normalizer that may
discard the cause.

## Order of work

Captured-basis validation, registry injection, maintenance failure evidence,
ambiguous-boundary refusal and the opt-in D0/D2 custody binding are implemented
and reviewed. The next roadmap work is workload conformance, explicit
maintenance/transfer completion and adoption. C9's SDK/CLI legacy cut follows
after those contracts stabilize. Durable vertex IDs, boundary incarnations,
revocation, cross-lineage identity association and automatic legacy migration
remain separately reviewable designs, not hidden additions to this pass.
