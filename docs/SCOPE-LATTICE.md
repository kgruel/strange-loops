# SCOPE-LATTICE: Capability Algebra at the Substrate

The scope lattice is the operational form that makes "trust attaches to
facts" hold under delegation. The substrate stance (participatory, not
authenticative — see [IDENTITY.md](./IDENTITY.md)) says trust is computed from
the accumulated fact-stream. When facts include grants and revocations that
extend authority from one peer to another, the math that keeps the
computation sound is the lattice.

This document is the standalone treatment of the math. Per-consumer
specialization (vouch's capability tuples, sqlmerge's slice specs) lives in
consumer payloads; this document describes only the substrate property.

---

## The lattice

A **capability** is a tuple. The shape of the tuple is consumer-specific —
for vouch, `(service, action, target)` (e.g., `("comms", "send",
"#agent-party")`); for other consumers, other shapes. The substrate makes no
commitment on tuple shape.

A **scope** is a finite set of capabilities — a subset of the universe of
all possible capability-tuples a consumer defines.

The set of all scopes, ordered by subset inclusion (⊆), forms a **lattice**:

- **Join** (∪): the union of two scopes. The smallest scope containing both.
- **Meet** (∩): the intersection. The largest scope contained in both.
- **Bottom** (⊥): the empty scope, ∅.
- **Top** (⊤): the full universe of capabilities — useful as a notional
  ceiling, rarely materialized in practice (no agent holds all possible
  capabilities at runtime).

This is the standard powerset lattice for whatever capability-universe the
consumer defines. The substrate does not need a richer order structure — ⊆
is sufficient for the properties below.

---

## Three properties the lattice gives the substrate

### 1. Unscoped is the bottom element

A scope of ∅ is an **identity-only attestation** — "this peer exists; the
voucher says so" — with no operational authority attached. Identity and
authorization are not separate primitives at the substrate; identity is the
limit case of scoped authorization where scope = ∅. The fusion is
unification along the scope axis, not conflation of distinct concepts.

Consequence: the substrate does not need a separate "identity assertion"
fact-kind. An attestation-without-capability is an attestation with empty
scope.

### 2. Delegation narrows

A peer holding scope **P** may issue an attestation to another peer with any
scope **C** such that **C ⊆ P** in the lattice order. Operationally:

```
issue_attestation(holder=H, scope=C, parent=A_parent)
    requires C ⊆ scope_of(A_parent)
```

Authority can never amplify through a chain. This is a structural invariant,
not a runtime check the issuer must remember to enforce — the issuance
operation is implemented as "compute **C ∩ P**" or fails if **C ⊄ P**. The
narrowing is mechanical.

### 3. Soundness by construction

For any chain of attestations a₀ → a₁ → … → aₙ (where each aᵢ₊₁ has
`parent_ref = aᵢ`), transitivity of ⊆ gives:

```
scope(aₙ) ⊆ scope(aₙ₋₁) ⊆ … ⊆ scope(a₀)
```

A consumer reading any attestation in the chain knows the upper bound of its
bearer's authority **without traversing the whole chain**. Reading aₙ gives
`scope(aₙ)` directly — the chain-walk is only required to validate the
chain's integrity (each link is a valid issuance from its parent), not to
compute the effective authority.

This is the property that makes the substrate's trust claim hold under
arbitrary delegation depth: trust attaches to the assertion, the assertion
carries its own scope, and the scope is bounded by every ancestor scope by
construction.

---

## What the lattice does *not* commit to

The substrate's lattice treatment is deliberately thin. It does not commit
to:

- **Capability-tuple schema.** The shape of a capability is per-consumer.
  Vouch uses `(service, action, target)`; sqlmerge might use
  `(kinds, topics, time-range)`; comms might use `(channel, action)`. The
  lattice operations work on any tuple shape with set semantics.
- **Capability-tuple semantics.** What `("comms", "send", "#agent-party")`
  *means* operationally is comms's concern, not the substrate's. The
  substrate guarantees the math; the consumer interprets the tuples.
- **Verification.** The lattice says nothing about cryptography. Whether an
  attestation is authentic (the claimed issuer actually issued it) is a
  separate question, handled at boundaries by `VertexPolicy` (see
  [IDENTITY.md](./IDENTITY.md)).
- **Capability namespace governance.** Who decides what capability-tuples
  exist, how collisions are avoided, how vocabulary evolves — these are
  governance questions answered by catalog discipline (see vouch ADR-0002
  for the homelab's approach), not substrate properties.
- **Revocation semantics.** "Revoking" an attestation is appending a new
  fact that the consumer's policy interprets as rescinding the prior. The
  substrate does not commit to a specific revocation mechanism — the lattice
  describes what's valid; revocation describes what's currently honored.
  These are separable concerns.

The lattice is the **algebra of authorized scope under delegation**. Anything
operational that depends on more than that is consumer territory.

---

## Connection to fact-trust

The lattice composes with the substrate stance:

- Trust attaches to facts (substrate stance).
- An attestation is a fact (`kind` declared by the consumer; envelope from
  the substrate; payload from the consumer).
- The attestation's scope is in the payload (consumer-defined tuple shape).
- The attestation's parent_ref is in the envelope (substrate-provided
  chain machinery).
- The lattice math operates on scopes at attestation time (issuance) and at
  read time (chain validation, effective-scope computation).

What the consumer adds:

- Capability-tuple schema (the lattice elements).
- Issuance verb (`issue_vouch`, `grant`, whatever the consumer calls it).
- Validation policy (`VertexPolicy.verify_grant_link` checks `C ⊆ P` per the
  consumer's tuple semantics).

What the substrate provides:

- Fact envelope with `parent_ref`.
- Chain-walker (`walk_grant_chain`) that traverses parent_refs and delegates
  link-validity to the policy.
- Read-helper (`grants_for`) that finds attestations targeting a given peer.

The math doesn't run anywhere in particular — it lives in the consumer's
policy, applied by the substrate's chain-walker. The substrate ships the
machinery; the consumer ships the math instantiated for its tuple schema.

---

## On using this in a consumer

A consumer adopting the lattice declares:

1. **Capability-tuple schema.** A formal description of the tuple shape.
   (E.g., `(service: str, action: str, target: str)`.)
2. **Universe of capabilities.** The set of valid tuples — typically open,
   constrained by catalog discipline rather than enumeration.
3. **`VertexPolicy.verify_grant_link`** implementation. Given a child and
   parent attestation, compute `child.scope ⊆ parent.scope` per the
   consumer's tuple semantics. Reject the child if violated.
4. **Scope intersection** at issuance. When issuing an attestation, the
   issuer's effective scope (the meet of all valid attestations naming them
   as holder) bounds what they can issue.
5. **Anchor declaration.** The vertex declares its trust roots — peers whose
   self-attestations are honored as chain origins (`parent_ref = None`).

The substrate runs the chain-walking; the consumer runs the math.

---

## Why the math matters

Without the lattice, "delegation narrows" is a convention the issuer might
forget to enforce. With it, narrowing is a structural property the issuance
operation cannot violate without a type error.

Without the lattice, soundness across chains requires walking and validating
every link. With it, soundness is given by transitivity — chain-walk is
needed for integrity but not for authority-bounding.

Without the lattice, identity-only attestations need a separate kind from
scoped attestations. With it, identity is the bottom-element case of the
same kind — fewer concepts to maintain, one shape to reason about.

The lattice is small and load-bearing. It is the operational form that makes
"trust attaches to facts" hold under the kinds of delegation real consumers
(vouch, future federation) need.

---

## See also

- [IDENTITY.md](./IDENTITY.md) — observer-as-stance, Peer as convenience
  bundle, VertexPolicy for boundary verification.
- [Trust topology essay](http://192.168.1.44:8080/trust-topology.html) —
  alcove's substrate framing (the *why*).
- `~/Code/vouch/docs/decisions/0001-vouch-trust-substrate.md` — vouch's
  adoption of the lattice with its specific capability-tuple schema
  (`(service, action, target)`) and the homelab's catalog discipline.
- The loops-side essay at `essays/2026-05-13-on-trust-as-substrate.md` —
  loops-claude's voice on what the lattice dissolves and what it leaves
  open.
