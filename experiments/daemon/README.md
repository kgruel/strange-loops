# daemon — the mill primitive

A **mill** is a running Projection with an open input. It is the smallest
thing that turns prism's static atoms into a live system.

```
stdin (JSON facts) → fold via Shape → stdout (JSON ticks)
```

The daemon IS a loop: **receive → fold → emit → repeat**.

## Why "mill"

A mill takes raw material in and produces shaped output continuously.
Facts flow in, state accumulates through a Shape, ticks flow out.
It never initiates — it only transforms what arrives.

## Usage

```bash
echo '{"kind":"ping","ts":1700000000.0,"payload":{"v":1}}' \
  | uv run python experiments/daemon/mill.py examples/counter.shape.json
```

Output (one tick per fact, JSON lines):

```json
{"ts": "2023-11-14T22:13:20+00:00", "payload": {"count": 1, "last_seen": 1700000000.0}}
```

## Shape spec

The shape is a JSON file matching the `Shape` constructor:

```json
{
    "name": "counter",
    "about": "Counts events and tracks the last timestamp",
    "input_facets": [{"name": "v", "kind": "int"}],
    "state_facets": [
        {"name": "count", "kind": "int"},
        {"name": "last_seen", "kind": "datetime"}
    ],
    "folds": [
        {"op": "count", "target": "count"},
        {"op": "latest", "target": "last_seen"}
    ]
}
```

See `examples/` for more shape specs.

## What makes it atomic

The mill does exactly one thing: fold facts through a shape and emit ticks.
It has no scheduling, no networking, no storage. Those are separate concerns
composed externally through Unix pipes:

```bash
# persist ticks to a file
... | python mill.py shape.json | tee ticks.jsonl

# chain two mills (ticks from one become facts for another)
... | python mill.py first.json | python mill.py second.json

# fan out with tee + process substitution
... | python mill.py shape.json | tee >(consumer_a) >(consumer_b)
```

## Architecture

```
stdin ──→ parse JSON line as Fact
             │
             ▼
          bridge(fact, shape, state)
             │  extract payload
             │  inject _ts
             │  call shape.apply(state, payload)
             │
             ▼
          new state
             │
             ▼
          emit Tick(ts, state) as JSON ──→ stdout
             │
             └──→ repeat (next line)
```

The bridge function (~3 lines) sits at the composition point between
Fact and Shape. It lives here in the integration layer because it touches
both atoms, and the atoms don't import each other.

## Composability

The mill is a Unix filter. It composes with anything that speaks JSON lines:

- **Source**: any process that writes `{"kind":...,"ts":...,"payload":...}` to stdout
- **Sink**: any process that reads `{"ts":...,"payload":...}` from stdin
- **Chain**: pipe one mill's output as another mill's input (ticks become facts)
