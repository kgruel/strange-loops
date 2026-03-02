# atoms — the data layer

Observations, contracts, and ingress. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  lang (grammar)  →  apps (CLI)
Fact, Spec        Tick, Vertex         .loop/.vertex      loops emit/status
```

Above: `libs/engine/` runs facts through vertices — routing, folding, boundary detection, persistence. `apps/loops/` provides the CLI (`loops emit`, `loops status`). When you `loops emit project decision topic=auth ...`, it creates a Fact, resolves a Vertex, and calls `vertex.receive()` — which folds using the Spec you define here.

---

## Level 0 — Observe

**Trigger**: Something happened and I need to record it.

```python
from atoms import Fact

# A human made a decision
Fact.of("decision", "kyle", topic="auth-approach", position="JWT over sessions")

# A system observed something
Fact.of("deploy", "ci-bot", service="api", version="2.3")

# A person noted something worth remembering
Fact.of("thread", "kyle", name="store-ops", status="open")
```

A fact is any observation — a deploy completing, a decision being made, a thought worth recording. Same atom. `kind` is an open routing key — no enum, no schema. `observer` is who recorded it. `payload` is auto-wrapped in `MappingProxyType` (truly immutable). At the CLI level, `loops emit project decision topic=auth ...` does the same thing — creates a Fact and feeds it to a Vertex (see `libs/engine/`).

Factory methods:
- `Fact.of(kind, observer, **payload)` — auto-timestamps, dict payload
- `Fact.tick(kind, observer, **payload)` — prefixes kind with `tick.`

Serialization: `f.to_dict()` / `Fact.from_dict(d)` for persistence.

**Don't reach for yet**: Spec, Fold, Source.

---

## Level 1 — Accumulate

**Trigger**: I need state to build up from facts — counts, latest values, collections.

```python
from atoms import Spec, Field, Boundary, Upsert, Collect

# Decisions accumulate by topic — latest position wins
decisions = Spec(
    name="decision",
    input_fields=(Field("topic", "str"), Field("position", "str")),
    state_fields=(Field("items", "dict"),),
    folds=(Upsert("items", key="topic"),),
)

state = decisions.initial_state()         # {"items": {}}
state = decisions.apply(state, {"topic": "auth", "position": "JWT"})
state = decisions.apply(state, {"topic": "storage", "position": "SQLite"})
state = decisions.apply(state, {"topic": "auth", "position": "JWT + refresh tokens"})
# {"items": {"auth": {...latest...}, "storage": {...}}}
```

This is exactly what `project.vertex` does — decisions fold by topic, threads fold by name. Same Spec, same apply. At runtime, `engine.Vertex` takes these Specs and wires them as fold functions (see `libs/engine/` Level 1).

```python
# Technical use case — bounded event collection
health = Spec(
    name="health",
    input_fields=(Field("container", "str"), Field("status", "str")),
    state_fields=(Field("events", "list"),),
    folds=(Collect("events", max=10),),
    boundary=Boundary(kind="health.close", reset=True),
)
```

`Spec.apply(state, payload)` is pure — deep-copies state, applies folds, returns new state.

**Fold vocabulary** (10 ops):

| Fold | What it does |
|------|-------------|
| `Latest(target)` | Timestamp of last event |
| `Count(target)` | Increment counter |
| `Sum(target, field)` | Add field value |
| `Collect(target, max=0)` | Append payloads (0 = unbounded) |
| `Upsert(target, key)` | Insert/update dict by key field |
| `TopN(target, key, by, n)` | Keep top N by field value |
| `Min(target, field)` | Track minimum |
| `Max(target, field)` | Track maximum |
| `Avg(target, field)` | Running average |
| `Window(target, field, size)` | Sliding window (FIFO, single field) |

**Boundary** controls when a cycle completes:
- `Boundary(kind="health.close")` — fires when that fact kind arrives
- `Boundary(count=10, mode="every")` — fires every N facts
- `reset=True` resets state after firing; `reset=False` carries forward

**Don't reach for yet**: Parse, Source, Runner.

---

## Level 2 — Shape input

**Trigger**: I have raw data (command output, JSON, log lines) that needs shaping before it becomes facts.

```python
from atoms import Split, Pick, Rename, Coerce, run_parse

pipeline = [
    Split(),                          # whitespace split
    Pick(0, 4),                       # keep filesystem and use%
    Rename({0: "filesystem", 1: "use_pct"}),
    Coerce({"use_pct": "int"}),
]

raw = "/dev/sda1  50G  25G  25G  50% /home"
result = run_parse(raw, pipeline)
# {"filesystem": "/dev/sda1", "use_pct": 50}
```

Parse pipeline applies left-to-right. Two execution modes:
- `run_parse(data, pipeline)` — single record in, dict or None out
- `run_parse_many(data, pipeline)` — stream mode for fan-out/filter (when pipeline has `Explode` or `Where`)

**Parse vocabulary** (10 ops):

| Op | Input → Output | Purpose |
|----|----|---------|
| `Skip(startswith=...)` | str/dict → None or pass | Filter out lines |
| `Split(delim, max)` | str → list | Tokenize |
| `Pick(*indices)` | list → list | Select by position |
| `Rename({idx: name})` | list → dict | Positional to named |
| `Transform(field, ...)` | dict → dict | String ops (strip, replace) |
| `Coerce({field: type})` | dict → dict | Type conversion |
| `Select(*fields)` | dict → dict | Keep only these fields |
| `Explode(path, carry)` | dict → list[dict] | Fan-out list field (1→N) |
| `Project({out: path})` | dict → dict | Extract nested JSON paths |
| `Where(path, op, value)` | dict → dict or None | Filter by field value |

**Don't reach for yet**: Source, Runner.

---

## Level 3 — Ingest

**Trigger**: I want external commands to produce facts automatically — polling, triggered, or one-shot.

```python
from atoms import Source

disk = Source(
    command="df -h",
    kind="disk",
    observer="monitor",
    format="lines",
    parse=[Split(), Pick(0, 4), Rename({0: "fs", 1: "use"}), Coerce({"use": "int"})],
    every=60.0,  # poll every 60s
)
```

`Source` bridges shell commands to facts. It runs a command, parses output, emits facts.

**Format modes**: `lines` (each line → fact), `json` (whole output → one fact), `ndjson` (each line as JSON → fact), `blob` (whole output as text → one fact).

**Timing**: `every=N` for polling, `trigger=("kind",)` for event-driven, neither for one-shot.

**Errors as facts**: Failures emit `Fact(kind="source.error", ...)` instead of raising — the runner continues.

`Runner` orchestrates multiple sources against a vertex (from `libs/engine/`):

```python
from atoms import Runner

runner = Runner(vertex)
runner.add(disk_source)
runner.add(health_source)
async for tick in runner.run():
    print(tick.payload)
```

In practice, most code doesn't wire Sources manually — `load_vertex_program()` in engine compiles `.vertex` files that declare sources in KDL (see `libs/engine/` Level 0). This level is for building custom Sources or understanding what the compiler generates.

---

## Key invariants

- All types frozen. `Fact.payload` wrapped in `MappingProxyType`.
- `Spec.apply` is pure — deep-copy, fold, return. No mutation.
- Kind is an open string — structure comes from Spec, not kind.
- Parse vocabulary shapes raw input; fold vocabulary accumulates state. Different concerns.
- Errors are facts, not exceptions.
- Zero runtime dependencies.

## Build & test

```bash
uv run --package atoms pytest libs/atoms/tests
uv run --package atoms pytest libs/atoms/tests/test_fold_typed.py  # single file
```

## Decisions

Query project-specific atoms decisions:
```bash
loops log project --kind decision | grep atoms/
```
