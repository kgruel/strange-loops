# Rung 10 — Identity & Federation

> **What you'll learn:** How observer identity is resolved; how Grant and Peer gate what an observer can see and do; the observer-state gating rule; the scope lattice and why delegation can only narrow; and where `sign` (JWT/JWKS) fits relative to the loops protocol.
> **Prerequisites:** [Rung 02 — Engine: Vertices & Loops](02-engine-vertices-and-loops.md), [Rung 09 — Store Maintenance & Transport](09-store-maintenance-and-transport.md)
> **Time:** ~25 min

Identity in loops answers a single question: **who produced this observation?** Every Fact carries that answer as a string field — `observer`. The rest of the identity machinery (Grant, Peer, scope lattice) determines what an observer is *allowed* to see and do at the Vertex.

---

## Observer: the fourth property of a Fact

The three shapes are Fact, Spec, and Tick. Every Fact carries four properties:

```
Fact
 ├─ kind:     str         — what happened
 ├─ ts:       float       — when (epoch seconds)
 ├─ payload:  dict        — what the observation contains
 └─ observer: str         — who produced this observation
```

Observer is a plain string. The loops substrate makes no attempt to verify it — verifying that a claimed observer actually produced the fact is a consumer-level concern, handled outside the core fact-ledger by tools like `vouch`. The substrate is participatory, not authenticative.

```python
from atoms import Fact

fact = Fact.of("decision", "kyle", topic="auth", message="JWT over sessions")
# fact.observer == "kyle"
```

### Observer naming conventions

Observer names encode the stance of the observation:

```
kyle                       direct participant
kyle/loops-claude          agent acting on kyle's behalf (namespaced)
monitor                    automated monitor with no principal attribution
```

The `/` separator is a convention, not a type boundary. Both bare names (`kyle`) and namespaced names (`kyle/loops-claude`) are valid strings. The namespace encodes delegation lineage — who the agent is acting for — but the substrate does not enforce or interpret the hierarchy. It is information available to consumers.

### Observer name matching

When the vertex checks whether an emitting observer is allowed to emit a given kind, it uses `observer_matches(a, b)` from `engine.observer`:

- `"kyle"` matches `"kyle"` — exact
- `"kyle/loops-claude"` matches `"loops-claude"` — bare matches the leaf (agent part) of a namespaced name
- `"kyle/loops-claude"` does NOT match `"kyle/meta-claude"` — both namespaced, different leaf: exact match required
- `"kyle/loops-claude"` does NOT match `"kyle"` — bare `"kyle"` does not match the leaf `"loops-claude"`

The leaf of a namespaced name is the segment after the final `/`. `observer_leaf("kyle/loops-claude")` returns `"loops-claude"`.

---

## Resolving observer identity in the CLI

`loops whoami` shows which observer the CLI will use for the current context:

```bash
loops whoami
# kyle
```

`resolve_observer()` walks a priority chain:

1. `--observer` flag (explicit)
2. `LOOPS_OBSERVER` environment variable
3. Project `.vertex` observers block (walk up from cwd), if exactly one observer is declared
4. Global `~/.config/loops/.vertex` observers block, if exactly one observer is declared

If a vertex declares multiple observers, `resolve_observer()` returns empty string — the CLI cannot auto-pick. Use `--observer` or `LOOPS_OBSERVER` to disambiguate.

### Emit-time validation

Before writing a fact, the CLI calls `validate_emit(vertex_path, observer, kind)`. This function:

1. Collects all observer declarations from the vertex file, the project `.vertex` chain, the global `.vertex`, and any `combine {}` source vertices.
2. Finds the declaration that matches the emitting observer (via `observer_matches`).
3. If the declaration has a `grant.potential` set, rejects kinds not in that set.

If no observers are declared anywhere, the system is open — no validation occurs.

---

## Grant: gating policy at the Vertex

`Grant` separates policy from identity. Observer is a string; Grant holds the constraints:

```python
from engine import Grant

# Unrestricted — can see and do anything
open_grant = Grant()                                # horizon=None, potential=None

# Constrained — can only emit health and deploy facts
gated = Grant(
    potential=frozenset({"health", "deploy"}),      # what kinds this observer can emit
    horizon=frozenset({"health", "metrics"}),       # what kinds this observer can see
)
```

`Grant(horizon=None, potential=None)` means **unrestricted** on both dimensions. `frozenset()` (explicitly empty) means **locked out** from that dimension.

The two dimensions:
- **`potential`** — the set of kinds this observer may emit. Checked on `vertex.receive()`.
- **`horizon`** — the set of kinds this observer may read. Not enforced by the vertex directly; consumed by rendering layers.

### Peer: identity bundled with policy

`Peer` is a convenience bundle: a name plus a Grant.

```python
from engine import Peer

# Unrestricted peer
admin = Peer("kyle")

# Constrained peer
monitor = Peer("monitor", potential=frozenset({"health", "deploy"}))

# Extract just the Grant from a Peer
from engine.peer import grant_of
grant = grant_of(monitor)
# Grant(horizon=None, potential=frozenset({"health", "deploy"}))
```

`Peer` is NOT a loop atom. The three atoms are Fact, Spec, and Tick. `Peer` is an engine-layer convenience type for policy management — it does not travel as data, it does not appear in payloads.

### The capability algebra

Four operations modify Peer permissions:

```python
from engine.peer import grant, restrict, delegate

# grant: union — expand permissions (no-op on unrestricted dimensions)
expanded = grant(monitor, potential={"metrics"})
# monitor.potential was {"health", "deploy"}, now {"health", "deploy", "metrics"}

# restrict: intersection — narrow permissions
narrowed = restrict(admin, potential={"health"})
# admin was unrestricted (None); restricting gives {"health"}

# delegate: restrict + rename — always narrows, never expands
viewer = delegate(admin, "viewer", potential={"health"})
# Peer("viewer", potential=frozenset({"health"}))
```

The key invariant: **delegation can only narrow.** `delegate()` is implemented as `restrict()` followed by rename. You cannot delegate more than you hold.

Grant-level versions of the same operations exist: `expand_grant()`, `restrict_grant()`.

---

## Observer-state gating: the built-in gate

The Vertex enforces one additional rule automatically, without any Grant declaration:

Kinds matching the pattern `focus.{name}`, `scroll.{name}`, or `selection.{name}` are **observer-state kinds**. A fact with kind `focus.kyle` can only be received by the vertex if `fact.observer` matches `kyle`. Any other observer is rejected at the gate.

```python
# Accepted: observer == "kyle"
focus_fact = Fact.of("focus.kyle", "kyle", item="auth-decision")

# Rejected: observer != "kyle"
bad_fact = Fact.of("focus.kyle", "monitor", item="auth-decision")
# → Vertex rejects this — observer "monitor" cannot emit kind "focus.kyle"
```

This ensures that observer-scoped UI state (focus, scroll, selection) cannot be impersonated by another observer, even if their Grant would otherwise allow the kind.

---

## The scope lattice

The scope lattice is the mathematical foundation that makes delegation provably safe. This section describes the property; the full treatment is in [../SCOPE-LATTICE.md](../SCOPE-LATTICE.md).

A **capability** is a tuple — the exact shape is consumer-specific. For `vouch`, it is `(service, action, target)`. For another consumer, it might be `(kind, observer)`. The substrate does not commit to a tuple shape.

A **scope** is a finite set of capabilities. The set of all scopes, ordered by subset inclusion (⊆), forms a lattice:

- **Join** (∪): union — smallest scope containing both
- **Meet** (∩): intersection — largest scope contained in both
- **Bottom** (⊥): empty set — identity-only (no operational authority)
- **Top** (⊤): all capabilities — theoretical ceiling

Three properties the lattice gives:

1. **Identity is the bottom element.** A scope of ∅ is attestation with no authority attached. Identity and authorization are not separate primitives — identity is the case where scope is empty.

2. **Delegation narrows.** A peer holding scope **P** can only issue an attestation with scope **C** where **C ⊆ P**. The issuance operation computes `C ∩ P` — narrowing is mechanical, not a convention the issuer might forget.

3. **Soundness by construction.** For any chain a₀ → a₁ → … → aₙ, transitivity of ⊆ gives `scope(aₙ) ⊆ scope(a₀)`. A consumer reading any attestation in the chain knows the authority ceiling without traversing the whole chain. Chain-walking is needed for *integrity validation*, not for *authority bounding*.

---

## Where `sign` fits — and where it does not

`libs/sign` is a utility library for JWT minting and verification, RSA key management, and JWKS/OIDC discovery documents. It depends on `cryptography`, `pyjwt`, and `python-ulid`. It has no dependency on `atoms`, `engine`, or any other loops primitive.

**`sign` is NOT part of the loops protocol.**

The loops protocol is the fact-ledger: Fact, Spec, Tick, and the Vertex runtime. `sign` is a separate utility that consumers (like `vouch`) use when they need cryptographic attestation. It is in this monorepo because it is shared code, not because it is substrate.

```python
# sign public API — use directly when you need JWT/JWKS
from sign import KeyStore, load_or_generate, mint, verify, build_document

# Generate or load RSA keypair from a directory
keystore = load_or_generate(Path("~/.config/loops/keys"))

# Mint a JWT — caller builds the claims dict
token, jti = mint(
    keystore=keystore,
    issuer="https://homelab.local",
    claims={"sub": "kyle", "aud": "comms"},
    ttl_seconds=3600,
)

# Verify — looks up signing key by kid from token header
claims = verify(token, public_keys=keystore.public_keys(), issuer="https://homelab.local", audience="comms")

# Publish JWKS
jwks_doc = build_document(keystore)
```

`sign` ships breaking changes via tagged loops releases. Consumers (`vouch`, `pile`, `comms`) pin and upgrade independently — the same posture as `libs/store`. It is useful shared code, not substrate.

---

## Vertex declaration: observers block

To declare which observers are authorized for a vertex — and optionally what each may do — use the `observers {}` block in the `.vertex` file:

```kdl
// project.vertex
name "project"
store "./data/project.db"

observers {
  kyle { }   // no grant — unrestricted (can emit any kind, see all state)

  monitor {
    grant {
      potential "health" "deploy" "metrics"   // can only emit these kinds
    }
  }

  "kyle/loops-claude" {
    identity "https://homelab.local/agents/loops-claude"  // optional OIDC issuer
    grant {
      potential "decision" "thread" "observation" "cite"
    }
  }
}
```

Observers declared here are checked at emit time by `validate_emit()`. When the `grant` block is absent, the observer is unrestricted — any kind is allowed. When `grant.potential` is declared, only listed kinds pass.

---

## Summary: the identity stack

```
CLI emit path:
  resolve_observer()     → who am I?
  validate_emit()        → am I allowed to emit this kind?
  Fact.of(kind, observer, ...)  → observer goes on the Fact

Runtime receive path:
  vertex.receive(fact, grant=grant)
    Gate 1: grant.potential check        → is this kind in potential?
    Gate 2: observer-state check         → focus/scroll/selection.{name} ≡ observer
    → accepted: route to fold engine

Policy layer (Grant/Peer):
  Grant(horizon, potential)     → what an observer can see/do
  Peer(name, horizon, potential) → identity + policy bundle (engine layer only)
  delegate()                    → always narrows, never expands

Cryptographic layer (NOT loops protocol):
  sign.mint / sign.verify       → JWT attestation for federation consumers
  sign.build_document           → JWKS for remote verification
```

The loops substrate provides the fact-ledger and the gating algebra. Cryptographic verification of claimed identity is a consumer concern — the substrate is designed to be wrappable, not to dictate the verification mechanism.

---

**See also:** [deep dive: IDENTITY](../IDENTITY.md) · [deep dive: SCOPE-LATTICE](../SCOPE-LATTICE.md) · `libs/sign/CLAUDE.md` · [guide index](README.md)
