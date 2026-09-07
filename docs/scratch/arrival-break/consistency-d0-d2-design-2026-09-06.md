# D0/D2 explicit credential binding design

Status: accepted after Fable-low clarification and under implementation. The
design itself makes no key, store, or wire-format change.

## Decision

A signing request has three independent identity inputs:

1. an exact, explicitly configured local custody namespace;
2. an exact protocol observer label; and
3. an explicit signing domain.

The local binding key is `(namespace, observer)`. All currently supported
domains select the same opaque local key reference for that binding. The domain
is still present on every request and determines the signature prefix; a FACT
signature can never substitute for ARRIVAL or TICK. Domain-specific private-key
bindings are a future design, not an implicit option in v1.

The captured verification context is separate. For an existing lineage it
contains the captured full Head, successor position, and the keys authorized by
that lineage or effective declaration. It is constructed by the engine after
the registry has attested the target. It is never an input that lets the local
provider infer a namespace or choose another observer.

Equal observer strings in different namespaces do not share a binding.
Applications may deliberately bind an existing managed key reference into
another namespace, but that is an explicit mutation. Namespace, observer, and
public wire strings are compared byte-for-byte as Python strings: no casefold,
Unicode normalization, path splitting, or filename derivation.

## Why the current interface is insufficient

`CredentialProvider.for_write(vertex: Path)` selects only from a mutable
locator. `CustodyCredentialProvider.for_write` eagerly constructs three
path-based callbacks, and custody derives the flat self observer from the file
stem. The callbacks expose neither the chosen key reference nor public-key
evidence. SDK preview, ordinary emit, batch emit, and sources all call this
interface before the engine captures H. Declaration edit does the same through
`_arrival_credentials`.

The runtime then calls those callbacks while planning FACT, ARRIVAL, and TICK
commitments. Ordinary runtime does not currently compare the selected local
author key with captured lineage key history. Declaration preparation does
perform such a check by scanning through captured H and consulting
`keys_valid_at(observer, H.ordinal + 1)`.

Initialization and observer grant bypass the provider entirely:
`init_vertex` and `grant_observer(key=None)` call
`ensure_signing_key`. This must not remain as a hidden legacy-key mutation
when a mapped provider is selected.

Relevant source seams:

- `engine.credentials:WriteCredentials, CredentialProvider`;
- `sdk.emit:CustodyCredentialProvider` and the preview/ordinary/batch calls;
- `sdk.sources:run_sources`;
- `sdk.declare:_arrival_credentials, _init_arrival`;
- `sdk.kind:grant_observer`;
- `engine.runtime_write:capture_runtime, plan_ordinary_write,
  plan_batch_from_capture`;
- `engine.arrival_sources:prepare_source_invocation,
  execute_source_invocation`;
- `engine.arrival_declarations:prepare_declaration_edit`; and
- `engine.arrival_initialization:initialize_arrival`.

## Neutral engine API

The proposed values live beside `WriteCredentials` in
`engine.credentials`. They contain no filesystem or Ed25519 dependency.

```python
class SigningDomain(StrEnum):
    FACT = "fact"
    ARRIVAL = "arrival"
    TICK = "tick"

class CredentialPurpose(StrEnum):
    AUTHORSHIP = "authorship"
    KEY_INTRODUCTION = "key-introduction"
    RECEIPT = "receipt"
    INITIALIZATION = "initialization"

@dataclass(frozen=True)
class CredentialRequest:
    namespace: str
    observer: str
    domain: SigningDomain
    purpose: CredentialPurpose

@dataclass(frozen=True)
class CredentialBindingEvidence:
    request: CredentialRequest
    key_ref: str
    algorithm: str
    public_key: str
    provenance: str

@dataclass(frozen=True)
class ResolvedCredential:
    evidence: CredentialBindingEvidence
    sign_digest: Callable[[str], str]

BindingResolver = Callable[[CredentialRequest], ResolvedCredential | None]
SignatureVerifier = Callable[[SigningDomain, str, str, str], bool]

class CredentialBindingRefused(ValueError):
    reason: str
    request: CredentialRequest | None
    captured_head: Head | None
    use_position: int | None
    evidence: CredentialBindingEvidence | None
```

The request validates non-empty namespace and observer strings but does not
normalize them. `key_ref` is opaque outside the provider. Public outcomes may
serialize `CredentialBindingEvidence`; they never serialize the signer,
private-key location, or provider root.

`WriteCredentials` gains trailing, constructor-compatible optional fields:

```python
binding_namespace: str | None = None
receipt_observer: str | None = None
binding_resolver: BindingResolver | None = None
signature_verifier: SignatureVerifier | None = None
```

The four mapped fields are an all-or-none coherent mode except that
`receipt_observer` is required only when a TICK signature is requested.
Existing `tick_signer`, `fact_signer`, and `arrival_signer` remain the
legacy mode. If mapped mode is configured, the engine never falls back to a
legacy callback for a missing, corrupt, or unauthorized mapped binding.

`WriteCredentials.__post_init__` requires namespace, resolver, and verifier to
be all present or all absent; mapped mode and legacy signer callbacks are
mutually exclusive. Namespace and any supplied receipt observer must be exact
non-empty strings. A receipt observer without mapped mode is invalid. These
static configuration errors raise `ValueError`. When boundary planning produces
a tick without a receipt observer, no TICK request is constructed and the tick
remains unsigned where the captured era permits it. An established signed tick
era instead refuses with `CredentialBindingRefused(reason="missing-required")`.

Resolvers and verifiers are invoked as callables. A provider normally assigns
its bound `resolve` and `verify` methods to those fields. The typed refusal is a
neutral shared precommit cause; runtime, source, and declaration wrappers keep
their established public families and retain it through `cause`/exception
chaining. Its evidence never contains a private path.

A mapped SDK provider may still implement `for_write(Path)` for source
compatibility, but that method only returns this lazy configuration. It must
not load, create, or choose a key. The explicit namespace comes from provider
configuration, not from the Path argument.

An internal frozen `CapturedSigningContext` records:

- `captured_head`;
- `use_position = captured_head.ordinal + 1`;
- verified author-key introductions through H; and
- the effective declaration's current receipt-key set.

It remains separate from `CredentialRequest` and is not sent to the provider.

## Engine resolution and verification rule

The engine signs in this order:

1. Open and attest the descriptor, capture full H, effective declaration, and
   any required projection evidence.
2. Only for mapped credentials, scan the structurally verified custody prefix
   through H and build selective key history using the injected signature
   verifier. Legacy and unsigned paths do not gain this new prerequisite.
3. Construct the exact request for the commitment being planned.
4. Resolve the binding. Verify that the returned request exactly equals the
   offered request and that its key reference, algorithm, and public key are
   well formed.
5. Check the public key against the captured authorization policy below.
6. Sign the digest, independently verify the signature using
   `signature_verifier(domain, public_key, signature, digest)`, then retain
   serializable binding evidence on the plan.
7. Any mismatch refuses before append. It never downgrades a contradictory
   binding to unsigned output.

A missing binding is distinct from corruption. Where the existing protocol
allows an unsigned ordinary fact/envelope, `None` may retain that behavior
and the plan records an unbound/unsigned decision. Declaration edits,
initialization, and a TICK in an established signed tick era require a usable
binding. Alias, conflict, public-key mismatch, malformed state, or resolver
failure always refuses.

### Authorization table

| Commitment | Request observer/domain | Captured authorization |
| --- | --- | --- |
| Inner fact, including each batch row | Exact fact author / FACT | That observer's verified lineage keys valid at H+1 |
| Outer fact or packed batch | Exact envelope author / ARRIVAL | That observer's verified lineage keys valid at H+1 |
| Declaration fact and envelope | Explicit edit author / FACT and ARRIVAL | Edit author's verified lineage keys valid at H+1 |
| Key introduction | Explicit introducing author / ARRIVAL | Introducing author's existing verified lineage keys valid at H+1. The introduced subject may equal the author, but the newly introduced key cannot authorize its own introducing record |
| Inner boundary tick | Explicit configured receipt observer / TICK | Returned public key is in the effective declaration's current declared receipt-key set, preserving the existing any-declared-key policy |
| Outer tick envelope | No signing request | Observer remains the verified physical genesis custodian and the envelope remains unsigned |
| Initialization declaration | Exact founding observer / FACT and ARRIVAL | Planned bootstrap context; both bindings must expose the same public key and verify independently |
| Physical genesis | Exact founding observer / ARRIVAL | Planned bootstrap context and requested founding public key |

For authored records, H+1 is sufficient even when a prepared batch expands to
several physical records: only keys introduced through H may authorize the
operation. A key-introduction draft in the same append cannot authorize a
sibling draft. The tick check uses keys declared in the same captured effective
declaration, not every key ever introduced into the physical lineage. The
request's receipt observer names local selection evidence; it does not change
the wire's existing any-declared-key receipt policy or add a signer identity to
the tick row.

Receipt-observer absence is evaluated only after planning proves a tick exists.
It constructs no TICK request and preserves unsigned pre-signed-era behavior;
it becomes `missing-required` only after captured ticks establish a signed era.

## Runtime integration

`capture_runtime` accepts the mapped verifier configuration and conditionally
retains immutable key-history evidence on `RuntimeCapture`. New fields are
trailing/defaulted so existing direct test construction and legacy callers
remain compatible.

`prepare_ordinary_write` captures before resolving either author domain.
The low-level `plan_ordinary_write` may continue accepting legacy callbacks,
but mapped credentials without a captured signing context refuse rather than
sign without authorization evidence.

`prepare_batch_write` captures once. `plan_batch_from_capture` resolves
FACT and ARRIVAL for each exact author and TICK for the explicit receipt
observer. Repeated requests may be cached only within that one captured
planning operation and only by the complete request value.

Source invocation resolves nothing before initial capture. Preflight uses the
initial context. Later dependency tiers recapture H, rebuild key evidence, and
resolve again before planning that tier. A binding change after collection
therefore causes a retained known-uncommitted tier refusal; collectors are not
rerun. One credential resolution must not be cached across tier captures.

Declaration preparation keeps its existing full-prefix selective registry.
Its signer helper changes to the mapped request path when configured, retaining
the current H+1 author check and independent FACT/ARRIVAL signature
verification. A no-change declaration plan need not resolve a signer.

Preview performs the same captured checks and may compute signatures in memory,
but provider resolution is read-only: it cannot create a key, binding, intent,
directory, or convenience public-key file.

Public plans/results may add ordered evidence for bindings that resolved and
produced verified signatures. Missing bindings and refused attempts remain
explicit in the typed refusal/request evidence; this first slice does not claim
an audit log of every absent or unsigned decision. The additive successful
binding evidence is not a new identity claim.

## Explicit mapped filesystem provider

The v1 mapped provider is separately configured with:

- a provider root;
- one exact custody namespace; and
- an optional exact receipt observer.

It does not accept a vertex-derived default namespace. `CustodyCredentialProvider`
remains the explicitly documented legacy adapter; C4's rejection of non-None
`key_dir` remains in force.

### Storage

Filesystem slot names are hashes of length-framed UTF-8 bytes, never encodings
that are later treated as identity:

```text
<provider-root>/
  bindings-v1/<sha256(frame(namespace, observer))>.json
  keys-v1/<opaque-key-ref>/ed25519.key
  keys-v1/<opaque-key-ref>/ed25519.pub
  intents-v1/<operation-token>.json
```

A binding record contains at least:

```json
{
  "schema": "loops.custody/binding/v1",
  "namespace": "<exact string>",
  "observer": "<exact string>",
  "key_ref": "<opaque provider ref>",
  "algorithm": "ed25519",
  "public_key": "<raw-32-byte base64>",
  "provenance": "created|legacy-import|existing-ref"
}
```

The loader recomputes the slot hash from the exact stored strings, confines the
key reference beneath the provider root, refuses symlinks and non-regular
files, loads the private key, derives its public key, and compares it with the
binding. If `ed25519.pub` exists it must also match. A missing convenience
public file is not created during resolution. This avoids
`ed25519.load_or_generate` silently repairing a mismatched public file before
the binding can be checked.

A binding is domain-independent in v1. Every domain request for the same
namespace/observer returns the same key ref and public key while constructing a
domain-specific signer. A provider returning different refs across domains is
corrupt.

### Atomic creation and concurrency

Every binding mutation—create, import, existing-ref bind, intent recovery and
explicit orphan maintenance—is serialized by one provider-root advisory lock.
Read-only resolution takes no lock and never persists. The provider refuses to
operate on a filesystem where it cannot obtain the configured lock semantics;
an in-process mutex alone is insufficient.

Creation requires an explicit operation token and follows a recoverable state
machine while holding that lock:

1. Publish a complete, fsynced creation-intent file using a temp file plus
   no-clobber hard link, then fsync the parent. The intent fixes namespace,
   observer, candidate key ref, and creation/import source. A repeated token
   must match exactly.
2. Create the candidate key object under its unique ref. Publish complete key
   files before any binding can name them and fsync the key directory.
3. Build and fsync the complete binding JSON in a temporary file.
4. Publish the binding slot with a no-clobber hard link and fsync its parent.
   Never create the final slot and then write into it.
5. Mark the intent complete atomically. If the slot already exists, validate
   and return it; never replace it or delete any intent-retained candidate.

A crash before the intent has no durable effect. At most one pending intent may
exist for a namespace/observer slot. A crash after intent but before binding is
resumed with that intent's candidate key ref. A new call with a different token
must return recovery-required (or explicitly resume the named pending intent),
not generate a competing candidate. A crash after binding publication is
reconciled by comparing the slot with the intent.

The provider-wide lock means two live creators do not both generate candidates:
the second observes either the first pending intent or the completed binding.
A pre-existing binding with different requested public material is a conflict,
not a rotation. Candidate key objects retained by incomplete or losing intents
are never deleted automatically; an explicit locked maintenance operation may
classify them after checking all binding and intent references. Anonymous temp
files are removable. Rotation and revocation remain outside D2.

The pending intent is indexed by the same namespace/observer slot hash (for
example `pending-v1/<slot-hash>` naming its operation token), so discovery does
not depend on an unlocked directory scan. Publishing or removing that marker
and every intent transition occurs under the provider-root lock.

`bind_existing_ref(namespace, observer, key_ref, expected_public_key, token)`
supports deliberate reuse of one already-managed key across namespaces. It
performs the same validation and exclusive publication and never infers reuse
from equal observer labels.

### Explicit legacy onboarding

Mapped resolution never scans `<vertex>/keys`. A separate explicit import
ceremony receives the legacy vertex path, exact observer, destination
namespace, and operation token. It:

1. invokes the current flat/nested resolver without minting;
2. preserves its missing-versus-alias/ambiguity distinction;
3. derives public material from the private key and refuses a malformed or
   mismatched existing `.pub`;
4. copies the private material into a new managed key object with restrictive
   permissions, leaving the legacy files untouched; and
5. publishes one mapped binding through the creation state machine.

The copy is an explicit custody mutation and must be reported. It is not run by
reads, preview, signer loading, write fallback, locator move, or declaration
inspection. Existing labels that the path layout cannot represent cannot be
auto-imported; they can receive a new mapped binding through explicit creation.
After import, moving the vertex locator does not change the mapped selection.

## Initialization and observer grant

Initialization has no captured existing H. It does not create a mapped binding.
The caller first completes the separate explicit creation/import operation,
then supplies that mapped provider to initialization. Initialization resolves
the existing binding read-only using a planned bootstrap context containing the
target, pending lineage and founding observer. This happens before the engine's
durable initialization intent, so documentation and results must call it
planned, not reserved.

Before resolving that pre-created binding, the SDK performs all available
zero-mutation checks: target/intent conflicts, descriptor and declaration
shape, identity collision, key format, and backend atomic capability.
Resolution itself remains read-only.

FACT and ARRIVAL requests must resolve the same public key. The existing engine
then verifies both domain signatures against that key before it reserves the
initialization intent. Recovery continues to use the exact signatures already
stored in that intent and signs nothing.

The first D2 slice should not change the v1 initialization-intent schema merely
to duplicate the custody receipt. Existing intents lack such a field and the
current observer, public key, and exact signatures already suffice for engine
recovery. The earlier binding result and slot are the durable local receipt.
Recovery must remain possible without re-resolving private custody; a later
mismatched binding affects future writes, not completion of an already reserved
bootstrap. Adding optional cross-links between the operations is a later
versioned evidence improvement.

When detectable, recovery reports both facts: initialization completed from
the reserved signatures, while a currently configured mismatched binding means
the next mapped write will refuse. Drift never makes recovery sign again or
abandon an already reserved bootstrap.

For `grant_observer(key=None)`, a mapped provider refuses before touching either
key layout and tells the caller to complete explicit binding creation first,
then pass that binding's public key. It must never call legacy
`ensure_signing_key`. Supplying an explicit public key continues not to imply
possession of its private key or create a local binding.

A separately created binding may survive a later declaration or initialization
refusal. That is expected composition of two durable operations, not a partial
effect hidden inside the later error.

## Legacy compatibility and migration boundary

The following remain transitional behavior:

- `CustodyCredentialProvider()` and explicit `None` use current path/stem,
  flat-self, and exact nested-observer lookup;
- missing legacy material may yield unsigned output where currently legal;
- filesystem aliases, symlinks, unsafe components, and conflicting flat/nested
  self keys keep refusing;
- legacy `engine.handle` and `engine.ceremony` retain callback credentials
  through `CredentialProvider.for_write(Path)` and explicitly refuse mapped
  credentials because they cannot establish a captured binding context; and
- directly supplied legacy `WriteCredentials` retain callback semantics.

These paths do not claim stable D0 namespace binding. They receive no automatic
migration and no new key-history scan prerequisite. Documentation must say a
locator move is stable only for an explicitly mapped provider after onboarding.

Mapped mode is opt-in. Once selected for an operation, there is no fallback to
legacy directories or callbacks. This prevents a corrupt binding from being
laundered into an unsigned or differently keyed write.

`SigningDomain` is neutral vocabulary. Mapping FACT, ARRIVAL, and TICK to the
`loops-fact-v1`, `loops-arrival-v1`, and `loops-tick-v1` prefixes remains
exclusively in custody. The SDK can adapt the generic four-argument verifier to
the existing domain-specific three-argument declaration/initialization verifier
callbacks; engine never hardcodes custody prefixes.

## Failure and result evidence

Introduce a typed precommit `CredentialBindingRefused` carrying the exact
request, captured Head/use position when present, reason code, and safe binding
evidence when available. It must not expose private paths. Suggested reasons
are `missing-required`, `corrupt-binding`, `request-mismatch`,
`unauthorized-public-key`, `signature-invalid`, `receipt-key-undeclared`,
and `recovery-required`.

Provider corruption and authorization disagreement refuse before signing or
append. Provider `BaseException` identity is preserved. Ordinary absence that
legally produces unsigned output is an explicit decision rather than an error.
Postcommit failure taxonomy is unchanged because credential work finishes
before append.

Creation/import results separately report operation token, winning key ref and
public key, whether a key object or binding was created, and whether another
creator won. Outcome-unknown errors retain the intent path/token and candidate
ref so callers reconcile instead of retrying with a new key.

## Implementation order and acceptance

A bounded implementation should proceed in four implementation steps followed
by one completed-stage external review:

1. Add neutral request/evidence types and lazy mapped fields while preserving
   constructors and all legacy behavior.
2. Add the mapped filesystem provider and creation/import recovery tests,
   without routing SDK defaults to it.
3. Integrate conditional captured verification into ordinary, batch, source,
   and declaration preparation; expose an explicit SDK mapped provider.
4. Integrate initialization and observer grant with pre-created mapped bindings,
   retaining old initialization recovery and refusing hidden mapped creation.

Required tests include:

- exact case- and Unicode-distinct namespaces/observers without path semantics;
- FACT/ARRIVAL/TICK domain separation and same-key-ref v1 policy;
- captured H+1 authorization, unauthorized replacement refusal, and no
  within-batch introduction authorization;
- current-declaration any-key receipt validation distinct from author history;
- provider resolution only after H, and source re-resolution per later tier;
- preview/read/load causing zero persistence;
- missing unsigned versus corrupt refusal;
- complete-temp/no-clobber binding publication, concurrent winner, every crash
  phase, same-intent recovery, retained candidates, and explicit orphan maintenance;
- malformed/mismatched `.pub`, private/public mismatch, symlink and slot-payload
  mismatch refusal;
- explicit legacy flat/nested import preserving current ambiguity rules;
- deliberate existing-ref reuse across namespaces;
- locator move after mapped onboarding;
- initialization requires a pre-created binding, enforces the FACT/ARRIVAL
  same-public rule, and recovers old intents; and
- mapped `grant_observer(key=None)` refuses before effects and never performs
  hidden legacy key generation.

## Judgment issues for review

1. **Receipt observer configuration.** When receipt signing is requested, the
   design requires an explicit provider `receipt_observer`. It deliberately
   does not infer one from vertex name, boundary name/origin, fact author, or
   physical custodian. Omitting it retains unsigned pre-signed-era ticks and
   refuses once a signed era requires a receipt; a product surface must decide
   where users configure it.
2. **Legacy onboarding copies private material.** Copying into managed storage
   makes locator moves stable and leaves the original untouched, but duplicates
   a secret. An external-reference key ref avoids duplication but does not
   survive moving the old key directory. This design chooses explicit secure
   copy and requires the operation to report it.
3. **Initialization intent cross-link.** The first slice keeps its proven v1
   recovery format unchanged. A later schema may cross-link the custody intent
   for richer provenance, but recovery must remain compatible with old intents.
4. **Unsigned mapped absence.** Existing ordinary unsigned behavior is retained.
   If the product wants selecting mapped mode to require signatures for every
   author, that is a separate policy flag; it must not be smuggled into D0.
5. **Cost.** Verified key-history scanning is conditional on mapped signing and
   may be O(N). A backend-neutral authenticated key-history query can optimize
   it later without changing the request or authorization rule.
