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
| `inventory.py` | HostInfo, load_ansible_inventory — Ansible YAML parser |
| `orchestrator.py` | Multi-host collection via Stream/FileWriter |
| `ssh_session.py` | SSHSession — async run() + stream() + common_args |
| `collectors/` | Collector registry + discovery + docker collectors |
| `collectors/spec.py` | CollectorSpec — KDL parser for .collector files |
| `collectors/discovery.py` | Scan collectors/ for .collector + .py |

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
- Collector discovery: `.collector` KDL + `.py` files scanned from `collectors/`
- `source.error` events emitted on collector failure
- Ansible inventory loader with `common_args` support
- SSHSession wires `common_args` → asyncssh (ProxyJump, Port, etc.)
- 110+ tests passing

**Known limitations:**
- Single event type per projection (first iteration)
- No state persistence (memory only)
- App spec inventory syntax not yet wired (next step)

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

## Completed: Collector Discovery (2026-01-25)

**Drop-in collector pattern implemented:**

- `framework/collectors/spec.py` — `CollectorSpec` dataclass + KDL parser
- `framework/collectors/discovery.py` — scans `collectors/` for `.collector` + `.py`
- Lazy registry via module `__getattr__` (PEP 562)
- `source.error` events on collector failure (PollSource continues, StreamSource stops)
- 27 tests for parser, discovery, error events

Naming: `collectors/docker/containers.collector` → `docker.containers`

## Completed: Inventory + SSH common_args (2026-01-25)

**Ansible inventory integration:**

- `framework/inventory.py` — `HostInfo` dataclass, `load_ansible_inventory()`
- Parses `all.children.{group}.hosts.{name}` structure
- Extracts `ansible_ssh_common_args` from `all.vars`
- `VMInfo = HostInfo` alias for backward compat

**SSHSession extension:**

- `common_args: str` field parsed via `shlex.split()`
- Supports `-J jump_host`, `-o ProxyJump=`, `-p port`, `-o Port=`
- Wired to `asyncssh.connect(**kwargs)`

## Next: App Spec Inventory Syntax

Wire inventory into app spec so dashboard auto-discovers hosts:

```kdl
app "homelab" {
    inventory from="ansible" path="~/Code/gruel.network/ansible/inventory.yml"

    per-connection {
        use "vm-health"
        collect "docker.containers" as="container.status" into="vm-health"
    }
}
```

Subtask drafted: `app-spec-inventory` (blocked on merged tasks, now unblocked)

## What Inventory Unlocks

**Progressive enhancement path:**

1. **Host autodiscovery** — dashboard iterates `app_spec.hosts`, no hardcoded VMs
2. **Group filtering** — `inventory ... groups="vms"` to select subset
3. **Per-host collectors** — different collectors for different service_types
4. **Multi-inventory** — combine Ansible + static KDL for dev/prod split
5. **Dynamic refresh** — watch inventory file, add/remove hosts at runtime

**User experiences enabled:**

| Feature | What it means |
|---------|---------------|
| Zero-config onboarding | Point at existing Ansible inventory, dashboard works |
| Proxy jump support | SSH through bastion hosts via `common_args` |
| Service-aware views | Group containers by `service_type` in UI |
| Inventory-as-code | Git-tracked host config, Terraform-generated |

## Deferred

- Multi-event projections
- State snapshots / replay
- SSH connection multiplexing
- Recording UI (tap attach/detach from dashboard)
- Collector parameters (L3)
- Multi-command collectors (L4)
- Inventory groups filtering
- Dynamic inventory refresh

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
