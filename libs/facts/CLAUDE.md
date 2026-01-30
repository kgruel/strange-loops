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
 ├─ ts: float        # epoch seconds — when observed. Display formatting is caller's problem.
 ├─ payload: T       # the details — Shape knows the structure
 └─ observer: str    # who produced this observation (required)
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Fact` | frozen dataclass, Generic[T] | the observation atom |
| `Fact.of(kind, observer, **data)` | classmethod | factory: auto-timestamp (epoch float), dict payload |
| `Fact.tick(name, observer, **data)` | classmethod | boundary factory: auto-prefixes kind to `tick.{name}`, same semantics as `of()` |
| `Fact.to_dict()` | method | serialize (float ts, unwrap MappingProxy, includes observer) |
| `Fact.from_dict(d)` | classmethod | deserialize (float ts, observer) |
| `Fact.is_kind(*kinds)` | method | predicate: kind membership check |

## Invariants

- Frozen dataclass. Dict payloads auto-wrapped in `MappingProxyType`.
- `kind` is an open string — no enum, no constrained set. Structure comes from Shape.
- `observer` is required — identifies who produced the observation.
- `Fact.of()` always produces `Fact[dict]` with epoch float timestamp (`time.time()`).
- `Fact.tick(name)` produces `Fact[dict]` with `kind="tick.{name}"` — same semantics as `of()`.
- Round-trip: `Fact.from_dict(f.to_dict())` preserves kind, ts, payload, observer.
- Non-dict payloads (int, str, custom dataclass) pass through unwrapped.

## Pipeline Role

```
Observer ─ produces ─→ Fact ─→ Stream[Fact] ─→ Projection(fold=shape.apply)
                         │
Fact is the pipeline input. Everything starts as an observation.
Fact.kind routes to Shape. Fact.payload is what Shape.apply() folds.
Fact.observer identifies who made the observation.
```

## Source Layout

```
src/facts/__init__.py   # Re-exports Fact
src/facts/fact.py       # Fact implementation
tests/test_fact.py      # 9 test classes
```
