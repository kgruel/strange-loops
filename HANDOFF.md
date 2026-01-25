# Handoff: Personal Event Infrastructure

## The Concept

**Personal-scale event infrastructure** — Kafka concepts (append-only logs, offset-tracking consumers, materialized views) at individual/homelab scale, using files instead of brokers.

```
Typed fact → Append-only log → Derived views (projections)
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Producers                                               │
│  Collectors (via SSH), scripts, hooks — emit facts       │
│  Write via: stream.emit() → FileWriter                   │
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
│  Spec Layer                                              │
│  .projection.kdl — declares events, state, fold ops      │
│  .app.kdl — composes projections, binds collectors       │
└─────────────────────────────────────────────────────────┘
```

**Two paths, same Projection interface:**

- **In-process** — Stream[T] fans out to consumers in the same event loop
- **Persistent** — FileWriter writes JSONL, Tailer reads with offset tracking

## Current State

### Framework (`framework/`)

| File | Role |
|------|------|
| `stream.py` | Stream[T] — typed async fan-out |
| `projection.py` | Projection[S,T] — fold events → state + version |
| `store.py` | EventStore[T] — in-memory append-only log |
| `file_writer.py` | FileWriter[T] — JSONL persistence (with optional validation) |
| `tailer.py` | Tailer[T] — JSONL reader with offset tracking |
| `forward.py` | Forward[T,U] — bridge between typed streams |
| `spec.py` | SpecProjection — KDL parser + declarative fold ops + validation |
| `app_spec.py` | AppSpec — composition parser + inventory + DataSourceSpec |
| `spec_render.py` | Convention-based state→component mapping |
| `ssh_session.py` | SSHSession — async run() + stream() over SSH |
| `collectors/` | Collector registry + docker collectors |
| `orchestrator.py` | Multi-host collection via Stream/FileWriter |
| `watcher.py` | Mtime-polling file watcher with debounce |

### Orchestration Layer (New)

The orchestrator composes framework primitives:

```
SSHSession.run(cmd) → collector parses → stream.emit(event) → FileWriter persists
```

**Key abstractions:**
- `DataSourceSpec` — collector → projection binding (`collect "docker:containers" into="vm-health" interval=5`)
- `HostStream` — bundles Stream + FileWriter + Tap for a host+projection pair
- `Orchestrator` — manages streams per host, handles graceful shutdown

**Collectors:**
- `docker:containers` — poll `docker ps`, emit container status
- `docker:events` — stream `docker events`, emit lifecycle events
- `docker:stats` — poll `docker stats`, emit resource usage

### Spec-Driven Projections

KDL specs as projection contracts:

```kdl
projection "vm-health" {
    event "container.status" {
        container "str"
        state "str"
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

**Fold ops:** `latest`, `collect`, `count`, `upsert`

**App composition:**

```kdl
app "homelab" {
    inventory "~/Code/gruel.network/ansible/inventory.yml"
    per-connection {
        collect "docker:containers" into="vm-health" interval=5
        stream "docker:events" into="vm-events"
    }
}
```

### Display (separate package)

The render layer lives in `~/Code/cells` — cell-buffer TUI engine. This repo depends on it via path dependency.

## What Was Learned

1. **Events are primary, state is derived** — append-only log is truth. State = fold(events).

2. **The file IS the broker** — JSONL + byte offset = Kafka partition at personal scale.

3. **Collectors emit to streams, persistence is a tap concern** — separation means collectors don't know about files.

4. **KDL specs as contracts work** — declare events, state, fold ops → get working projections.

5. **Convention-based rendering** — dict→table, list→list_view, set→tags, scalar→label.

## Next: Framework Cleanup

Focus areas:
- Clean up module boundaries
- Remove dead code paths
- Ensure consistent patterns across primitives
- Tests for orchestration layer

## Run

```bash
# Orchestrator (collection)
uv run python -m framework.orchestrator --spec specs/homelab.app.kdl --output /tmp

# Simulated producer
uv run python -m apps.simulate_homelab

# Homelab dashboard (requires cells package)
uv run python -m apps.homelab --source /tmp/homelab

# Tests
uv run pytest tests/ -v
```

## See Also

- `CLAUDE.md` — project conventions
- `framework/README.md` — streaming topology reference
- `~/Code/cells` — cell-buffer TUI package
