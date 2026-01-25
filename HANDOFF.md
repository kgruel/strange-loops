# Handoff: Homelab Event Infrastructure

## The Concept

This repo experiments with **personal-scale event infrastructure** — Kafka concepts at homelab scale. The core primitives now live in [rill](../rill), a separate package.

```
Typed fact → Append-only log → Derived views (projections)
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  rill (separate package)                                │
│  Stream, Projection, EventStore, FileWriter, Tailer    │
│  The "personal kafka" primitives. Stdlib only.         │
├─────────────────────────────────────────────────────────┤
│  framework/ (this repo)                                 │
│  Spec layer: KDL parsing, projection specs, app specs  │
│  SSH layer: SSHSession, collectors, orchestration      │
│  Uses rill primitives to build homelab monitoring      │
├─────────────────────────────────────────────────────────┤
│  Display (separate package)                             │
│  ~/Code/cells — cell-buffer TUI engine                 │
└─────────────────────────────────────────────────────────┘
```

## rill Primitives

| Primitive | Role |
|-----------|------|
| `Stream[T]` | Typed async fan-out |
| `EventStore[T]` | Append-only log with optional JSONL persistence |
| `Projection[S,T]` | Incremental fold (materialized view) |
| `FileWriter[T]` | JSONL persistence (consumer) |
| `Tailer[T]` | JSONL reader with byte-offset tracking |
| `Forward[T,U]` | Stream-to-stream bridge with transform |

## This Repo: Spec + Orchestration

### Spec Layer

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

### App Composition

```kdl
app "homelab" {
    inventory "~/Code/gruel.network/ansible/inventory.yml"
    per-connection {
        collect "docker:containers" into="vm-health" interval=5
        stream "docker:events" into="vm-events"
    }
}
```

### Orchestration

```
SSHSession.run(cmd) → collector parses → stream.emit(event) → FileWriter persists
```

**Collectors:**
- `docker:containers` — poll `docker ps`, emit container status
- `docker:events` — stream `docker events`, emit lifecycle events
- `docker:stats` — poll `docker stats`, emit resource usage

## Files

| File | Role |
|------|------|
| `spec.py` | ProjectionSpec, SpecProjection — KDL parser + fold ops |
| `app_spec.py` | AppSpec — composition + inventory + DataSourceSpec |
| `spec_render.py` | Convention-based state→component mapping |
| `ssh_session.py` | SSHSession — async run() + stream() over SSH |
| `orchestrator.py` | Multi-host collection via Stream/FileWriter |
| `collectors/` | Collector registry + docker collectors |
| `watcher.py` | Mtime-polling file watcher with debounce |

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

- `~/Code/rill` — core streaming primitives
- `~/Code/cells` — cell-buffer TUI package
- `CLAUDE.md` — project conventions
