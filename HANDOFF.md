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

- **Event shapes** — input schema, validated on ingest
- **State shapes** — derived schema, initialized from types
- **Fold ops** — transformation rules (latest, collect, count, upsert)
- **App composition** — which projections, what data sources, inventory

This makes projections declarative. You define the contract, the runtime instantiates typed Projections from rill.

## The Thesis

**rill** = primitives (what), **cells** = display (how to show), **spec layer** = contracts (what shape, how to fold)

The homelab is the real testbed that proves all three compose into something useful.

## Files

| File | Role |
|------|------|
| `spec.py` | ProjectionSpec, SpecProjection — KDL parser + fold ops |
| `app_spec.py` | AppSpec — composition + inventory + DataSourceSpec |
| `orchestrator.py` | Multi-host collection via Stream/FileWriter |
| `ssh_session.py` | SSHSession — async run() + stream() over SSH |
| `collectors/` | Collector registry + docker collectors |

## Run

```bash
# Orchestrator (collection)
uv run python -m framework.orchestrator --spec specs/homelab.app.kdl --output /tmp

# Tests
uv run pytest tests/ -v
```

## Next

Focus areas to consider:
1. **Spec layer** — event validation, type generation, richer fold ops
2. **Orchestrator** — real collection from homelab VMs
3. **Integration** — spec-driven dashboard with cells rendering projection state

## See Also

- `../rill` — core streaming primitives
- `../cells` — cell-buffer TUI package
- `ROADMAP.md` — detailed phased plan
- `CLAUDE.md` — project conventions
