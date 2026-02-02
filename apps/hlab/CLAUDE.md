# CLAUDE.md — hlab

Homelab monitoring app. DSL defines data, Python renders.

## The Model

**Facts flow into Vertices. Vertices fold Facts through Specs. Boundaries emit Ticks. Ticks flow onward as Facts. The loop closes.**

Three truths:
- **Time is fundamental.** Facts are observations of what occurred. You are always in the present, observing an ordered past.
- **The observer is first-class.** Facts exist because someone observed them. The `observer` field carries attribution.
- **Everything is loops.** Facts flow in, accumulate into state, boundaries fire, ticks flow out. The end connects to the beginning.

Three atoms:
```
Fact    what happened           kind + ts + payload + observer
Spec    how state accumulates   fields + folds + boundary
Tick    what a period became    name + ts + payload + origin
```

## Boundaries: Semantic Time

Boundaries fire on domain semantics, not clocks. The question isn't "how much time has passed?" but "what just happened that gives meaning to everything before it?"

In hlab: each source emits facts with its own kind (`infra`, `media`, `dev`, `minecraft`), then `{kind}.complete`. The `.complete` fact triggers that stack's boundary. Four sources = four loops = four ticks.

**tick.name IS the stack name.** No re-grouping needed in render — state is already per-stack.

## The Feedback Loop

```
Vertex.state ──→ Surface ──→ Observer sees
                    │
Observer acts ──→ Surface.emit ──→ Fact ──→ Vertex
```

Surfaces close the loop. A keypress becomes a Fact, flows into a Vertex, folds into state, triggers a boundary, emits a Tick — which the Surface renders. hlab will use this for actions (restart container → fact → automation loop picks up).

## Run

```bash
uv run python main.py              # TUI (default)
uv run python main.py --once       # single fetch, text output
uv run python main.py --json       # single fetch, JSON output
```

## Structure

```
apps/hlab/
├── infra.loop        # Source: SSH → docker compose ps → ndjson, kind: infra
├── media.loop        # kind: media
├── dev.loop          # kind: dev
├── minecraft.loop    # kind: minecraft
├── status.vertex     # 4 loops (infra, media, dev, minecraft), boundary on {kind}.complete
├── main.py           # Main app: TUI + CLI modes
└── demos/
    └── status.py     # Legacy demo (uses old structure)
```

## Integration Pattern

```
.loop files → compile_loop() → Source
.vertex file → compile_vertex_recursive() → materialize_vertex() → Vertex
Runner(vertex) + runner.add(source) → async for tick in runner.run()
```

Load DSL, materialize runtime, stream ticks, render with cells.

## Key Types

| Type | Library | Role |
|------|---------|------|
| Fact | data | Observation record: kind + ts + payload + observer |
| Spec | data | Contract: fields + folds + boundary |
| Source | data | Ingress: command → parse → facts. Emits `{kind}.complete` when done |
| Tick | vertex | Boundary snapshot: name + ts + payload + origin |
| Vertex | vertex | Routes facts by kind, manages loops, fires boundaries |
| Loop | vertex | Fold engine + boundary. Accumulates state, ticks when boundary fires |
| Runner | data | Orchestrates sources → vertex. Yields ticks as async iterator |
| Surface | cells | Renders state, emits input as facts |

## Gotchas

**tick.name IS the stack name:**
```python
# tick.name = "infra", "media", "dev", or "minecraft"
# tick.payload = {"containers": [...]}
async for tick in runner.run():
    self._stacks[tick.name] = tick.payload.get("containers", [])
```

**Tick payload is raw state, not nested:**
```python
# Wrong
containers = tick.payload.get("infra", {}).get("containers", [])

# Right
containers = tick.payload.get("containers", [])
```

**One tick per stack, not one aggregated tick:**
Each source emits its own kind, fires its own boundary. Four ticks total.

## Working Here

1. **Run first, then code** — Print actual tick payloads before writing render logic
2. **DSL is source of truth** — No hardcoded config that duplicates .loop files
3. **Trace data, not code** — When debugging, feed facts and print state
4. **Fidelity is render-side** — DSL doesn't know about zoom levels; that's cells' job
5. **Boundaries are semantic** — They fire when data says so, not on timers

## Lib Imports

```python
# DSL: load and compile
from dsl import (
    parse_vertex_file, parse_loop_file,
    compile_vertex_recursive, compile_loop,
    materialize_vertex
)

# Runtime: orchestrate
from data import Runner
from vertex import Tick

# Render: cells
from cells import Block, Style, join_vertical, border, print_block
from cells.tui import Surface
```

## Next

- **Actions**: keypress → emit fact → loop picks up → executes (restart container)
- **Polling**: `every: 30s` in .loop for live updates
- **More views**: different vertex configurations, same sources
- **Nesting**: stack ticks → region vertex → global tick (hierarchy emerges)
