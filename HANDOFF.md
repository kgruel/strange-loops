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

## Key Insight (2026-01-25)

**The dashboard IS the orchestrator.**

Previously: orchestrator runs standalone, writes JSONL; dashboard tails files or uses its own SSH. Two paths that don't share code.

Now: orchestration is a pattern you embed, not infrastructure you deploy. The dashboard runs sources directly, events flow in-memory, persistence is a tap you attach when you want to record.

```
Source → Stream → [Tap: FileWriter] → Projection → Render
              ↑ optional
```

This changes the framing:
- Default is live, not replay
- Recording is a feature, not architecture
- The file is the broker when you want replay; the stream is the broker when you want live

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
- Spec-driven collection: `as=` field maps collector output to event types
- Source protocol in rill (async iterator shape)
- SourceBinding wiring (Source → Stream → Projection, recording as tap)
- SSHConnectionManager collapsed into spec-driven Sources
- 56 tests passing

**Known limitations:**
- Single event type per projection (first iteration)
- No state persistence (memory only)
- Collectors still use manual registry (drop-in pattern designed, not implemented)

## Completed: Collapse SSHConnectionManager (2026-01-25)

Dashboard now embeds orchestration via Source pattern:

```
Source[T] → Stream[T] → Projection → optional FileWriter tap
```

- `Source` protocol in `rill/source.py` (async iterator, stdlib only)
- `TailerSource`, `PollSource`, `StreamSource` in `framework/sources/`
- `SourceBinding` in `framework/binding.py` (wiring + lifecycle)
- `homelab.py` migrated, SSHConnectionManager deleted

See subtask workspace: `~/.subtask/workspaces/-Users-kaygee-Code-experiments--3`

## Designed: Collector Drop-In Pattern (2026-01-25)

**Two paths, one shape:**

1. **`.collector` files** — declarative specs for simple cases
2. **`.py` files** — code when you need logic

```
collectors/
  docker/
    containers.collector   # spec: command + parse + fields
    events.py              # code: streaming with logic
  proxmox/
    vms.py                 # code: API parsing
```

**Spec-defined collector:**
```kdl
collector {
    command "docker ps --format json"
    parse "jsonl"
    mode "collect"
    fields {
        id from="ID"
        name from="Names"
        state from="State"
    }
}
```

**Two contracts:**
- `fields {}` in collector = transform from raw command output
- `EventSpec` in projection = validation contract (the authority)
- `as=` in source spec bridges them

**Errors are events:**
```python
{"type": "source.error", "host": "x", "collector": "y", "error": "timeout"}
```
No special machinery. Fold them or ignore them.

See `docs/COLLECTORS.md` for full design.

## Next: Implement Collector Discovery

1. Implement `.collector` file parser (KDL)
2. Implement discovery (scan dir, load both `.collector` and `.py`)
3. Replace manual `COLLECTORS` registry with discovery
4. Add `source.error` event emission to Sources
5. Test with real homelab collectors

## Deferred

- Multi-event projections
- State snapshots / replay
- SSH connection multiplexing
- Recording UI (tap attach/detach from dashboard)
- Collector parameters (L3)
- Multi-command collectors (L4)

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
- `docs/COLLECTORS.md` — collector design (drop-in pattern, two contracts)
- `docs/COLLAPSED_ARCHITECTURE.md` — Source pattern design
- `apps/README.md` — homelab app documentation
- `../rill` — core streaming primitives
- `../cells` — cell-buffer TUI package
- `CLAUDE.md` — project conventions
