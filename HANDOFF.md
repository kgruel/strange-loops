# Handoff: Homelab Event Infrastructure

## Lineage

```
hlab (exploration) → experiments (proving ground) → extracted packages
```

- **rill** (`../rill`) — streaming primitives, stdlib only
- **cells** (`../cells`) — cell-buffer TUI, composition-first rendering
- **experiments** — spec layer + orchestrator, the integration testbed

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  rill (stdlib only)                                         │
│  Stream, Projection, EventStore, FileWriter, Tailer         │
│  "Personal Kafka" — the file IS the broker                  │
├─────────────────────────────────────────────────────────────┤
│  experiments/framework                                       │
│  Spec layer: KDL → projection contracts                     │
│  Orchestrator: SSH → collectors → streams → JSONL           │
│  "Homelab as code" — declare what to collect, how to fold   │
├─────────────────────────────────────────────────────────────┤
│  cells                                                       │
│  Buffer → Diff → Writer, Styled blocks, Components          │
│  "Python's missing middle" — between Rich and Textual       │
└─────────────────────────────────────────────────────────────┘
```

## What's Where

| Thing | Location | Status |
|-------|----------|--------|
| Stream, Projection, EventStore, FileWriter, Tailer, Forward | `../rill` | Extracted, stdlib only |
| Cell buffer, diff, styling, components | `../cells` | Extracted |
| KDL spec parsing (ProjectionSpec, AppSpec) | `framework/spec.py`, `app_spec.py` | Here |
| SSH + collectors + orchestrator | `framework/orchestrator.py`, `ssh_session.py`, `collectors/` | Here |
| Homelab dashboard app | `apps/` | Here, uses all three |

## The Spec Layer

The interesting middle piece — not just config, but a **contract language**:

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

- **Event shapes** — input schema, validated + coerced on ingest
- **State shapes** — derived schema, initialized from types
- **Fold ops** — transformation rules (latest, collect, count, upsert)
- **App composition** — which projections, what data sources, inventory

This makes projections declarative. You define the contract, the runtime instantiates typed Projections from rill.

## The Thesis

**Spec-driven data contracts**, not config-driven UI.

- **rill** = primitives (Stream, Projection, Tailer, FileWriter)
- **cells** = rendering (Block, Style, convention-based)
- **spec layer** = contracts (event shapes, state shapes, fold ops)

The spec declares *what data looks like* and *how it transforms*. Rendering is derived from state shapes via conventions (dict→table, list→scrolling). No custom render code per projection.

See `docs/SPEC_DRIVEN.md` for the full conceptual foundation.

## Files

| File | Role |
|------|------|
| `spec.py` | ProjectionSpec, SpecProjection — KDL parser + fold ops |
| `app_spec.py` | AppSpec — composition + inventory + DataSourceSpec |
| `orchestrator.py` | Multi-host collection via Stream/FileWriter |
| `ssh_session.py` | SSHSession — async run() + stream() over SSH |
| `collectors/` | Collector registry + docker collectors |

## Current State

**Implemented:**
- KDL spec parsing (event, state, fold)
- Event validation + type coercion (raises `ValidationError` on mismatch)
- Fold ops: upsert, collect, latest, count
- Hot-reload via SpecWatcher
- Simulator + tail mode working
- 41 tests passing

**Known limitations:**
- Single event type per projection (first iteration, will evolve)
- SSHConnectionManager has hardcoded docker collectors (not using registry)
- No state persistence (memory only)

## Next

**Open questions:**
- Multi-event projections — when/how to support multiple event types
- Collector registry wiring — how specs map to collector functions
- State persistence — snapshot vs replay from event log

**Deferred:**
- Collector registry — wire data_source specs to collector functions
- State snapshots / replay
- SSH connection multiplexing

## Run

```bash
# Dashboard (tail mode)
uv run python apps/simulate_homelab.py    # generate test events
uv run python apps/homelab.py --source /tmp/homelab

# Dashboard (live SSH)
uv run python apps/homelab.py

# Tests
uv run pytest tests/ -v
```

## See Also

- `docs/GROUNDING.md` — how to re-orient, tbd queries, checklist
- `docs/SPEC_DRIVEN.md` — conceptual foundation (spec-driven data contracts)
- `apps/README.md` — homelab app documentation
- `../rill` — core streaming primitives
- `../cells` — cell-buffer TUI package
- `CLAUDE.md` — project conventions
