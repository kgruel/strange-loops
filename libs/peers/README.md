# peers

Scoped identity primitives: Peer = name + scope

## Atom

```
Peer
 ├─ name: str        # identity label
 └─ scope: Scope
     ├─ see: frozenset[str]   # what you can observe
     ├─ do: frozenset[str]    # what you can act on
     └─ ask: frozenset[str]   # what you can query
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

## API

| Export | Purpose |
|--------|---------|
| `Peer` | name + scope (atomic identity) |
| `Scope` | see + do + ask (boundaries) |
| `grant` | expand scope |
| `restrict` | narrow scope (intersection) |
| `delegate` | create child peer with restricted scope |
