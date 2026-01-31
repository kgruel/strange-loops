# CLAUDE.md — specs

Data contracts and fold rules. Answers: **how does raw data become state?**

## Build & Test

```bash
uv run --package specs pytest libs/specs/tests
```

## Atom

```
Spec
 ├─ name: str                      # identity (matches Fact.kind by convention)
 ├─ about: str                     # human description
 ├─ input_fields: tuple[Field, ...]  # what incoming payloads contain
 ├─ state_fields: tuple[Field, ...]  # what accumulated state looks like
 ├─ folds: tuple[Fold, ...]        # transformation rules
 └─ boundary: Boundary | None      # cycle completion declaration

Boundary
 ├─ kind: str                      # fact kind that triggers the boundary
 └─ reset: bool                    # True = reset state, False = carry state
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Spec` | frozen dataclass | fields + folds + boundary + apply |
| `Shape` | alias | backward compat alias for Spec |
| `Field` | frozen dataclass | name + kind (+ optional flag) |
| `Facet` | alias | backward compat alias for Field |
| `Fold` | frozen dataclass | op + target + props |
| `Boundary` | frozen dataclass | kind + reset (cycle completion) |
| `ValidationError` | exception | contract violation |

### Spec Methods

| Method | Purpose |
|--------|---------|
| `apply(state, payload) -> dict` | execute folds, return new state (pure, never mutates) |
| `initial_state() -> dict` | zero-value dict from state_fields |
| `input_field(name)` / `state_field(name)` | lookup by name |

### Fold Operations

| Op | Behavior | Props |
|----|----------|-------|
| `latest` | `state[target] = payload._ts or now()` | — |
| `count` | `state[target] += 1` | — |
| `sum` | `state[target] += payload[field]` | `field=` |
| `collect` | append to list, bounded | `max=` (optional) |
| `upsert` | `state[target][key_value] = payload` | `key=` (required) |

## Invariants

- All types frozen. `Fold.props` wrapped in `MappingProxyType`.
- `Spec.apply()` is pure: copies state, applies folds, returns new dict. Never mutates input.
- `Spec.apply()` does not check boundary — boundary is declarative, checked externally by the fold engine.
- A Spec with no boundary (`None`) folds continuously — no cycle, no Tick produced.
- Fold closures built by `engine.py` at call time from Fold descriptors.
- `Field.kind` is a string from: str, int, float, bool, dict, list, set, datetime.
- `Field.from_type_str("int?")` parses optional suffix.

## Pipeline Role

```
Fact.payload ──→ Spec.apply(state, payload) ──→ new state
                      │
Spec is the contract at every boundary:
  - Describes what input looks like (input_fields)
  - Describes what state looks like (state_fields)
  - Describes how input becomes state (folds)

Projection uses: Projection(initial=spec.initial_state(), fold=spec.apply)
```

## Source Layout

```
src/specs/
  __init__.py    # Re-exports: Boundary, Facet, Field, Fold, Shape, Spec, ValidationError
  boundary.py    # Boundary (kind + reset)
  facet.py       # Field (name + kind + optional) + Facet alias
  fold.py        # Fold (op + target + props)
  spec.py        # Spec (fields + folds + boundary + apply) + Shape alias
  engine.py      # Fold closure builder (_make_latest, _make_count, etc.)
  types.py       # initial_value, coerce_value, type_matches, ValidationError
tests/
  test_shapes.py # 72+ tests across 10 test classes
```
