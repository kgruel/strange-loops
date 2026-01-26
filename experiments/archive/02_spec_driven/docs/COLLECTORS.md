# Collectors

Collectors gather data from remote hosts via SSH. They run commands, parse output, and emit structured events.

## Two Paths, One Shape

**Spec-defined** (`.collector` files) — declarative, for simple cases:
```kdl
// collectors/docker/containers.collector
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

**Code-defined** (`.py` files) — for logic, transforms, state:
```python
# collectors/proxmox/vms.py
__collector__ = {"mode": "collect"}

async def collect(ssh: SSHSession) -> list[dict]:
    raw = await ssh.run("pvesh get /cluster/resources --type vm --output-format json")
    data = json.loads(raw)
    return [{"vmid": vm["vmid"], "name": vm["name"], ...} for vm in data]
```

Both register the same way. Discovery scans `collectors/`, loads `.collector` as specs, imports `.py` and reads `__collector__`.

## Collector Responsibilities

1. **Run command(s)** over SSH
2. **Parse output** (text, json, jsonl)
3. **Transform fields** (rename, extract, coerce)
4. **Return dicts** — list for poll, async iterator for stream

Collectors do NOT:
- Know which host they're running on (Source injects context)
- Know the event type (Source maps via `as=`)
- Validate against EventSpec (Projection does that)

## The Two Contracts

### `fields {}` in Collector

Specifies how to transform raw command output into clean events.

```kdl
fields {
    id from="ID"              // rename ID → id
    name from="Names"         // rename Names → name
    cpu from="CPUPerc" as="float"  // rename + coerce
}
```

This is the **output shape** of the collector.

### `EventSpec` in Projection

Specifies what the projection accepts and validates.

```kdl
projection "containers" {
    event "container.status" {
        id "str"
        name "str"
        state "str"
        healthy "bool?"  // optional, defaults if missing
    }
}
```

This is the **input contract** for the projection.

### The Bridge: `as=`

Source connects collector output to event type:

```kdl
source "docker-stack-1" {
    collector "docker.containers"
    as "container.status"
}
```

Flow:
```
Command output → Collector (fields transform) → Source (context injection) →
  → as= mapping → EventSpec validation → Projection fold
```

## Context Injection

Source wraps every event with host context:

```python
# Collector emits
{"id": "abc123", "name": "myapp", "state": "running"}

# Source wraps as
{
    "host": "docker-stack-1",
    "collected_at": 1706198400,
    "id": "abc123",
    "name": "myapp",
    "state": "running"
}
```

Collectors stay portable — same collector works on any host.

## Modes

**`collect` (poll)** — runs periodically, returns `list[dict]`
```kdl
collector {
    mode "collect"
    command "docker ps --format json"
    ...
}
```

**`stream`** — runs continuously, yields events as they arrive
```kdl
collector {
    mode "stream"
    command "docker events --format json"
    ...
}
```

## Error Handling

Errors are events. No special machinery.

When a collector fails (connection, timeout, parse error), Source emits:
```python
{
    "type": "source.error",
    "host": "docker-stack-1",
    "collector": "docker.containers",
    "error": "connection timeout"
}
```

Apps can fold errors into state:
```kdl
projection "source-health" {
    event "source.error" {
        host "str"
        collector "str"
        error "str"
    }
    state { errors "dict" }
    fold { upsert "errors" key="host,collector" }
}
```

Or ignore them — errors don't crash the system, just get logged and skipped.

## File Layout

```
collectors/
  system/
    uptime.collector      # simple text parse
    resources.collector   # multi-value
  docker/
    containers.collector  # poll, jsonl
    events.collector      # stream, jsonl
    stats.py              # needs parsing logic
  proxmox/
    vms.py                # API response parsing
    nodes.collector       # simple jsonl
```

Naming: `{namespace}.{name}` derived from path.
- `collectors/docker/containers.collector` → `docker.containers`
- `collectors/proxmox/vms.py` → `proxmox.vms`

## Levels of Complexity

| Level | What | Example |
|-------|------|---------|
| L0 | One command, text output | `uptime.collector` |
| L1 | JSONL with field mapping | `containers.collector` |
| L2 | Streaming JSONL | `events.collector` |
| L3 | Parameterized command | `collector "x" filter="y"` |
| L5 | Python for complex parsing | `vms.py` |
| L6 | Python with async iterator | `events.py` (debouncing) |

Start simple. Escalate when needed.
