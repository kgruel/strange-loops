# peers

Identity primitives: Peer = name + horizon + potential

## Atom

```
Peer
 ├─ name: str                    # identity label
 ├─ horizon: frozenset[str]      # what you can observe
 └─ potential: frozenset[str]    # what you can do/emit
```

## Usage

```python
from peers import Peer, grant, restrict, delegate

# Create a peer with permissions
admin = Peer(
    name="admin",
    horizon=frozenset({"logs", "metrics", "secrets"}),
    potential=frozenset({"deploy", "rollback"}),
)

# Delegate with restricted permissions
operator = delegate(admin, "operator", horizon={"logs", "metrics"}, potential={"deploy"})
# operator can see logs/metrics, do deploy, but not secrets or rollback

# Grant additional permissions
expanded = grant(operator, horizon={"alerts"})
```

## API

| Export | Purpose |
|--------|---------|
| `Peer` | name + horizon + potential (atomic identity) |
| `grant` | expand permissions (union) |
| `restrict` | narrow permissions (intersection) |
| `delegate` | create child peer with restricted permissions |
