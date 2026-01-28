# CLAUDE.md — peers

Identity primitives. Answers: **who is acting, what can they see, what can they do?**

## Build & Test

```bash
uv run --package peers pytest libs/peers/tests
```

## Atom

```
Peer
 ├─ name: str                          # identity label
 ├─ horizon: frozenset[str] | None     # what you can observe (None = unrestricted)
 └─ potential: frozenset[str] | None   # what you can do/emit (None = unrestricted)
```

`None` = unrestricted (no constraints). `frozenset()` = explicitly empty (locked out).
Constraints emerge through delegation, not through upfront enumeration.

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Peer` | frozen dataclass | name + horizon + potential |
| `grant(peer, horizon=, potential=)` | function | expand permissions (union); no-op on unrestricted |
| `restrict(peer, horizon=, potential=)` | function | narrow permissions (intersection); unrestricted → specific |
| `delegate(peer, name, horizon=, potential=)` | function | child peer with restricted permissions |

## Invariants

- Frozen + slots on Peer. All operations return new instances.
- `grant` = union. No-op when dimension is `None` (can't add to "everything").
- `restrict` = intersection. `None` intersected with a set gives that set.
- `delegate` = restrict + new name.
- Delegation is monotonic: can only narrow, never escalate.
- `None` on any grant/restrict/delegate arg preserves the parent's value.

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
