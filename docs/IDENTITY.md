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
