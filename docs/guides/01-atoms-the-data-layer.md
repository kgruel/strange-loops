# Rung 01 — Atoms: the data layer

> **What you'll learn:** What a Fact is, how to define fold contracts with Spec and Field, and how the full vocabulary of fold operations turn a sequence of facts into accumulated state — all without the engine.
> **Prerequisites:** none — start here
> **Time:** ~15 min

The `atoms` library is the bottom of the stack. It defines the three shapes — Fact, Spec, Tick — as pure data, with no runtime, no I/O, and no database. Everything above it (engine, CLI) speaks in atoms' vocabulary. You can reason about, test, and compose atoms without instantiating a single vertex.

This rung covers Fact and Spec. Tick appears in [Rung 02 — Vertices & Loops](02-engine-vertices-and-loops.md) where the engine produces it.

---

## Fact — the observation atom

A `Fact` is a frozen record of something that happened. Five fields:

| Field | Type | Meaning |
|---|---|---|
| `kind` | `str` | Open routing key — `"heartbeat"`, `"deploy"`, `"error"` |
| `ts` | `float` | Epoch seconds when observed |
| `payload` | `MappingProxyType` | The details (immutable dict) |
| `observer` | `str` | Who produced this observation |
| `origin` | `str` | Which vertex/loop produced it (`""` for external observations) |

The constructor you'll use almost exclusively is `Fact.of`:

```python
from atoms import Fact

f = Fact.of("heartbeat", "monitor", service="api", latency=42)

print(f.kind)       # "heartbeat"
print(f.observer)   # "monitor"
print(f.payload)    # mappingproxy({"service": "api", "latency": 42})
print(f.ts)         # 1748123456.789 (epoch float, auto-set)
print(f.origin)     # "" (external observation)
```

The signature: `Fact.of(kind, observer, *, origin="", ts=None, **data)`. Everything after the two positional arguments becomes the payload.

### Immutability is load-bearing

`Fact` is frozen — it raises `FrozenInstanceError` on any attempted mutation. This is intentional, not just defensive coding. The whole system is append-only: observations are never edited, only added. A new fact with a corrected value replaces an old one by the fold logic choosing latest-per-key — the original stays in the store as history.

```python
f = Fact.of("metric", "sensor", value=10)
f.value = 20  # raises FrozenInstanceError
```

The payload is also wrapped in `MappingProxyType`, so `f.payload["value"] = 20` fails too. Use `dataclasses.replace(f, payload={"value": 20})` to produce a new Fact with modified fields when you need one (rare in normal use).

---

## Spec and Field — the fold contract

A `Spec` defines the data contract for accumulating a sequence of facts into state. It has four components:

- `input_fields` — what the incoming fact payload must contain
- `state_fields` — what the accumulated state looks like (and their initial values)
- `folds` — rules that map each incoming payload to a state update
- `boundary` — (optional) when to snapshot state into a Tick

Import the pieces you need:

```python
from atoms import Spec, Field, Sum, Count, Collect
```

### Field

`Field(name, kind, optional=False)` is the typed slot declaration. `kind` is a string:

| `kind` string | Initial value | Python type |
|---|---|---|
| `"int"` | `0` | `int` |
| `"float"` | `0` | `float` |
| `"str"` | `""` | `str` |
| `"bool"` | `False` | `bool` |
| `"dict"` | `{}` | `dict` |
| `"list"` | `[]` | `list` |
| `"set"` | `set()` | `set` |

```python
from atoms import Field

amount_field = Field("amount", "int")        # required int
tag_field    = Field("tag", "str", optional=True)  # optional string
```

The `kind` string drives `Spec.initial_state()` — it creates the zero value for each state field automatically.

### Spec — putting it together

```python
from atoms import Spec, Field, Sum, Count

spend_spec = Spec(
    name="spend",
    about="Total spend and event count",
    input_fields=(
        Field("amount", "int"),
    ),
    state_fields=(
        Field("total", "int"),
        Field("events", "int"),
    ),
    folds=(
        Sum(target="total", field="amount"),
        Count(target="events"),
    ),
)
```

`Spec.initial_state()` returns `{"total": 0, "events": 0}` — one zero per state field, type-derived.

`Spec.apply(state, payload)` takes the current state dict and one fact's payload dict, returns a **new** state dict (pure, no mutation):

```python
state = spend_spec.initial_state()   # {"total": 0, "events": 0}
state = spend_spec.apply(state, {"amount": 10})  # {"total": 10, "events": 1}
state = spend_spec.apply(state, {"amount": 5})   # {"total": 15, "events": 2}
```

`Spec.replay(payloads)` does the same across a whole sequence, mutating one state dict in place (faster than chaining `apply` when you don't need intermediate states):

```python
state = spend_spec.replay([
    {"amount": 10},
    {"amount": 5},
    {"amount": 20},
])
# {"total": 35, "events": 3}
```

---

## Fold vocabulary

The `folds` tuple inside a Spec is composed from these typed fold operations. Each becomes a `(state, payload) -> None` closure at runtime.

### Primitive folds

**`Count(target)`** — increment a counter on every fact:

```python
Count(target="events")
# each fact: state["events"] += 1
```

**`Sum(target, field)`** — accumulate a numeric field:

```python
Sum(target="total", field="amount")
# {"amount": 10} → state["total"] += 10
```

**`Latest(target)`** — store the timestamp of the most recent fact (reads `payload["_ts"]`):

```python
Latest(target="last_seen")
# each fact: state["last_seen"] = payload.get("_ts", time.time())
```

**`Collect(target, max=0)`** — append each payload dict to a list; `max=0` is unbounded:

```python
Collect(target="history", max=100)
# keeps the last 100 full payloads
```

**`Upsert(target, key)`** — insert or update a dict keyed by a payload field (merge semantics — prior fields persist unless overwritten):

```python
Upsert(target="users", key="id")
# {"id": "alice", "role": "admin"} → state["users"]["alice"] = {merged entry}
```

### Convenience folds

**`Min(target, field)`** — track the minimum value seen:

```python
Min(target="coldest", field="temp")
# state["coldest"] = min across all received "temp" values
```

**`Max(target, field)`** — track the maximum value seen:

```python
Max(target="peak", field="memory")
```

**`Avg(target, field)`** — running average (maintains hidden sum/count state):

```python
Avg(target="rate", field="latency")
# state["rate"] = running average of all "latency" values
```

**`TopN(target, key, by, n, desc=True)`** — keep top N items by a numeric field:

```python
TopN(target="top_procs", key="pid", by="cpu", n=5)
# keeps the 5 processes with highest cpu, keyed by pid
```

**`Window(target, field, size)`** — sliding FIFO buffer of a single field's values (drops oldest when full):

```python
Window(target="intervals", field="interval", size=10)
# state["intervals"] = last 10 "interval" values
```

The key distinction between `Collect` and `Window`: `Collect` appends the full payload dict and keeps the last N payloads; `Window` appends a single field's scalar value and keeps the last N values. Use `Collect` when you need the whole record; use `Window` when you need a numeric series for rate/jitter calculations.

---

## Folding by hand — seeing the properties

To understand why the engine exists, it helps to drive a fold manually. Here is the full sequence you would write if there were no Vertex:

```python
from atoms import Fact, Spec, Field, Sum, Count

# Define the contract
purchase_spec = Spec(
    name="purchases",
    about="Accumulate purchase totals",
    input_fields=(Field("amount", "int"), Field("item", "str")),
    state_fields=(Field("total", "int"), Field("count", "int")),
    folds=(Sum(target="total", field="amount"), Count(target="count")),
)

# Create some observations
facts = [
    Fact.of("purchase", "store", amount=10, item="coffee"),
    Fact.of("purchase", "store", amount=25, item="book"),
    Fact.of("purchase", "store", amount=5,  item="snack"),
]

# Fold by hand: start from initial state, apply each payload in order
state = purchase_spec.initial_state()  # {"total": 0, "count": 0}
for fact in facts:
    state = purchase_spec.apply(state, fact.payload)

print(state)  # {"total": 40, "count": 3}
```

Three properties are visible here:

1. **Immutable facts.** The `facts` list never changes. Each `fact.payload` is a read-only view. The fold only reads from facts, never writes to them.

2. **Append-only.** Adding a new fact appends to the sequence; nothing is replaced. To "correct" a value, you'd append a new fact with the right amount and let the fold see both.

3. **Unidirectional.** State flows in one direction: `(state, payload) -> new_state`. Applying them out of order would produce a different result only if the fold is non-commutative (like `Collect` or `Latest`). The engine replays in insertion order to preserve causality.

The key insight: `fact.payload` is the bridge. The Spec knows nothing about `Fact` — it just takes a dict. When you write `spec.apply(state, fact.payload)` you're connecting the observation atom to the fold contract manually. This is exactly what a `Vertex` automates in the next rung — it routes facts by `kind` to the right fold engine and calls the equivalent of `apply` on each arrival.

---

## The Boundary descriptor

`Boundary` is the last atoms piece worth knowing before you meet the engine. A Spec can carry one:

```python
from atoms import Boundary

Boundary(kind="flush", reset=True)    # fire when a "flush" fact arrives
Boundary(count=100, mode="every")     # fire every 100 facts
Boundary(count=50,  mode="after")     # fire once after 50 facts
```

The Boundary descriptor lives on a Spec but is only *acted on* by the engine's Vertex and Loop. Atoms defines it; engine implements it. So you'll see more in [Rung 02](02-engine-vertices-and-loops.md).

---

**Next:** [Rung 02 — Vertices & Loops: the runtime](02-engine-vertices-and-loops.md)
**See also:** [deep dive: VERTEX](../VERTEX.md) · [deep dive: TEMPORAL](../TEMPORAL.md) · [API reference](../api-reference.md) · [guide index](README.md)
