# Handoff: Personal Event Infrastructure

## The Concept

This project is building **personal-scale event infrastructure** — the same concepts as Kafka (append-only logs, offset-tracking consumers, materialized views) but at individual/homelab scale, using files instead of brokers.

The pattern is always:

```
Typed fact → Append-only log → Derived views (projections)
```

This applies across all contexts — homelab monitoring, work alerting, cognitive effort capture, tool automation, research triggers. The common shape was discovered through iterative exploration of reaktiv/Signals, events-primary architecture, stream topology, and render primitives.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Producers                                               │
│  Scripts, hooks, collectors — anything that emits facts   │
│  Write via: FileWriter, ev Emitter, direct JSONL append  │
├─────────────────────────────────────────────────────────┤
│  The Log                                                 │
│  JSONL files. One file = one topic. Append-only.         │
│  The filesystem IS the broker.                           │
├─────────────────────────────────────────────────────────┤
│  Consumers                                               │
│  Tailer (offset-tracking reader) → Projection (fold)     │
│  In-process: Stream → direct fan-out (fast path)         │
│  Cross-process: file → Tailer → Projection (general)     │
├─────────────────────────────────────────────────────────┤
│  Spec Layer (NEW)                                        │
│  .projection.kdl — declares events, state, fold ops      │
│  .app.kdl — composes projections, loads inventory         │
│  Convention renderer — state shape → component            │
├─────────────────────────────────────────────────────────┤
│  Display                                                 │
│  RenderApp checks Projection.version, paints on change   │
│  Cell-buffer TUI: Buffer+diff, styled composition        │
└─────────────────────────────────────────────────────────┘
```

**Two paths, same Projection interface:**

- **In-process** — Stream[T] fans out to consumers in the same event loop. Zero IO, synchronized.
- **Persistent** — Producer writes JSONL via FileWriter. Consumer uses Tailer to read, feeds Projection. Survives process boundaries. Tap in/out at will.

## Spec-Driven Projections (Latest Work)

The big addition: **KDL specs as projection contracts**. An app is a collection of projection specs. The render layer derives views from state shapes. Adding a projection = adding a `.kdl` file + one `use` line.

### The Design

```
.projection.kdl (declares: event shapes, state shapes, fold ops)
        ↓ (parsed at runtime)
SpecProjection (fold function built from ops)
        ↓
Convention renderer (dict→table, list→list_view, set→tags, scalar→label)
        ↓
RenderApp (paints projection.state without knowing event source)
```

### Fold Ops (built-in, declarative)

| Op | Behavior |
|----|----------|
| `latest "field"` | state[field] = event timestamp |
| `collect "field" max=N` | append to bounded list |
| `count "field"` | increment counter |
| `upsert "field" key=K` | update-or-insert into dict; add to set |

Custom folds stay in Python. Patterns bubble up to ops if they repeat.

### Example Spec

```kdl
// specs/vm-health.projection.kdl
projection "vm-health" {
    about "Container health state per VM"

    event "container.status" {
        container "str"
        service "str"
        state "str"
        health "str?"
        healthy "bool"
    }

    state {
        containers "dict"
        last_update "datetime?"
    }

    fold {
        upsert "containers" key="container"
        latest "last_update"
    }
}
```

### App Composition

```kdl
// specs/homelab.app.kdl
app "homelab" {
    about "Homelab VM dashboard"
    watch true

    inventory "~/Code/gruel.network/ansible/inventory.yml"

    per-connection {
        use "vm-health"
        use "vm-logs"
    }
}
```

Add a `use` line, save — dashboard gains a new panel. The vision: hot-reload on spec file change.

### Convention-Based Rendering

No explicit view declarations needed. State field type implies component:

| State type | Renders as |
|-----------|------------|
| `dict` | table (keys=rows, nested fields=columns) |
| `list` | scrolling list (auto-scroll to bottom) |
| `set` | inline tags |
| scalar | labeled value |

Override with explicit view hints only when convention breaks down.

## Current State

### Framework (topology primitives)

| File | Type | Role |
|------|------|------|
| `stream.py` | Stream[T] | In-process typed fan-out |
| `projection.py` | Projection[S,T] | Fold events → state + version counter |
| `store.py` | EventStore[T] | In-memory append-only log (Consumer protocol) |
| `file_writer.py` | FileWriter[T] | JSONL append (producer side) |
| `tailer.py` | Tailer[T] | JSONL reader with offset tracking (consumer side) |
| `forward.py` | Forward[T,U] | Bridge between typed streams |
| `spec.py` | SpecProjection | KDL parser + declarative fold ops runtime |
| `app_spec.py` | AppSpec | App composition parser + inventory loader |
| `spec_render.py` | render_projection() | Convention-based state→component mapping |

### Render (cell-buffer TUI engine)

Novel for Python. No curses dependency, pure ANSI. Performance: 7.3ms avg frame at 2800+ items.

- **Primitives:** Cell, Style, Buffer (width×height grid), BufferView, diff
- **Composition:** Block.text(), join_horizontal/vertical, pad, border, truncate
- **Components:** list_view, table, text_input, spinner, progress
- **App lifecycle:** RenderApp with update/render/on_key, adaptive sleep, SIGWINCH

### Specs

| File | Role |
|------|------|
| `specs/vm-health.projection.kdl` | Container health fold (upsert + latest) |
| `specs/vm-logs.projection.kdl` | Log line collection (collect + upsert set) |
| `specs/homelab.app.kdl` | App composition (inventory + per-connection uses) |

### Apps

| App | What it does |
|-----|-------------|
| `apps/demo.py` | Progressive walkthrough of render layer |
| `apps/logs.py` | Streaming SSH log viewer |
| `apps/producer.py` | Simulates container events → writes JSONL |
| `apps/tail_dashboard.py` | Tails JSONL → Projection → live dashboard |
| `apps/homelab.py` | **Spec-driven VM dashboard** (simulated events, real inventory) |

**apps/homelab.py** is the spec-driven proof-of-concept: parses KDL specs, loads real inventory from terraform-generated YAML, instantiates projections per connected VM, renders via convention. Currently uses simulated events; real SSH is the next step.

## Broader Ecosystem

| Package | Role | Relationship |
|---------|------|-------------|
| **ev** | Event vocabulary (Event, Result, Emitter protocol) | Defines the typed fact shape |
| **ev-toolkit** | CLI script harness (run, signal, lifecycle) | Producer pattern for scripts |
| **gruel.network/scripts** | Homelab tools (status, logs, media-audit) | Concrete producers |
| **gruel.network/scripts/specs** | `.cli.kdl` specs for script contracts | Inspiration for projection specs |
| **tbd-v2** | Conversation analytics (ingest, FTS5, embeddings) | Cognitive context consumer |
| **experiments/framework** | Stream topology + Tailer + Spec runtime | Routing + persistent consumption + declarative folds |
| **experiments/render** | Cell-buffer TUI | Display consumer |

## What Was Learned

1. **Signals/reaktiv were wrong** — too fine-grained, too coupled, UI-oriented. Version counters + polling do the same job for event streams.

2. **Events are primary, state is derived** — append-only log is the truth. Current state = fold(events). This enables replay, filter, tee.

3. **The file IS the broker** — no need for message infrastructure. JSONL + byte offset = Kafka partition at personal scale. Tailer = consumer with offset tracking.

4. **Render layer was a side discovery** — emerged while replacing Rich. Novel for Python, useful, but orthogonal to the event infrastructure question.

5. **The pattern is universal** — same shape applies to homelab monitoring, work alerting, tool installs, meeting transcripts, research triggers. The "personal event bus" framing unifies them.

6. **KDL specs as projection contracts work** — declaring events, state, and fold ops in KDL produces fully functional projections. The convention-based renderer means no view code needed for common cases. An app is just a collection of specs.

7. **Fold ops cover the mechanical cases** — `upsert`, `collect`, `count`, `latest` handle status dashboards and log viewers without custom Python. Custom folds stay in Python; patterns promote to ops if they repeat.

## Next: Pick Up Here

The spec-driven pipeline is proven end-to-end with simulated events. The next iteration:

1. **Real SSH connections** — Replace `_simulate_events()` in `apps/homelab.py` with persistent SSH subprocesses running `docker compose ps --format json` and `docker compose logs -f`, parsing output into the event shapes declared in the specs.

2. **File watcher for hot-reload** — The `watch true` in the app spec is declared but not implemented. On spec file change: re-parse, diff projections, add/remove panels live.

3. **New projection spec** — Add e.g. `vm-resources.projection.kdl` (CPU/memory from `docker stats`), add `use "vm-resources"` to app spec, see it appear in the dashboard.

4. **FileWriter integration** — Connected VMs should write events to JSONL via FileWriter (one file per VM per projection). Enables: replay on reconnect, cross-process consumption, offline analysis.

## Open Questions

1. **Checkpoint persistence** — Tailer tracks offset in memory. For restart-resilient consumers, offset should persist somewhere (sidecar `.offset` file most likely).

2. **Per-VM vs per-stack granularity** — Current model is per-VM connections. Real gruel.network has multiple docker-compose stacks per VM. Should the app spec model `per-stack` instead?

3. **Custom fold escape hatch** — How does a projection spec reference a Python fold function? `fold { custom "my_module.my_fold" }`? Or is the pattern always: if you need custom, subclass SpecProjection?

## Run

```bash
# Spec-driven homelab dashboard
uv run python -m apps.homelab               # ↑/↓ select, Enter connect/disconnect

# Producer/consumer demo (two terminals)
uv run python -m apps.producer              # writes /tmp/events.jsonl
uv run python -m apps.tail_dashboard        # tails and renders

# Tests
uv run pytest tests/test_spec.py -v         # 13 spec tests, 0.05s
uv run pytest tests/ -v                     # full suite (some async tests need pytest-asyncio)

# Render demos
uv run python -m apps.demo
uv run python -m render.demo_app
```

## See Also

- `CLAUDE.md` — branching, subtask workflow, conventions
- `RETROSPECTIVE.md` — intellectual genealogy, what was proven, the void
- `docs/render-layer.md` — render layer reference
- `docs/genesis.md` — (pending) full narrative history via tbd research
