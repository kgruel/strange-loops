# IDENTITY: Observer and Gating

Identity answers *who* — who observed this fact, who can emit this kind. The
model evolved: **Peer as an atom dissolved** into two simpler mechanisms.

---

## Current Model

### Observer (on Fact)

Every Fact carries its observer as a string field:

```
Fact
 ├─ kind: str
 ├─ ts: float
 ├─ payload: dict
 └─ observer: str    ← who produced this observation
```

The observer is part of the fact's meaning. A deployment observed by `"kyle"`
(direct) carries different weight than one observed by `"kyle/backup-cron"`
(automated). The identity encodes the stance.

```python
from atoms import Fact

# Create with observer attribution
fact = Fact.of("deploy", "kyle", target="api", version="2.3")
# fact.observer == "kyle"
```

### Grant (at Vertex)

Gating policy attaches at the Vertex level via `Grant`:

```python
from engine import Grant

# Define what an observer can do
grant = Grant(
    observer="kyle/monitor",
    potential=frozenset({"focus", "scroll"}),  # can emit these kinds
    horizon=frozenset({"health", "metrics"}),  # can see these kinds
)
```

The Vertex checks grants when:
- **Receiving**: Is this observer allowed to emit this kind? (potential)
- **Reading**: Is this observer allowed to see this state? (horizon)

---

## Why Peer Dissolved

The original Peer atom carried three fields: `name`, `horizon`, `potential`.
But:

1. **Name is just a string** — no structure needed beyond the string itself
2. **Horizon/potential are policy** — they belong at the Vertex, not on data
3. **The Fact needs observer** — but not the full policy object

The dissolution:
- `Peer.name` → `Fact.observer` (string field)
- `Peer.horizon` + `Peer.potential` → `Grant` (Vertex-attached policy)

The helper `Peer` type may still exist in the engine library for convenience,
but it's not a loop atom. The atoms are: Fact, Spec, Tick.

---

## Observer Conventions

### Naming Hierarchy

Observer names encode participation level by convention:

```
kyle                              → direct participant
kyle/claude-session-123           → delegated session
kyle/claude-session-123/worker-1  → further delegated agent
kyle/deploy-agent                 → autonomous agent
kyle/backup-cron                  → automated process
```

The hierarchy is just naming. The vertex interprets these strings through
Grant policy — there's no built-in parent/child relationship.

### Stance Is Emergent

"Stance" (direct, guided, delegated, automated, observing) doesn't need an
enum. Which observer produced the fact tells you the participation level.
The identity **is** the stance.

---

## Grant Semantics

### Potential: What You Can Emit

```python
grant = Grant(
    observer="monitor",
    potential=frozenset({"ui.scroll", "ui.select"}),
)

# At vertex:
if kind not in grant.potential:
    # blocked — observer cannot emit this kind
```

### Horizon: What You Can See

```python
grant = Grant(
    observer="metrics-viewer",
    horizon=frozenset({"cpu", "memory", "disk"}),
)

# At render:
if kind not in grant.horizon:
    # filtered — observer doesn't see this state
```

### None Means Unrestricted

```python
# Full access
grant = Grant(observer="kyle", potential=None, horizon=None)

# Can emit anything, can see anything
```

### Empty Set Means Locked Out

```python
# Read-only: can see everything, can emit nothing
grant = Grant(observer="viewer", potential=frozenset(), horizon=None)
```

---

## Capability-as-Fact

Capabilities can be event-sourced. Grants and revocations are facts:

```
Fact(kind="grant.add",    observer="admin", payload={target: "alice", kind: "deploy"})
Fact(kind="grant.revoke", observer="admin", payload={target: "bob",   kind: "secrets"})
```

A vertex folds these facts through a Spec. The current grant state is derived.
The audit trail is free.

---

## Relationship to the Loop

```
observer ─ creates ─→ Fact(kind, ts, payload, observer)
                           │
                         Vertex ── checks Grant.potential ── allowed?
                           │                                    │
                           ▼                                    no → blocked
                         routes by kind
                           │
                         Spec.apply folds into state
                           │
                         Lens renders ── checks Grant.horizon ── filtered
                           │
                         observer sees it
                           │
                         observer acts → new Fact
                           │
            the loop closes ←─────────────────┘
```

---

## Beyond the Loop: Cross-Collaboration

When facts cross trust boundaries — between vertices, between agents, between
trust domains — the participatory observer-as-string isn't sufficient on its
own. The convenience-bundle Peer carries the additional metadata needed at
boundaries.

### Peer with iss

Peer is a consumer-side helper type. The dissolved-atom history left it as
`Peer(name, horizon, potential)`; the boundary extension is `Peer(name, iss)`,
where `iss` is the *issuer* — the authority that vouches for this peer's
identity.

```python
from engine import Peer

# Solo / local work: no iss needed
local = Peer(name="kyle")

# Identified peer with an authority: iss carries the trust-root reference
remote = Peer(name="adjunct-x", iss="https://vouch.bfc.lol")
```

The `iss` field is the **policy join point**, not metadata about the peer. It
is how a vertex decides whether to honor a peer's claims at all:

- **Same-iss** operations are intra-domain. The vertex's policy knows how to
  resolve this iss and trusts the peers it issues. Verification is local.
- **Cross-iss** operations are federation. The vertex's policy must assess "do
  I honor grants/emissions from this foreign iss?" — yes for own-iss,
  configurable for foreign-iss, no for unknown.
- **No iss** (`iss=None`) is the trust-by-convention case. Solo work, no
  external authority needed; the trust-root is whoever has write access to
  the store.

`iss` stays opaque-string at the data layer; the policy machinery (resolver,
trust-assessor, chain-walker) gives it operational meaning. Engine ships
nothing for resolving JWKS or validating signatures; consumers (vouch, pile,
comms) implement those via their `VertexPolicy`.

### Verification at boundaries, not at fact-shape

The substrate stance is **participatory, not authenticative**. Observer
carries who-asserts, not cryptographically-proven-who-asserts. Trust attaches
to the accumulated fact-stream, not to each fact's signature.

This is consistent at three sites:

1. STRANGE-LOOPS.md commits: "participatory (observer-as-stance), not
   authenticative (proof-of-origin)."
2. alcove's trust-topology essay: "the audit trail IS the trust system."
3. siftd's provenance model: "who pushed this data" (audit trail), not
   "cryptographic proof of source authenticity."

Verification becomes load-bearing only at boundaries:

- **Transport boundary** — facts moving from one vertex to another. The
  receiver verifies "did this assertion actually come from the claimed
  observer?"
- **Persistence boundary** — facts that need to be verifiable beyond the
  immediate context in which they were emitted (vouches that travel,
  attestations that persist past their issuer's session).
- **Federation boundary** — facts crossing `iss` values; different trust
  domains where direct trust-by-convention doesn't hold.

Inside a boundary, verification is unnecessary overhead. Across a boundary,
it is structural.

### VertexPolicy: the gate at the boundary

`VertexPolicy` is an extension hook for the vertex's accept-emission gate. The
existing `vertex.receive(fact, grant=grant)` check is generalized to an
interface a vertex can register a policy against. Default policy is permissive
(preserves current behavior; solo work unchanged). Stricter policies
implement:

- `verify_emission(fact)` — does the observer's claim verify?
- `verify_grant_link(child, parent)` — for chain-bearing facts, is `child` a
  valid extension of `parent`? (Consumer-supplied comparator; engine doesn't
  know what "valid" means for a given kind's payload.)
- `verify_grant_anchor(root)` — is the root of a chain anchored in this
  vertex's trust roots?
- `resolve_verification_context(peer)` — how does this policy verify a peer
  with given `(name, iss)`? Vouch resolves JWKS at iss; other consumers
  implement against their own auth path.

Substrate primitives stay thin. The hook is contract-level; implementations
are consumer-level.

### Chain-walking on `payload.parent_ref`

For facts that participate in delegation chains (vouches, attestations, any
kind whose semantics include "this fact extends an earlier one"), the
convention is `payload.parent_ref = <fact-id>`. The engine ships a generic
chain-walker that traverses parent_refs and delegates verification to the
vertex policy at each link.

```python
result = walk_grant_chain(leaf_fact, store, policy)
# result.valid: bool — every link verified
# result.chain: list of facts from leaf to root
# result.anchor: the root fact (where parent_ref is None)
```

This is fact-graph traversal, not a Grant-specific operation. Any
parent_ref-bearing fact can be chain-walked.

### What Peer-the-convenience-bundle carries

Facts still carry observer-as-string. `Peer` is consumer-side convenience that
wraps the observer string with verification context when the vertex policy
needs it.

```python
# Fact carries observer-as-string (the on-Fact identity reference)
fact = Fact.of("vouch", observer="kyle/loops-claude", payload={...})

# Vertex policy resolves observer to a Peer when verification matters
peer = policy.resolve_peer("kyle/loops-claude")
# → Peer(name="kyle/loops-claude", iss="https://vouch.bfc.lol")
verified = policy.verify_emission(fact)
```

The dissolution is preserved: Fact stays clean with observer-as-string. Peer
is a helper for the layer of code that crosses boundaries and needs to
verify, federate, or chain.

### Cross-collaboration shape

Different consumers exercise different combinations of these primitives:

- **vouch** uses Peer + chain-walking + verification (issuer identity, chain
  validity, anchor in `chain_anchors`).
- **sqlmerge** (when it adopts) uses Peer + slice-spec in payload (recipient
  identity, what slice of the store).
- **comms** (when it migrates) uses Peer + per-channel acceptance policy.
- **pile** uses Peer + owner-namespace check (already implicit in the
  `<owner>/<source>` naming convention).

Each consumer's vertex policy interprets the payload its kinds carry. The
substrate provides envelope-shape (`parent_ref`), traversal (`walk_grant_chain`),
and the policy hook (`VertexPolicy`). It does not commit to slice-spec,
capability-tuple, or any kind-specific schema — those live in consumer
payloads.

---

## Migration from Peer

If you have code using the old Peer pattern:

```python
# Old pattern
from peers import Peer, delegate
kyle = Peer("kyle")
monitor = delegate(kyle, "kyle/monitor", potential={"focus"})

# New pattern
from engine import Grant
# Observer is just a string
observer = "kyle/monitor"
# Policy is a Grant
grant = Grant(observer=observer, potential=frozenset({"focus"}))
# Facts carry the observer
fact = Fact.of("focus", observer, index=3)
```

The `Peer` helper type may still exist for convenience in building grants,
but the fundamental model is: observer string on Fact, Grant policy at Vertex.

---

*See LOOPS.md for the fundamental model. See VERTEX.md for how gating integrates with routing.*
