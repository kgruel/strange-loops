# Rung 02 — Vertices & Loops: the runtime

> **What you'll learn:** How the engine automates fold routing with Vertex and Loop, how boundaries produce Ticks, and how multiple loops in one vertex compose.
> **Prerequisites:** [Rung 01 — Atoms: the data layer](01-atoms-the-data-layer.md)
> **Time:** ~15 min

In [Rung 01](01-atoms-the-data-layer.md) you folded facts by hand: call `spec.apply(state, fact.payload)` for each fact in a loop. The engine's `Vertex` automates exactly that — and adds routing (many fact kinds, each with its own fold), boundaries (snapshot state into a Tick when a trigger fires), and persistence (optional store backing). This rung covers the in-memory runtime. Persistence comes in [Rung 03](03-persistence-and-replay.md).

---

## Vertex — the routing layer

```python
from atoms import Fact
from engine import Vertex

v = Vertex("meter")
```

`Vertex("meter")` creates a named vertex. The name is stamped as `origin` on every Tick it produces. It holds no facts and has no folds yet — you register them.

### register — attaching a fold

```python
v.register(kind, initial_state, fold_fn, *, boundary=None, reset=True)
```

- `kind` — the fact kind this fold handles
- `initial_state` — the zero value for this fold's state
- `fold_fn` — `(state, payload) -> new_state`
- `boundary` — (optional) fact kind that triggers a Tick snapshot
- `reset` — whether state resets to `initial_state` after the boundary fires

Internally, `register` constructs a `Loop` and stores it under the kind. Callers rarely touch `Loop` directly — it is the engine's internal fold-and-fire unit.

### receive — routing a fact

```python
result = v.receive(fact)   # returns Tick | None
```

`receive` routes the fact by kind. If the kind matches a registered fold, it calls the fold function and updates state. If the kind matches a boundary, it fires the boundary and returns a `Tick`. Otherwise it returns `None` and the fact passes through silently (stored if a store is attached, but not folded).

### state — reading the current fold state

```python
v.state("metric")   # current fold state for kind "metric"
```

Raises `KeyError` if the kind is not registered.

---

## Canonical example

This is the verified wiring pattern to build from in your own code:

```python
from atoms import Fact
from engine import Vertex

v = Vertex("meter")
v.register(
    "metric",               # kind to fold
    0,                      # initial state (int)
    lambda state, payload: state + payload["value"],   # fold fn
    boundary="flush",       # "flush" fact triggers a Tick
    reset=True,             # state resets to 0 after boundary
)

v.receive(Fact.of("metric", "me", value=10))
v.receive(Fact.of("metric", "me", value=5))
v.state("metric")          # 15

tick = v.receive(Fact.of("flush", "me"))
# Tick(name="metric", payload=15, origin="meter")
```

After the boundary fires: `v.state("metric")` returns `0` (reset). The next facts start a fresh accumulation cycle.

With `reset=False`, the state is *not* cleared — the Tick carries the snapshot and the fold continues accumulating from where it left off:

```python
v.register("running", 0, lambda s, p: s + p["n"], boundary="checkpoint", reset=False)
v.receive(Fact.of("running", "me", n=10))
tick = v.receive(Fact.of("checkpoint", "me"))
# tick.payload == 10, v.state("running") == 10 (still)
v.receive(Fact.of("running", "me", n=5))
v.state("running")   # 15
```

---

## Tick — the boundary snapshot

`Tick` is a frozen dataclass produced when a boundary fires:

| Field | Type | Meaning |
|---|---|---|
| `name` | `str` | Which loop fired (the fold kind) |
| `ts` | `datetime` | When the boundary fired |
| `payload` | `Any` | The fold state at that moment |
| `origin` | `str` | The vertex that produced this tick |
| `since` | `datetime \| None` | When the period started (first fact after last reset) |
| `run` | `str \| None` | Shell command to execute (carried for app layer) |

`since` supports fidelity traversal — `store.between(tick.since, tick.ts)` retrieves exactly the facts that produced this tick's payload. This is covered in [Rung 03](03-persistence-and-replay.md) and explored fully in [deep dive: TEMPORAL](../TEMPORAL.md).

---

## Boundary modes

The `boundary` argument to `register` takes a **kind string** — when a fact of that kind arrives, the loop fires. This is the `"when"` mode, and it's the most common.

For count-based boundaries, you construct a `Loop` explicitly and register it with `register_loop`:

```python
from engine import Loop, Vertex

v = Vertex("batcher")
loop = Loop(
    name="events",
    initial=[],
    fold=lambda state, payload: [*state, payload],
    boundary_count=10,
    boundary_mode="every",  # fire every 10 facts
    reset=True,
)
v.register_loop(loop)
```

The three modes:

| Mode | Trigger | Semantics |
|---|---|---|
| `"when"` (default) | fact of boundary kind arrives | fires on each matching fact |
| `"every"` | after every N facts | fires repeatedly, resets count |
| `"after"` | after first N facts | fires once, then exhausted |

`register_loop` is the lower-level entry point. `register` is a convenience wrapper that constructs the Loop for you — for kind-based boundaries, prefer `register`.

---

## Multiple loops in one vertex

A vertex can hold as many registered folds as you need. Each kind gets its own independent state:

```python
v = Vertex("dashboard")

v.register(
    "metric",
    {"total": 0, "count": 0},
    lambda s, p: {**s, "total": s["total"] + p["value"], "count": s["count"] + 1},
    boundary="flush",
)
v.register(
    "error",
    [],
    lambda s, p: [*s, p["message"]],
    # no boundary — continuous accumulation
)

v.receive(Fact.of("metric", "app", value=10))
v.receive(Fact.of("error",  "app", message="timeout"))
v.receive(Fact.of("metric", "app", value=20))
tick = v.receive(Fact.of("flush", "app"))

# tick.name == "metric", tick.payload == {"total": 30, "count": 2}
# v.state("error") == ["timeout"]  (unchanged, no boundary on error)
```

Kinds that are not registered are silently ignored (the fact is stored if a store is attached, but not folded). This is by design — a vertex folds what it cares about and ignores the rest.

---

## How Loop works internally

You rarely construct Loop directly, but understanding its role clarifies the separation of concerns:

- **Vertex** owns routing: given a fact, which loop gets it?
- **Loop** owns fold-and-fire: accumulate state, decide when to snapshot.

`Loop.receive(payload, ts)` folds the payload into the projection and tracks the period start (timestamp of the first fact after construction or reset). When a boundary fires, `Loop.fire(ts, origin)` snapshots the current state into a `Tick` and — if `reset=True` — resets the projection to the initial state and clears `_period_start` so the next `receive` starts a new period.

The `Projection` is an internal fold engine inside Loop. Callers never instantiate it.

---

## Nested vertices

Ticks from one vertex can feed a downstream vertex as facts. This is how multi-level aggregation works — batches roll up into summaries:

```python
upstream = Vertex("upstream")
upstream.register("metric", 0, lambda s, p: s + p["value"], boundary="flush", reset=True)

downstream = Vertex("downstream")
downstream.register("tick-metric", 0, lambda s, p: s + p["value"])

upstream.receive(Fact.of("metric", "me", value=10))
upstream.receive(Fact.of("metric", "me", value=5))
tick1 = upstream.receive(Fact.of("flush", "me"))  # tick1.payload == 15

upstream.receive(Fact.of("metric", "me", value=20))
tick2 = upstream.receive(Fact.of("flush", "me"))  # tick2.payload == 20

# Downstream receives ticks as facts
downstream.receive(Fact.of("tick-metric", "upstream", value=tick1.payload))
downstream.receive(Fact.of("tick-metric", "upstream", value=tick2.payload))
downstream.state("tick-metric")   # 35
```

The pattern: upstream Tick's `payload` becomes the value in a downstream Fact's payload. The downstream vertex folds Ticks-as-facts. Vertices can also be wired together with `add_child` so the forwarding happens automatically — but the manual form shown here makes the data flow explicit.

For the full design of nesting and vertex-level boundaries (which snapshot all loop states at once), see [deep dive: VERTEX](../VERTEX.md) and [deep dive: TEMPORAL](../TEMPORAL.md).

---

## What receive does, step by step

When `v.receive(fact)` is called:

1. Gate check: if a `Grant` is attached and the kind is not in its `potential`, reject and return `None`.
2. Persist: if a `Store` is attached, append the fact before folding.
3. Route: resolve the fact's `kind` to a registered Loop (or route pattern).
4. Fold: call `loop.receive(payload, ts)`, which calls the fold function and updates state.
5. Forward: if child vertices are attached, forward the fact to those that accept the kind.
6. Boundary check: if the kind matches a boundary trigger, call `loop.fire()` and return the resulting Tick; otherwise return `None`.

The fold happens before the boundary check — state is up to date in the Tick's payload.

---

**Next:** [Rung 03 — Persistence & Replay](03-persistence-and-replay.md)
**See also:** [deep dive: VERTEX](../VERTEX.md) · [deep dive: TEMPORAL](../TEMPORAL.md) · [API reference](../api-reference.md) · [guide index](README.md)
