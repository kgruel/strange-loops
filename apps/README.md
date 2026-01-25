# Homelab Dashboard

Spec-driven VM monitoring dashboard. Connects to VMs via SSH, runs docker commands, folds output into projections, renders live.

## Run

```bash
# Live SSH (connects to real VMs)
uv run python apps/homelab.py

# Tail mode (reads JSONL files, for testing)
uv run python apps/simulate_homelab.py   # generate fake events
uv run python apps/homelab.py --source /tmp/homelab
```

## Conceptual Model

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  VM (via SSH)   │────▶│   Projection    │────▶│     Render      │
│  docker ps/stats│     │   fold events   │     │   cells TUI     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Core assumption:** A projection is a fold over an event stream. Events have a shape (declared in spec). State has a shape (declared in spec). Fold ops transform events into state updates.

## What Actually Runs

When you connect to a VM, three SSH subprocesses spawn:

| Task | Command | Interval | Projection |
|------|---------|----------|------------|
| Health poller | `docker ps --format json` | 5s | vm-health |
| Log streamer | `docker events --format json` | continuous | vm-events |
| Resources poller | `docker stats --no-stream --format json` | 5s | vm-resources |

Each subprocess:
1. Runs the docker command over SSH
2. Parses JSON output into event dicts
3. Calls `proj.consume(event)` to fold into state
4. Projection version bumps, triggering re-render

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

## Architecture Assumptions

### 1. File is the broker (tail mode)

In `--source` mode, JSONL files are the transport:
```
/tmp/homelab/
  media/
    vm-health.jsonl      # one event per line
    vm-events.jsonl
    vm-resources.jsonl
  infra/
    ...
```

`Tailer` reads with byte-offset tracking. No external broker needed.

### 2. Projection is the primitive

From `rill`:
```python
class Projection[S, T]:
    def apply(self, state: S, event: T) -> S: ...
    async def consume(self, event: T) -> None: ...

    @property
    def state(self) -> S: ...
    @property
    def version(self) -> int: ...  # bumps on state change
```

`SpecProjection` extends this with declarative fold ops parsed from KDL.

### 3. Specs declare contracts

Event shapes and fold semantics are declared, not coded:
- **Event spec** → input schema (currently not validated at runtime)
- **State spec** → derived schema, initialized from types
- **Fold ops** → transformation rules

### 4. Render is convention-based

`spec_render.py` maps state shapes to UI:
- `dict` field → table
- `list` field → scrolling list
- `set` field → tag row

No custom rendering code per projection.

## Current Limitations

### Hardcoded collectors

`SSHConnectionManager` has docker commands baked in. The collector registry (`framework/collectors/`) exists but isn't used. To add a new data source, you'd currently edit `ssh.py`.

**Future:** Wire data_source specs to collector registry so new sources are declarative.

### No event validation

Specs declare event shapes but `SpecProjection.consume()` doesn't validate. Malformed events silently produce bad state.

**Future:** Validate on ingest, reject or log violations.

### Memory-only projections

State lives in-memory. Disconnect and it's gone. No snapshots, no replay from JSONL.

**Future:** Snapshot/restore, or replay from FileWriter output.

### SSH subprocess per command

Each poller spawns a new SSH process. For 8 VMs × 3 collectors = 24 subprocesses.

**Future:** Multiplex over single SSH connection per VM.

## Code Map

```
apps/
  homelab.py          # main app, RenderApp subclass
  simulate_homelab.py # fake event generator for testing

framework/
  ssh.py              # SSHConnectionManager (hardcoded collectors)
  spec.py             # ProjectionSpec, SpecProjection, fold ops
  app_spec.py         # AppSpec, VMInfo, inventory loading
  spec_render.py      # projection → Block conventions
  collectors/         # collector registry (unused by homelab)

specs/
  homelab.app.kdl
  vm-health.projection.kdl
  vm-events.projection.kdl
  vm-resources.projection.kdl
```

## Dependencies

- **rill** — `Tailer`, `Projection`, `FileWriter` (stdlib only)
- **cells** — `RenderApp`, `Block`, `Style`, composition
- **framework** — spec parsing, SSH, orchestration
