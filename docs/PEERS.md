# PEERS: Identity and Observation

A Peer is the answer to *who* — who observed this fact, who can see this
state, who can emit this action. Participation in the loop requires
identity.

## The Atom

```
Peer
 ├─ name: str                          # identity label
 ├─ horizon: frozenset[str] | None     # what you can observe
 └─ potential: frozenset[str] | None   # what you can emit/do
```

Three fields. The name is who you are. Horizon and potential are what
you can see and what you can do. That's the complete atom.

## None Means Unrestricted

`None` = no constraints. The peer can see anything, do anything.

```python
kyle = Peer("kyle")
# kyle.horizon is None   → sees everything
# kyle.potential is None → can do anything
```

This is the root state. You start unrestricted. Constraints emerge
through delegation, not through upfront enumeration.

An explicit `frozenset()` is different: it means *locked out* — can see
nothing, can do nothing. The distinction matters:

| Value | Meaning |
|-------|---------|
| `None` | unrestricted — no constraints |
| `frozenset({"a", "b"})` | limited to a and b |
| `frozenset()` | locked out — nothing permitted |

## Horizon: What You Can See

Horizon controls what data a peer can observe. The strings are semantic
— their interpretation lives in the composition layer, not in the atom.

Horizon can express:
- **Temporal**: "7 days back"
- **Depth**: "N hops from this vertex"
- **Scope**: "team:backend" or "project:homelab"
- **Full**: `None` — no constraints

The composition layer interprets horizon. The peers library just stores
the constraint.

```python
# Horizon gating (render)
if peer.horizon is None:
    visible = all_items
else:
    visible = [x for x in all_items if x in peer.horizon]
```

## Potential: What You Can Do

Potential controls what actions a peer can emit. When a peer tries to
emit a fact, the composition layer checks potential.

```python
# Potential gating (bridge)
if peer.potential is not None and kind not in peer.potential:
    # blocked — peer cannot emit this kind
```

Potential can express:
- **Emit**: which fact kinds you can produce
- **Delegate**: whether you can create child peers
- **Execute**: whether you can trigger side effects
- **Full**: `None` — no constraints

## Delegation: Constraints Emerge

You don't enumerate all permissions upfront. You start unrestricted and
delegate narrower views to children.

```python
from peers import Peer, delegate

kyle = Peer("kyle")  # unrestricted root

# Create a child with narrower potential
monitor = delegate(kyle, "kyle/monitor", potential={"focus"})
# monitor can navigate (focus) but can't acknowledge

# Create another child with narrower horizon
metrics_viewer = delegate(kyle, "kyle/metrics", horizon={"cpu", "memory"})
# metrics_viewer can only see cpu and memory data
```

The delegation hierarchy encodes participation level:

```
kyle                              → unrestricted root (direct)
kyle/claude-session-123           → delegated session
kyle/claude-session-123/worker-1  → further delegated agent
kyle/deploy-agent                 → autonomous, narrower potential
kyle/backup-cron                  → automated, narrowest potential
```

Delegation is **monotonic**: you can only narrow, never escalate. A
child cannot have broader horizon or potential than its parent.

## The Observer as Participant

The peer who observed a fact is part of the fact's meaning. A
deployment observed by `kyle` (direct) carries different weight than
one observed by `kyle/backup-cron` (automated). The identity encodes
the stance.

This is why "stance" (direct, guided, delegated, automated, observing)
doesn't need an enum. Which peer observed the fact tells you the
participation level. The identity **is** the stance.

## Operations

Three pure functions. All return new Peer instances.

### restrict(peer, horizon=, potential=)

Narrow permissions via intersection. Restricting an unrestricted
dimension gives the specific set.

```python
from peers import Peer, restrict

kyle = Peer("kyle")  # unrestricted
limited = restrict(kyle, potential={"deploy", "rollback"})
# limited.potential == frozenset({"deploy", "rollback"})

more_limited = restrict(limited, potential={"deploy"})
# more_limited.potential == frozenset({"deploy"})
```

### grant(peer, horizon=, potential=)

Expand permissions via union. No-op when dimension is `None` — you
can't add to "everything".

```python
from peers import Peer, grant

# Only useful when a peer already has explicit constraints
viewer = Peer("viewer", potential=frozenset({"read"}))
editor = grant(viewer, potential={"write"})
# editor.potential == frozenset({"read", "write"})

# No-op on unrestricted
kyle = Peer("kyle")  # potential is None
still_kyle = grant(kyle, potential={"deploy"})
# still_kyle.potential is still None — unchanged
```

### delegate(peer, name, horizon=, potential=)

Create a child peer with restricted permissions. Delegation = restrict
+ new name.

```python
from peers import Peer, delegate

kyle = Peer("kyle")
monitor = delegate(kyle, "kyle/monitor", potential={"focus"})
# monitor.name == "kyle/monitor"
# monitor.potential == frozenset({"focus"})
# monitor.horizon is still None (inherited unrestricted)
```

## Capability-as-Fact

Capabilities can be event-sourced. Grants and revocations are facts,
folded through a shape into current potential.

```
Fact(kind="peer.grant",   payload={peer: "alice", capability: "deploy"})
Fact(kind="peer.revoke",  payload={peer: "bob",   capability: "secrets"})
```

A vertex folds these facts through an access shape. The current
potential is derived state. The audit trail is free. See
`experiments/capability.py` for this pattern.

## Relationship to the Loop

```
Peer ─ observes ─→ Fact
                     │
                   Vertex routes by kind
                     │
                   Shape folds into state
                     │
                   Lens renders as Cells
                     │
                   You see it. Your choice becomes a new Fact.
                     │
Peer ←─ the loop closes ─────────────────┘
```

Peer.name appears in audit trails and fact provenance. Peer.horizon
cascades: filters which facts, shapes, lenses are accessible.
Peer.potential cascades: filters what emissions are permitted. The
composition layer interprets these constraints; the atom just carries
them.

## A Note on the Name "Peer"

The word "peer" implies equality — *peers* among equals. But the
delegation hierarchy is explicitly hierarchical: parents constrain
children, children cannot escalate.

The tension is real. Alternative framings:
- **Observer**: emphasizes the act (observation), not the relationship
- **Participant**: emphasizes involvement in the loop
- **Actor**: emphasizes agency, but overloaded in CS

"Peer" was chosen because:
1. It fits the metaphor family (social) for the *who* question
2. At any given vertex, connected peers **are** equals in the protocol
   sense — the hierarchy exists in naming, not in protocol treatment
3. The delegation hierarchy is a naming convention (`kyle/monitor`),
   not a protocol asymmetry

If this tension causes confusion, the vocabulary can evolve. For now,
"peer" means "participant in the loop with an identity."

---

*See ARCHITECTURE.md for how peers compose with the other atoms.*
