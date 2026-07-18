# Session 4 independent design advice — Digest

*2026-07-17. Scope: strange-loops 0.8.0 session 4. Grounded in
`dossier-digest.md`, `dossier-tui-corpus.md`, `s1-arbitration.md`, and the
current Python implementation.*

## Recommendation and gate verdict

Digest should be an app-level operation that freezes a cursor-addressed source
window, constructs a deterministic and auditable input frame, asks an injected
synthesizer for prose, and appends one ordinary domain fact at the **current
head** of an explicitly selected target vertex. It should not be a reserved
fact kind, a declaration event, a mutable replacement for the source facts, or
a write at the source cursor position.

The mock's `kind=close` is a useful project profile, not a new substrate kind.
The emitted kind must be an ordinary kind already declared by the target
vertex; the initial UI may default it to `close` only where that declaration
exists. Other stores can choose another target-declared kind. This avoids both
hard-coding this project's vocabulary and touching the code-frozen `_decl.*`
vocabulary. The fact's normal domain payload carries the summary and required
fold fields. A versioned `_digest` payload envelope carries input provenance,
coverage, and synthesis metadata.

The destination is neither always the source nor a magical dedicated digest
vertex. It is an explicit target (`--to <vertex>`) resolved at execution time.
It may equal the source, be a parent such as `loops/roadmap`, or be a dedicated
digest vertex chosen by the user. Target selection and target authorization
are separate: the command selects a target; that target's current constitution
decides whether this observer may append this kind.

There is one genuine implementation gate. No mutating `loops digest` may ship
until the parallel authorization paths are dissolved and that resolution is
ratified. Before that, a deterministic, non-writing `digest --dry-run` can
honestly ship. Restricting writes to vertices the process supposedly "owns"
does not resolve authorization: filesystem/key custody is not a grant, and the
feature was explicitly chartered as the first in-repo Peer/Grant consumer.

## 1. Exact operation, payload, destination, and cursor grammar

### Source position and window

A digest run has two source positions in one source lineage:

- `after`: an exclusive, lineage-qualified facts-witness position;
- `through`: an inclusive, lineage-qualified facts-witness position.

The source window is therefore `(after, through]` in facts receipt order. It
inherits session 1's facts-only cursor design, receipt-group atomicity,
lineage-qualified handles, and aggregate restrictions. The end defaults to an
atomically captured `head`; once captured it is immutable for the run. A digest
may read an old source interval, but the output fact is always constructed with
the current event time and appended at the target's current head. This obeys
"you cannot write or sign into the past."

The mock command:

```text
loops digest project --since 'last tick'
```

should be retained as digest-specific sugar for:

```text
loops digest project --since tick:last --at head
```

Here `tick:last` is an address form, not the English definition of a time
filter. It resolves through the last tick's `fact_cursor`; the digest window
starts immediately after that position. The persisted manifest records the
resolved lineage and fact-position handles, never the phrase `last tick`.
`--at` retains the session-1 meaning "witness cursor." `--as-of` retains its
different meaning, "event-time projection," and is not accepted for a
coverage-bearing digest write. An event-time projection can be exposed only in
a labeled, non-writing analytical preview. `seq:` and `fact:` are refused for
aggregate sources under A9; aggregate digest is deferred.

Digest does not redefine the existing `close` or `seal` commands in the first
slice. `close` remains the session-resolution action and `seal` remains the
signed tick boundary; Digest consumes positions they make addressable. The
mock's eventual compound interaction can be an orchestration with an explicit
order: capture the previous tick position, seal the source window, digest
`(previous_tick.fact_cursor, new_tick.fact_cursor]`, then append at the target
head. The manual `--since tick:last --at head` form may inspect an unsealed live
edge, but its coverage stays pending until a source tick attests through the
manifest's `through` position. It never silently promotes an unsealed interval
to verified coverage.

### Deterministic frame

The deterministic input frame should contain:

1. the resolved source lineage and `(after, through]` handles;
2. the exact source fact rows selected from that interval;
3. the fold/reconstruction used as synthesis context;
4. a stable structural diff between the two endpoint reconstructions;
5. the selection/cutline decision and exact contributing fact ids; and
6. canonical commitments for every input fact and for the ordered manifest.

Anything rendered into the model prompt is input and must be represented in
the input manifest. If carried-forward pre-window state is supplied as context,
its contributing ids belong in a separate `context` manifest and are not
silently claimed as covered by the window. Likewise, facts below a salience
cutline must not influence a folded row sent to the model; otherwise the UI's
claim that they remain below the cutline is false. The safest first slice has
no implicit top-k: select the entire interval, or require an explicit,
deterministic selection whose ids are printed before synthesis.

### Emitted fact

The result is one ordinary `Fact`:

```text
kind      target-declared domain kind (the mock profile uses "close")
ts        commit-time now
observer  the actor adopting the final bytes
origin    source vertex/lineage display hint, not the authorization carrier
payload   target kind's fold fields + summary + versioned _digest envelope
```

Illustrative application envelope (field names need implementation
ratification, but no `_decl.*` addition is involved):

```json
{
  "message": "the synthesized prose",
  "_digest": {
    "version": 1,
    "run_id": "01...",
    "source": {"vertex": "project", "lineage": "..."},
    "window": {"after": "lineage:.../fact:...", "through": "lineage:.../fact:..."},
    "input": {"ids": ["..."], "count": 142, "commitment": "sha256:..."},
    "context": {"ids": [], "count": 0, "commitment": "sha256:..."},
    "coverage": {"ids": ["..."], "count": 37, "commitment": "sha256:..."},
    "synthesis": {"adapter": "...", "model": "...", "prompt_commitment": "sha256:..."}
  }
}
```

Target-specific required fields, including its fold key, are supplied normally
and validated before the LLM call. The `_digest` envelope is evidence attached
to an ordinary domain observation; it is not ontology. A run id is minted
before synthesis and makes retry detection possible. Re-running intentionally
mints a new run and may append different bytes. It does not overwrite or
deduplicate a prior run merely because the source window matches.

The single new fact should be appended by loading the target `VertexProgram`
at head and calling its authorized `receive`, returning the target's normal
`Receipt`. The existing slice/merge/receive/push/pull machinery proves that
cross-store carriage exists, but a temporary store and whole-store merge are
the wrong mechanism for one newly authored target fact. Source facts stay in
the source store; the target fact carries their qualified provenance.

## 2. Observer, signing, and the meaning of attestation

The default unattended author should be a stable, declared synthesizer
observer such as `digest/<profile>`, with its own key in the **target** vertex's
custody and its public key in that target's observer declaration. It should not
masquerade as the human, and an ephemeral session-agent label should not become
an identity unless it is deliberately declared and keyed like any other Peer.

The rule is: `Fact.observer` names whoever adopts the final bytes for emission.
An unattended model result uses the digest observer. If a human edits or
explicitly adopts the preview and chooses to emit as themself, the fact uses
the human observer and human key. The initial version should not invent a
second signature or countersignature. Approval, if later needed, is another
fact/ref relationship. Delegation remains absent from signatures as ratified.

Non-determinism changes no cryptographic claim. The existing fact signature is
a per-observer authorship/adoption claim over the exact content commitment
`(kind, ts, observer, origin, payload)`. It says neither "this model will
reproduce this prose" nor "the prose is true." The prompt commitment, model
label, exact input manifest, and optional provider response id support audit,
not deterministic replay.

The phrase "authorship-at-receipt" must be split carefully. A fact signature is
transport-stable and is not a store-local receipt claim; it attributes the
content to its observer at emission/adoption. After append, the target store's
tick chain separately attests receipt order and sealed windows. This is exactly
the chain-attests-receipt principle: content authorship and store custody are
two claims, and neither substitutes for the other. An unsealed live-edge digest
has authorship protection if signed but not yet sealed receipt attestation.

Signing uses the target's `fact_signer_for(target)`. The source vertex's key must
not sign into another custody context merely because it supplied inputs. No
signature is generated until the final edited payload is frozen, authorization
is rechecked, and a head append is attempted.

## 3. Authorization: canonical resolution required before a write

The engine types currently are (verbatim from `libs/engine/src/engine/peer.py`):

```python
@dataclass(frozen=True, slots=True)
class Grant:
    """Optional policy: what an observer can see/do.

    Separates permission policy from identity. Observer is just a name;
    Grant holds the constraints.

    Attributes:
        horizon: What you can see (None = unrestricted)
        potential: What you can do (None = unrestricted)
    """

    horizon: frozenset[str] | None = None
    potential: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class Peer:
    """Atomic identity: name + horizon + potential.

    A Peer is who is acting, what they can see (horizon),
    and what they can do (potential).

    None means unrestricted — the peer can see/do anything.
    An explicit frozenset constrains to those entries only.

    Chain ancestry is intentionally NOT reachable from a leaf Peer.
    Peer is a per-agent projection of current state, not a per-assertion
    relation. To reconstruct "who vouched for this Peer / who is its
    voucher's voucher," walk the Fact ledger (via Fact.observer for the
    immediate asserter and via payload conventions like chain_metadata
    for ancestry). This is by design — assertions live on Facts, not on
    identity objects. See loops decision
    `substrate-friction/peer-assertion-relation` (2026-05-13).
    """

    name: str
    horizon: frozenset[str] | None = None   # None = unrestricted
    potential: frozenset[str] | None = None  # None = unrestricted
```

`potential` is a set of kinds. There is no target vertex in either value. The
current architecture fact must be carried verbatim because it is the gate:

> Two parallel authorization paths exist and only one is enforced: (a) lang-AST GrantDecl/ObserverDecl -> identity.py ObserverCheck (enforced at emit — 'forbidden' when decl.grant.potential excludes the kind); (b) engine.Peer/Grant frozen dataclasses with Vertex.receive(grant=) gating — ZERO production consumers (no CLI site constructs one; every receive() call is bare). Horizon (read-side visibility) is enforced NOWHERE. This is a dissolution candidate that must resolve BEFORE Digest builds on either path — Digest is chartered as the first in-repo Peer/Grant consumer, and building it on the unenforced path while the enforced path speaks a different schema would fork authorization semantics. Echoes convergence/consumer-more-substrate-aligned-than-substrate (2026-05-13): the substrate's own primitive still doesn't participate in the substrate. Found by the 0.7.0 design-state audit 2026-07-16.

The minimal resolution is **target-local grants**, not a new `targets` field on
`Grant`:

1. Resolve the explicit target vertex and load its declaration at target head.
2. Resolve the observer in that target's `ObserverDecl` chain.
3. Project its persisted `GrantDecl.potential` into the engine `Peer`/`Grant`
   value.
4. Pass that grant through the target's production `receive` path.
5. Make ordinary emit use the same projection/evaluator, removing the separate
   app-only policy implementation as an independent authority.

The target dimension is supplied by the vertex whose constitution is being
evaluated. Thus `potential={"close"}` in vertex B means permission to emit
`close` **to B**, not globally. This gives the missing target dimension without
changing the serialized grant schema. `_decl.observer-defined` already carries
`grant: {potential: [...]}`; no new declaration kind, payload member, or Go
oracle change is required for this minimal path. `Grant.horizon` stays out of
scope and unenforced rather than being smuggled into Digest.

Implementation may keep an app preflight for good diagnostics and an engine
gate for defense in depth only if both call the same canonical evaluator over
the same projected grant. Two separately implemented tests are still two
authorization paths. Authorization is checked before the costly synthesis and
again against target head immediately before append; a changed declaration or
lineage aborts without writing.

Writing only where the process has local keys/files is a design dodge, not an
honest first Digest slice. Local custody proves ability, not permission; it also
evades the explicit first-consumer charter and fails the mock's authorized
upward write. A self-target-only prototype is acceptable only when labeled
non-writing/dry-run or experimental and excluded from the Digest write contract.

## 4. Coverage backlink and Dissolution safety

Coverage needs three different sets, because conflating them causes false
dissolution:

- **window ids**: every fact in `(after, through]`;
- **input/context ids**: every fact whose content influenced the model prompt;
- **covered ids**: the exact subset the final fact's observer asserts is
  represented by the summary.

The coverage set must be explicit fact ids, qualified by source lineage. Cursor
bounds plus count and hash are not enough: the cutline can make coverage a
proper subset of the window. Conversely, generic inbound `_refs` cannot mean
coverage because refs already represent broader attention/provenance. The
digest may expose all inputs as provenance refs for `why`, but Dissolution must
read only the explicit coverage manifest.

For each manifest, compute a canonical commitment over the ordered pairs
`(fact_id, existing_fact_content_commitment)`, in source witness order, using
the existing canonical/signing helper rather than reimplementing JSON
canonicalization. Count is a diagnostic; the commitment is the integrity
check; explicit ids define the set. A structural verifier can then prove:

1. the source lineage matches;
2. every id exists and lies in the claimed cursor interval (or in the separately
   labeled pre-window context set);
3. ids are unique and the count matches;
4. current source content commitments reproduce the manifest commitment;
5. covered ids are a subset of eligible input ids, never below-cutline ids; and
6. the source chain seals through the claimed endpoint, and the digest fact's
   observer signature and target receipt chain verify to the available era.

This makes the **coverage assertion and its exact subject set** verifiable. No
hash can prove that prose semantically preserves a fact's meaning. That last
step remains an accountable assertion by the digest fact's observer. The UI
must say `coverage claimed by … · manifest verified`, not `summary proven from
facts`. An interactive reviewer may reduce the covered set before emission;
automation may assert it under the declared digest observer's key.

Dissolution may mark only those exact ids covered after structural verification
and trust-policy acceptance. It must not infer coverage from age, window
membership, kind alone, or an unverified/missing source. At key level, coverage
is valid only as of the digest endpoint and only when all contributing facts for
that key/state are covered; later revisions immediately remain uncovered.
For the first safety-bearing implementation, a newly appended digest remains
`coverage pending` until its authorship signature verifies and a later target
tick seals its receipt; an unsigned or live-edge claim may still be displayed
but cannot drive dissolution. Failures degrade to uncovered. Nothing is
deleted, and rewind/why retain the original facts.

The full Dissolution lens need not ship with Digest. Until cross-vertex coverage
discovery and trust policy exist, 0.8.0 may persist and verify the backlink but
must leave the salience coverage term inactive. That is conservative and obeys
"covered, not merely old."

## 5. LLM home and deterministic/non-deterministic split

The provider call belongs in `apps/loops`, initially in the digest command or a
small app-local adapter module. Define an injected `Synthesizer` protocol whose
shape is approximately:

```python
class Synthesizer(Protocol):
    def synthesize(self, request: DigestRequest) -> SynthesisResult: ...
```

The CLI composes the configured default adapter lazily. No LLM SDK or provider
import belongs in `atoms`, `lang`, `engine`, `store`, `sign`, or `custody`.
This follows the existing signer/dispatcher injection precedent and keeps the
library DAG honest. A separate app is justified later only if Digest becomes an
independent service; it is unnecessary for the first local command.

Everything surrounding the single `synthesize` call is deterministic:

```text
resolve cursor handles
  -> freeze exact source snapshot
  -> reconstruct endpoints / select inputs
  -> build canonical frame and prompt commitment
  -> authorize target (preflight)
  -> synthesize(frame)                 # only nondeterministic step
  -> preview/edit and choose covered ids
  -> construct + locally verify manifest
  -> re-authorize target head
  -> sign final fact as chosen observer
  -> target.receive -> Receipt
```

Tests use a fake synthesizer. Golden tests pin the request bytes, input and
coverage commitments, fact construction, authorization failures, and receipt.
Provider tests need only pin adapter translation and error mapping. Timeout,
provider failure, malformed response, user cancel, failed manifest validation,
authorization drift, signing failure, or target append failure leaves both
stores unchanged. The source snapshot can be retained as a dry-run artifact;
it does not become a fact until the final append succeeds.

## 6. Explicit 0.8.0 deferrals

The following should not ship as part of the first Digest write:

- **New `_decl.*` kinds or grant payload fields.** The target-local projection
  uses the frozen vocabulary already mirrored by the Go oracle.
- **Cross-observer or cross-vertex delegation.** Signatures encode the final
  observer's authorship only; delegation relations remain facts and policy.
- **`Grant.horizon` enforcement.** It is a separate, currently unenforced read
  policy and the Horizon lens is a different concept.
- **Remote/cross-host single-fact writes and multi-target atomic broadcast.**
  First ship one explicitly resolved local target and one target Receipt.
- **Digest of aggregate vertices.** A9 requires per-member cursor vectors and
  refuses member-local `seq:`/`fact:` addresses; membership history is also not
  available.
- **Recursive digest-of-digests and Strata integration.** Tick lineage remains
  unmet; recursion would conceal that missing provenance.
- **Scheduled/background digests.** Scheduling adds daemon lifecycle, secret
  custody, retry/idempotency, and unattended coverage policy. Manual invocation
  establishes the write contract first.
- **Automatic salience decay or the full Dissolution lens.** Persist and verify
  backlinks first; no fact is treated as subsumed until cross-store discovery
  and trust acceptance are implemented.
- **Semantic-proof or reproducibility claims.** Inputs and bytes are auditable;
  LLM meaning and repeated prose are not deterministic.
- **Countersigning/approval workflow.** A human may emit adopted bytes as the
  human observer; multi-party approval is a later fact/ref design.
- **Implicit salience top-k and carried-forward context.** Defer until the
  attribution machinery can prove exactly which fact ids influenced every
  prompt row and keep below-cutline facts uncovered.
- **Backdated digest facts or signatures.** Historical source selection never
  changes the head-only target append rule.

## 7. Implementation slices and exit criteria

### Gate 0 — authorization dissolution and ratification (blocking)

Adopt target-local grant scoping; create one projection/evaluator from current
`ObserverDecl` to `Peer`/`Grant`; route ordinary production emit and the future
Digest path through it; keep target lineage and kind in diagnostics.

**Exit:** one persisted schema and one evaluator are authoritative; all
production receive sites pass the resolved policy or an explicitly documented
open-system value; existing emit behavior remains pinned; forbidden writes
cannot reach store append; no `_decl.*` change; Kyle/arbiter ratifies the
dissolution. Until this exits, no mutating Digest work proceeds.

### Slice 1 — cursor-addressed dry-run planner (safe before Gate 0)

Implement the pure source-side plan: `(after, through]` resolution, `tick:last`
relative address, atomic head capture, exact manifest, endpoint reconstruction,
and printed input/coverage candidates. No LLM, signing, or write.

**Exit:** mixed id eras use lookup/rowid rather than id sorting; receipt groups
cannot be split; lineage mismatch fails; A9 aggregate forms refuse honestly;
`--since 'last tick'` prints its resolved handles; repeated runs over the same
frozen source produce byte-identical plan JSON; both stores' hashes are
unchanged.

### Slice 2 — synthesizer seam and preview

Add the app-local protocol, fake synthesizer, deterministic request renderer,
configured provider adapter, response validation, and editable preview. Still
no append by default; `--dry-run` never incurs a provider call unless an
explicit preview mode requests it.

**Exit:** all non-prose bytes are golden-pinned; model/prompt/input metadata is
captured; cancel/timeout/provider/malformed-output paths write nothing; no LLM
dependency enters a library package.

### Slice 3 — coverage envelope and verifier

Construct input/context/coverage manifests with explicit ids and existing fact
content commitments. Add a verifier and clear `claimed` versus `verified`
rendering. Begin with full-window selection; keep implicit top-k disabled.

**Exit:** missing, duplicate, mutated, out-of-window, below-cutline, wrong-lineage,
and hash/count mismatch fixtures all fail closed; a valid fixture identifies
exactly the covered ids; no generic ref or age is interpreted as coverage;
semantic adequacy is never labeled cryptographically proven.

### Slice 4 — one authorized head-only target append (after Gate 0)

Require explicit local `--to`, target-declared kind and payload fields, declared
observer, and target key. Pre-authorize, synthesize/preview, re-authorize target
head, sign final bytes with target custody, then call target
`VertexProgram.receive` and print its Receipt.

**Exit:** source cursor remains a read selector only; the fact timestamp and
append are current-head; forbidden/undeclared observer, changed grant/lineage,
missing key, signing failure, or append failure produces no fact; successful
cross-vertex write returns a target fact id and verifies authorship; re-running
with a new run id appends rather than overwrites; retrying one completed run id
detects the existing receipt.

### Slice 5 — conservative coverage discovery (optional 0.8.0 tail)

Teach source reads to discover reachable target digest facts, validate their
manifests, and expose `covered_by` without changing visibility or salience.

**Exit:** only verified, reachable, trust-accepted claims annotate exact source
ids; unavailable targets and verification failures render uncovered; rewind and
why still address originals. Activating the third salience term and shipping
the Dissolution lens remain a separately reviewed slice.

## Blocker statement

This session can recommend a concrete dissolution, but the binding architecture
fact reserves its ratification to the project owner/arbiter. Therefore the
honest immediate deliverable is this design plus Slice 1 (and, if desired,
non-writing Slices 2–3). A write-capable Digest is blocked at Gate 0, not by the
LLM call or by absent cross-store mechanics. Shipping an owner-only bypass would
hide, rather than resolve, the exact authorization fork Digest was sequenced
last to confront.
