# shapes

Data contracts for how events become state: `Facet + Fold + Shape`.

## What it is

Shape contracts that define how events become state. Three primitives:

- **Facet** — a named, typed face of a shape (`name + kind`), with optional marker (`"int?"`)
- **Fold** — a transformation rule (`op + target`): latest, collect, count, upsert, sum
- **Shape** — a complete contract: input facets + state facets + fold rules

## Usage

```python
from shapes import Facet, Fold, Shape

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

shape = Shape(
    name="host_monitor",
    about="Track host CPU readings",
    input_facets=input_facets,
    state_facets=state_facets,
    folds=folds,
)

state = shape.initial_state()  # {"hosts": {}, "readings": [], "count": 0}
```

## Fold operations

| Op | Behavior | Props |
|----|----------|-------|
| `latest` | Replace with most recent value/timestamp | — |
| `collect` | Append to list | `max=` bound |
| `count` | Increment counter | — |
| `upsert` | Update-or-insert into dict or set | `key=` field |
| `sum` | Accumulate numeric value | — |

## Dependencies

None. Stdlib only.
