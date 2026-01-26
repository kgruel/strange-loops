# peers

Scoped identity primitives: `Peer = name + scope`

Part of a five-library ecosystem answering: *Who is acting? What can they see/do?*

## Install

```bash
uv add peers
```

## Usage

```python
from peers import Peer, Scope, grant, restrict, delegate

# Create a peer with scope
admin = Peer(
    name="admin",
    scope=Scope(
        see=frozenset({"logs", "metrics", "secrets"}),
        do=frozenset({"deploy", "rollback"}),
    ),
)

# Delegate with restricted scope
operator = delegate(admin, "operator", see={"logs", "metrics"}, do={"deploy"})
# operator can see logs/metrics, do deploy, but not secrets or rollback

# Grant additional permissions
expanded = grant(operator.scope, see={"alerts"})
```

## Primitives

| Primitive | Purpose |
|-----------|---------|
| `Peer` | name + scope (atomic identity) |
| `Scope` | see + do + ask (boundaries) |
| `grant` | expand scope |
| `restrict` | narrow scope (intersection) |
| `delegate` | create child peer with restricted scope |

## Key Insight

**Scope cascades through everything.** A Peer's scope defines what they can see/do/ask across all layers of the ecosystem.
