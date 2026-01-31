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
| `Latest` | frozen dataclass | typed fold: store timestamp |
| `Count` | frozen dataclass | typed fold: increment counter |
| `Sum` | frozen dataclass | typed fold: accumulate value |
| `Collect` | frozen dataclass | typed fold: append to list |
| `Upsert` | frozen dataclass | typed fold: insert/update by key |
| `TopN` | frozen dataclass | typed fold: keep top N by field |
| `Min` | frozen dataclass | typed fold: track minimum |
| `Max` | frozen dataclass | typed fold: track maximum |
| `FoldOp` | type alias | union of all fold types |
| `Boundary` | frozen dataclass | kind + reset (cycle completion) |
| `ValidationError` | exception | contract violation |

### Spec Methods

| Method | Purpose |
|--------|---------|
| `apply(state, payload) -> dict` | execute folds, return new state (pure, never mutates) |
| `initial_state() -> dict` | zero-value dict from state_fields |
| `input_field(name)` / `state_field(name)` | lookup by name |

### Typed Folds

Type-safe fold classes with IDE support and self-documenting signatures.

**Primitive folds** — direct mappings to fundamental operations:

| Class | Signature | Behavior |
|-------|-----------|----------|
| `Latest` | `(target)` | `state[target] = payload._ts` |
| `Count` | `(target)` | `state[target] += 1` |
| `Sum` | `(target, field)` | `state[target] += payload[field]` |
| `Collect` | `(target, max=0)` | append to list, 0 = unbounded |
| `Upsert` | `(target, key)` | `state[target][payload[key]] = payload` |

**Convenience folds** — compositions for common patterns:

| Class | Signature | Behavior |
|-------|-----------|----------|
| `TopN` | `(target, key, by, n, desc=True)` | keep top N items by field value |
| `Min` | `(target, field)` | track minimum value seen |
| `Max` | `(target, field)` | track maximum value seen |

```python
# Examples
Latest(target="last_seen")
Count(target="events")
Sum(target="total", field="amount")
Collect(target="history", max=100)
Upsert(target="users", key="id")
TopN(target="top_procs", key="pid", by="cpu", n=5)
Min(target="coldest", field="temp")
Max(target="peak", field="memory")
```

## Invariants

- All types frozen (dataclasses with `frozen=True`).
- `Spec.apply()` is pure: copies state, applies folds, returns new dict. Never mutates input.
- `Spec.apply()` does not check boundary — boundary is declarative, checked externally by the fold engine.
- A Spec with no boundary (`None`) folds continuously — no cycle, no Tick produced.
- Fold closures built by `engine.py` at call time from typed fold classes.
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
  __init__.py    # Re-exports: Boundary, Facet, Field, FoldOp, Shape, Spec, ValidationError
                 #             + typed folds: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max
  boundary.py    # Boundary (kind + reset)
  facet.py       # Field (name + kind + optional) + Facet alias
  fold.py        # Typed fold classes + FoldOp union
  spec.py        # Spec (fields + folds + boundary + apply) + Shape alias
  engine.py      # Fold closure builder (_make_latest, _make_count, etc.)
  types.py       # initial_value, coerce_value, type_matches, ValidationError
tests/
  test_shapes.py    # Core type tests
  test_fold_typed.py # Typed fold tests
```
