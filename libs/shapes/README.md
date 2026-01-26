# shapes

Declarative schema shapes: `Field + Fold + Form`.

## What it is

Shape contracts that define how events become state. Three primitives:

- **Field** — a typed slot (`name + kind`), with optional marker (`"int?"`)
- **Fold** — a transformation rule (`op + target`): latest, collect, count, upsert, sum
- **Form** — a complete contract: input fields + state fields + fold rules

## Usage

```python
from shapes import Field, Fold, Form

# Define what events look like
input_fields = (
    Field("host", "str"),
    Field("cpu", "float"),
    Field("status", "str"),
)

# Define what state looks like
state_fields = (
    Field("hosts", "dict"),
    Field("readings", "list"),
    Field("count", "int"),
)

# Define how events update state
folds = (
    Fold("upsert", "hosts", props={"key": "host"}),
    Fold("collect", "readings", props={"max": 100}),
    Fold("count", "count"),
)

form = Form(
    name="host_monitor",
    about="Track host CPU readings",
    input_fields=input_fields,
    state_fields=state_fields,
    folds=folds,
)

state = form.initial_state()  # {"hosts": {}, "readings": [], "count": 0}
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
