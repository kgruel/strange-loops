# CLAUDE.md — peers

Identity and policy primitives. Answers: **who is acting, what can they see, what can they do?**

## Build & Test

```bash
uv run --package peers pytest libs/peers/tests
```

## Atoms

```
Grant
 ├─ horizon: frozenset[str] | None     # what you can observe (None = unrestricted)
 └─ potential: frozenset[str] | None   # what you can do/emit (None = unrestricted)

Peer
 ├─ name: str                          # identity label (observer name)
 ├─ horizon: frozenset[str] | None     # what you can observe (None = unrestricted)
 └─ potential: frozenset[str] | None   # what you can do/emit (None = unrestricted)
```

**Observer** is just a name (string) — intrinsic to Fact.
**Grant** is optional policy (horizon + potential) — separate from identity.
**Peer** is a convenience bundle: name + horizon + potential.

`None` = unrestricted (no constraints). `frozenset()` = explicitly empty (locked out).
Constraints emerge through delegation, not through upfront enumeration.

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Grant` | frozen dataclass | horizon + potential (optional policy) |
| `Peer` | frozen dataclass | name + horizon + potential (convenience bundle) |
| `grant(peer, horizon=, potential=)` | function | expand Peer permissions (union); no-op on unrestricted |
| `restrict(peer, horizon=, potential=)` | function | narrow Peer permissions (intersection); unrestricted → specific |
| `delegate(peer, name, horizon=, potential=)` | function | child Peer with restricted permissions |
| `grant_of(peer)` | function | extract Grant from Peer |
| `expand_grant(grant, horizon=, potential=)` | function | expand Grant permissions (union) |
| `restrict_grant(grant, horizon=, potential=)` | function | narrow Grant permissions (intersection) |

## Invariants

- Frozen + slots on Grant and Peer. All operations return new instances.
- `grant` / `expand_grant` = union. No-op when dimension is `None` (can't add to "everything").
- `restrict` / `restrict_grant` = intersection. `None` intersected with a set gives that set.
- `delegate` = restrict + new name.
- Delegation is monotonic: can only narrow, never escalate.
- `None` on any grant/restrict/delegate arg preserves the parent's value.
- `grant_of(peer)` extracts just the policy (Grant) from a Peer.

## Gating pattern

The composition layer interprets horizon and potential:

```python
# Potential gating (bridge)
if peer.potential is not None and kind not in peer.potential:
    # blocked

# Horizon gating (render)
if peer.horizon is None:
    visible = all_items
else:
    visible = [x for x in all_items if x in peer.horizon]
```

Note: debug/verbose rendering is a **lens** concern (presentation depth),
not a horizon concern (data access). Do not put rendering modes in horizon.

## Pipeline Role

```
Observer (name) ─ produces ─→ Fact (with observer field)
                                 │
Grant (policy) ─ gates ─→ Vertex.receive()
                                 │
Peer.name becomes Fact.observer when observing.
Grant.horizon cascades: filters which Facts, Shapes, Lenses are accessible.
Grant.potential cascades: filters what actions/emissions are permitted.
Delegation hierarchy encodes participation level (direct, delegated, automated).
```

## Source Layout

```
src/peers/__init__.py   # All types + functions (single module)
tests/test_peer.py      # 11 tests
```
