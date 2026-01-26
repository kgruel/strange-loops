# CLAUDE.md — peers

Scoped identity primitives. Answers: **who is acting, what can they see/do/ask?**

## Build & Test

```bash
uv run --package peers pytest libs/peers/tests
```

## Atom

```
Peer
 ├─ name: str              # identity label
 └─ scope: Scope
     ├─ see: frozenset[str] # what you can observe
     ├─ do: frozenset[str]  # what you can modify
     └─ ask: frozenset[str] # what you can request
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Peer` | frozen dataclass | name + scope |
| `Scope` | frozen dataclass | see + do + ask (frozensets) |
| `grant(scope, see=, do=, ask=)` | function | expand permissions (union) |
| `restrict(scope, see=, do=, ask=)` | function | narrow permissions (intersection) |
| `delegate(peer, name, see=, do=, ask=)` | function | child peer with restricted scope |

## Invariants

- Frozen + slots on both Scope and Peer. All operations return new instances.
- `grant` = union. `restrict` = intersection. `delegate` = restrict + new Peer.
- Delegation is monotonic: can only narrow, never escalate.
- `None` on any dimension preserves the parent's value.

## Pipeline Role

```
Peer ─ observes ─→ Fact
                     │
Peer.name appears in headers, audit trails.
Peer.scope cascades: filters which Facts, Shapes, Lenses are accessible.
Delegation hierarchy encodes participation level (direct, delegated, automated).
```

## Source Layout

```
src/peers/__init__.py   # All types + functions (single module)
tests/test_peer.py      # 11 tests
```
