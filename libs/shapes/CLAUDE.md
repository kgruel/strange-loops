# CLAUDE.md — shapes

Data contracts and fold rules. Answers: **how does raw data become state?**

## Build & Test

```bash
uv run --package shapes pytest libs/shapes/tests
```

## Atom

```
Shape
 ├─ name: str                      # identity (matches Fact.kind by convention)
 ├─ about: str                     # human description
 ├─ input_facets: tuple[Facet, ...]  # what incoming payloads contain
 ├─ state_facets: tuple[Facet, ...]  # what accumulated state looks like
 ├─ folds: tuple[Fold, ...]        # transformation rules
 └─ boundary: Boundary | None      # cycle completion declaration

Boundary
 ├─ kind: str                      # fact kind that triggers the boundary
 └─ reset: bool                    # True = reset state, False = carry state
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Shape` | frozen dataclass | facets + folds + boundary + apply |
| `Facet` | frozen dataclass | name + kind (+ optional flag) |
| `Fold` | frozen dataclass | op + target + props |
| `Boundary` | frozen dataclass | kind + reset (cycle completion) |
| `ValidationError` | exception | contract violation |

### Shape Methods

| Method | Purpose |
|--------|---------|
| `apply(state, payload) -> dict` | execute folds, return new state (pure, never mutates) |
| `initial_state() -> dict` | zero-value dict from state_facets |
| `input_facet(name)` / `state_facet(name)` | lookup by name |

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
- `Shape.apply()` is pure: copies state, applies folds, returns new dict. Never mutates input.
- `Shape.apply()` does not check boundary — boundary is declarative, checked externally by the fold engine.
- A Shape with no boundary (`None`) folds continuously — no cycle, no Tick produced.
- Fold closures built by `engine.py` at call time from Fold descriptors.
- `Facet.kind` is a string from: str, int, float, bool, dict, list, set, datetime.
- `Facet.from_type_str("int?")` parses optional suffix.

## Pipeline Role

```
Fact.payload ──→ Shape.apply(state, payload) ──→ new state
                      │
Shape is the contract at every boundary:
  - Describes what input looks like (input_facets)
  - Describes what state looks like (state_facets)
  - Describes how input becomes state (folds)

Projection uses: Projection(initial=shape.initial_state(), fold=shape.apply)
```

## Source Layout

```
src/shapes/
  __init__.py    # Re-exports: Boundary, Facet, Fold, Shape, ValidationError
  boundary.py    # Boundary (kind + reset)
  facet.py       # Facet (name + kind + optional)
  fold.py        # Fold (op + target + props)
  shape.py       # Shape (facets + folds + boundary + apply)
  engine.py      # Fold closure builder (_make_latest, _make_count, etc.)
  types.py       # initial_value, coerce_value, type_matches, ValidationError
tests/
  test_shapes.py # 72 tests across 8 test classes
```
