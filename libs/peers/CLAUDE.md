# CLAUDE.md — peers

Identity primitives. Answers: **who is acting, what can they see, what can they do?**

## Build & Test

```bash
uv run --package peers pytest libs/peers/tests
```

## Atom

```
Peer
 ├─ name: str                    # identity label
 ├─ horizon: frozenset[str]      # what you can observe
 └─ potential: frozenset[str]    # what you can do/emit
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Peer` | frozen dataclass | name + horizon + potential |
| `grant(peer, horizon=, potential=)` | function | expand permissions (union) |
| `restrict(peer, horizon=, potential=)` | function | narrow permissions (intersection) |
| `delegate(peer, name, horizon=, potential=)` | function | child peer with restricted permissions |

## Invariants

- Frozen + slots on Peer. All operations return new instances.
- `grant` = union. `restrict` = intersection. `delegate` = restrict + new name.
- Delegation is monotonic: can only narrow, never escalate.
- `None` on any dimension preserves the parent's value.

## Pipeline Role

```
Peer ─ observes ─→ Fact
                     │
Peer.name appears in headers, audit trails.
Peer.horizon cascades: filters which Facts, Shapes, Lenses are accessible.
Peer.potential cascades: filters what actions/emissions are permitted.
Delegation hierarchy encodes participation level (direct, delegated, automated).
```

## Source Layout

```
src/peers/__init__.py   # All types + functions (single module)
tests/test_peer.py      # 11 tests
```
