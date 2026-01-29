# specs

Declarative schema specs: Facet, Fold, Spec

## Atom

```
Spec
 ├─ name: str
 ├─ about: str
 ├─ input_facets: tuple[Facet, ...]    # what events look like
 ├─ state_facets: tuple[Facet, ...]    # what state looks like
 ├─ folds: tuple[Fold, ...]           # how events update state
 └─ boundary: Boundary | None         # when a fold cycle completes

Facet
 ├─ name: str       # field name
 └─ kind: str       # type marker ("str", "int", "dict", "int?")

Fold
 ├─ op: str         # operation (latest, collect, count, upsert, sum)
 ├─ target: str     # which state facet to update
 └─ props: dict     # operation-specific config

Boundary
 ├─ kind: str       # fact kind that triggers the boundary
 └─ reset: bool     # True = reset state, False = carry forward
```

## Usage

```python
from specs import Facet, Fold, Spec

# Define what events look like
input_facets = (
    Facet("host", "str"),
    Facet("cpu", "float"),
    Facet("status", "str"),
)

# Define what state looks like
state_facets = (
    Facet("hosts", "dict"),
    Facet("readings", "list"),
    Facet("count", "int"),
)

# Define how events update state
folds = (
    Fold("upsert", "hosts", props={"key": "host"}),
    Fold("collect", "readings", props={"max": 100}),
    Fold("count", "count"),
)

spec = Spec(
    name="host_monitor",
    about="Track host CPU readings",
    input_facets=input_facets,
    state_facets=state_facets,
    folds=folds,
)

state = spec.initial_state()  # {"hosts": {}, "readings": [], "count": 0}
```

## API

| Export | Purpose |
|--------|---------|
| `Facet` | Named, typed face of a spec (name + kind) |
| `Fold` | Transformation rule (op + target + props) |
| `Boundary` | Cycle completion declaration (kind + reset) |
| `Spec` | Complete contract: input facets + state facets + folds + boundary |
| `Shape` | Backward compat alias for Spec |
| `Spec.apply()` | Execute folds: pure dict → dict |
| `Spec.initial_state()` | Generate initial state from state facets |

### Fold operations

| Op | Behavior | Props |
|----|----------|-------|
| `latest` | Replace with most recent value/timestamp | — |
| `collect` | Append to list | `max=` bound |
| `count` | Increment counter | — |
| `upsert` | Update-or-insert into dict or set | `key=` field |
| `sum` | Accumulate numeric value | — |
