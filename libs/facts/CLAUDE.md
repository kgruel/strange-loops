# CLAUDE.md — facts

Observation atom. Answers: **what happened, when?**

## Build & Test

```bash
uv run --package facts pytest libs/facts/tests
```

## Atom

```
Fact[T]
 ├─ kind: str        # open routing key ("heartbeat", "deploy", etc.)
 ├─ ts: datetime     # when observed (timezone-aware UTC)
 └─ payload: T       # the details — Shape knows the structure
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Fact` | frozen dataclass, Generic[T] | the observation atom |
| `Fact.of(kind, **data)` | classmethod | factory: auto-timestamp, dict payload |
| `Fact.to_dict()` | method | serialize (ISO ts, unwrap MappingProxy) |
| `Fact.from_dict(d)` | classmethod | deserialize (parse ISO ts) |
| `Fact.is_kind(*kinds)` | method | predicate: kind membership check |

## Invariants

- Frozen dataclass. Dict payloads auto-wrapped in `MappingProxyType`.
- `kind` is an open string — no enum, no constrained set. Structure comes from Shape.
- `Fact.of()` always produces `Fact[dict]` with UTC timestamp.
- Round-trip: `Fact.from_dict(f.to_dict())` preserves kind, ts, payload.
- Non-dict payloads (int, str, custom dataclass) pass through unwrapped.

## Pipeline Role

```
Peer ─ observes ─→ Fact ─→ Stream[Fact] ─→ Projection(fold=shape.apply)
                     │
Fact is the pipeline input. Everything starts as an observation.
Fact.kind routes to Shape. Fact.payload is what Shape.apply() folds.
```

## Source Layout

```
src/facts/__init__.py   # Re-exports Fact
src/facts/fact.py       # Fact implementation
tests/test_fact.py      # 10 test classes
```
