# Homelab Dashboard

Spec-driven VM monitoring with embedded orchestration. The dashboard IS the orchestrator — live connection is the default, recording is opt-in.

## Run

```bash
# Live SSH (connects to real VMs)
uv run python apps/homelab.py

# Replay mode (reads recorded JSONL files)
uv run python apps/simulate_homelab.py   # generate fake events
uv run python apps/homelab.py --source /tmp/homelab
```

## Conceptual Model

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Source    │────▶│   Stream    │────▶│  Projection │────▶│   Render    │
│ (SSH, file) │     │  (fan-out)  │     │   (fold)    │     │   (cells)   │
└─────────────┘     └──────┬──────┘     └─────────────┘     └─────────────┘
                          │
                          ▼ (opt-in tap)
                   ┌─────────────┐
                   │ FileWriter  │
                   │ (recording) │
                   └─────────────┘
```

**The thesis:** The dashboard embeds orchestration. Persistence is a tap you attach when you want to record, not architecture you deploy separately.

**Core primitives:**
- **Source** — produces events (SSH collector, file tailer, simulator)
- **Stream** — typed async fan-out to consumers
- **Projection** — fold events into derived state
- **FileWriter** — optional persistence tap

## Operating Modes

### Live Mode (default)

Dashboard connects directly to sources, events flow in-process:

```
SSH Source ──▶ Stream ──▶ Projection ──▶ Render
                  │
                  └──▶ FileWriter (if recording enabled)
```

### Replay Mode (`--source`)

Dashboard tails recorded files, same projection logic:

```
Tailer ──▶ Stream ──▶ Projection ──▶ Render
```

### Recording (future)

User triggers from dashboard: "start recording" attaches FileWriter tap. Events persist AND feed projections. Stop recording detaches the tap.

## What Actually Runs

When you connect to a VM, data sources from the spec execute:

| Data Source | Command | Mode | Event Type |
|-------------|---------|------|------------|
| `docker:containers` | `docker ps --format json` | poll (5s) | `container.status` |
| `docker:events` | `docker events --format json` | stream | `docker.event` |
| `docker:stats` | `docker stats --no-stream --format json` | poll (5s) | `container.stats` |

Each source:
1. Runs collector function (SSH command, parse output)
2. Maps to declared event type (`as=` in spec)
3. Emits to Stream
4. Projection taps stream, folds event, bumps version
5. Render loop detects version change, re-renders

## Specs

### App Spec (`specs/homelab.app.kdl`)

```kdl
app "homelab" {
    watch true                                    // hot-reload on spec changes
    inventory "~/Code/gruel.network/ansible/inventory.yml"

    per-connection {
        use "vm-health"
        use "vm-events"
        use "vm-resources"
    }
}
```

### Projection Spec (`specs/vm-health.projection.kdl`)

```kdl
projection "vm-health" {
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

**Reading this:** Events of type `container.status` with those fields fold into state via `upsert` (dict keyed by container name) and `latest` (timestamp tracking).

## Architecture

### 1. Stream is the broker (live), File is the broker (replay)

**Live mode:** Stream is the in-process broker. Events flow directly from source to projection.

**Replay mode:** JSONL files are the broker. Tailer reads with byte-offset tracking.

```
/tmp/homelab/
  media/
    vm-health.jsonl      # one event per line
    vm-events.jsonl
  infra/
    ...
```

Same projection logic, different source. The broker choice is a runtime decision.

### 2. Embedded orchestration

The dashboard doesn't shell out to an orchestrator. It IS the orchestrator:

```python
# Conceptually (collapsed architecture)
for source_spec in app_spec.data_sources:
    source = make_source(source_spec, vm)     # SSHSource, TailerSource, etc.
    stream = Stream()
    projection = SpecProjection(source_spec.projection)
    stream.tap(projection)
    # optional: stream.tap(FileWriter(...)) for recording
    asyncio.create_task(run_source(source, stream))
```

No separate process. No file-based coordination. Events flow in-memory.

### 3. Persistence is a tap, not architecture

Recording is opt-in:
- Default: events flow source → stream → projection (memory only)
- Recording: attach `FileWriter` tap, events persist AND feed projection
- Stop recording: detach tap, back to memory only

The user decides when to record, from the dashboard.

### 4. Specs declare contracts

Event shapes and fold semantics are declared, not coded:
- **Event spec** → input schema, validated on ingest
- **State spec** → derived schema, initialized from types
- **Fold ops** → transformation rules (upsert, collect, latest, count)
- **Data sources** → collector + event type mapping (`as=`)

### 5. Render is convention-based

`spec_render.py` maps state shapes to UI:
- `dict` field → table
- `list` field → scrolling list
- `set` field → tag row

No custom rendering code per projection.

## Current State

### Done
- Spec-driven collection: `as=` field maps collector output to event types
- Event validation with type coercion
- Orchestrator uses DataSourceSpec from app spec
- Fold ops: upsert, collect, latest, count

### In Progress: Collapse SSHConnectionManager

Currently two SSH paths exist:
- `SSHConnectionManager` — hardcoded collectors, callback-based (used by dashboard)
- `Orchestrator` — spec-driven, Stream-based (standalone CLI)

**Target:** One path. Dashboard embeds orchestrator-style collection.

### Future

**Recording from dashboard** — UI to attach/detach FileWriter taps at runtime.

**SSH multiplexing** — single connection per VM instead of subprocess per collector.

**State snapshots** — persist projection state for fast restart.

## Code Map

```
apps/
  homelab.py          # main app, embeds orchestration
  simulate_homelab.py # fake event generator for testing

framework/
  orchestrator.py     # spec-driven collection, Stream-based
  ssh_session.py      # SSHSession (asyncssh wrapper)
  ssh.py              # SSHConnectionManager (to be replaced)
  spec.py             # ProjectionSpec, SpecProjection, fold ops
  app_spec.py         # AppSpec, DataSourceSpec, inventory
  spec_render.py      # projection → Block conventions
  collectors/         # collector registry + implementations

specs/
  homelab.app.kdl
  vm-health.projection.kdl
  vm-events.projection.kdl
  vm-resources.projection.kdl
```

## Package Boundaries

```
ticks (stdlib only)
├── Stream, Tap        — typed async fan-out
├── Projection         — incremental fold
├── FileWriter         — JSONL persistence
├── Tailer             — byte-offset reader
└── Forward            — stream bridging

cells (stdlib + wcwidth)
├── Buffer, Diff       — cell-level rendering
├── Block, Style       — composable layout
└── RenderApp          — event loop + render

framework (ticks + cells + IO)
├── Spec parsing       — KDL → contracts
├── SpecProjection     — declarative fold ops
├── Sources            — SSH, collectors
└── Orchestration      — wire sources to projections

apps (everything)
└── Dashboard          — orchestration + rendering
```
