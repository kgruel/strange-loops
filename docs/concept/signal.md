# Signals (Structured Observations)

Signals are structured, machine-readable observations within the log event kind.

## Two Lanes Within Log

The `log` kind serves two distinct purposes:

### Lane 1: Narrative Logs

Human-first prose, not reliably machine-parseable.

```python
Event.log("Connecting to server...")
Event.log("Retrying in 5 seconds", level="warn")
Event.log("Skipping optional checks")
```

**Rules:**
- May contain prose
- May be suppressed freely (`--quiet`)
- Not stable for parsing (wording can change)
- `data` allowed but optional, informational only

### Lane 2: Signals (Structured Observations)

Machine-meaningful, stable identifiers with structured attributes.

```python
Event.log_signal("stack_status", stack="media", healthy=True)
Event.log_signal("connection_established", host="db.local", port=5432)
Event.log_signal("cache_invalidated", key="user:123")
```

**Rules:**
- Must have a stable signal name (identifier)
- `data` must be structured attributes
- `message` is optional and non-authoritative (display-only)
- Signals should be safe to filter, group, and format consistently

## How Renderers Detect Signals

Signals are stored as logs with a `"signal"` key in data:

```python
# Created via:
Event.log_signal("stack_status", stack="media", healthy=True)

# Produces:
Event(kind="log", data={"signal": "stack_status", "stack": "media", "healthy": True})
```

Renderers can distinguish signals from narrative logs:

```python
def emit(self, event: Event) -> None:
    if event.is_signal:
        # Structured observation - interpret data
        name = event.signal_name
        ...
    elif event.kind == "log":
        # Narrative - display message as-is
        ...
```

## Signal Naming Conventions

Signal names should be stable identifiers, not sentences.

**Format:**
- Lowercase snake_case: `connection_established`
- Scope prefix if needed: `deploy.stack_status`
- Versioning only if truly breaking: `stack_status_v2` (rare)

**Good:**
- `stack_status`
- `cache_invalidated`
- `service_restarted`
- `deploy.rollback_started`

**Bad:**
- `Stack status changed` (sentence, not identifier)
- `stackStatus` (camelCase)
- `STACK_STATUS` (screaming case)

## Signal Attribute Guidelines

Signal attributes should be structured, JSON-serializable values.

**Good attributes:**
- `healthy=True` — boolean state
- `stack="media"` — string identifier
- `attempt=2` — count (when not a metric)
- `tags=["prod", "critical"]` — list of values

**Use other primitives instead:**
- `duration=2.3` → use `Event.metric("duration", 2.3, unit="s")`
- `path="/tmp/out.txt"` → use `Event.artifact("file", path=...)` if it was produced
- `percent=50` → use `Event.progress(percent=50)`

**Avoid:**
- Deep nesting (keep it flat)
- Large blobs (if it's big, it's an artifact)
- Numbers that should be graphed/compared (use metric)

## Four Primitives First Rule

Before using `log_signal`, check if another primitive fits better:

| If it's... | Use |
|------------|-----|
| A durable output (file, report, etc.) | `artifact` |
| A number you'd graph or compare | `metric` |
| Advancement toward completion | `progress` |
| A human decision | `input` |
| None of the above | `log_signal` |

Signals are for **state facts** — observations about what's happening that don't fit the special-purpose primitives.

## Renderer Treatment

### Rich / Plain Emitters

- Signals can be rendered tersely, grouped, or collapsed
- Consistent formatting: `stack_status: media healthy=true`
- Can show only at `-v` (verbose) if desired

### JSON Emitter

- Signals are structured facts for downstream consumers
- Can choose to output only signals in JSONL mode for tooling

### Live Displays

Signals drive live UI updates:

```python
class StackLiveEmitter:
    def emit(self, event: Event) -> None:
        if event.signal_name == "stack_status":
            stack = event.data.get("stack")
            healthy = event.data.get("healthy")
            self._update_tree(stack, healthy)
```

### Auditing / Replay

Signals become the "timeline of domain events" — a structured record of what happened, suitable for replay or analysis.

## Why Not a Separate Primitive?

We considered adding `signal` as a 6th EventKind. We chose to keep it within `log` because:

1. **Primitives stay frozen** — extension via convention, not new types
2. **Signals and logs share a property** — both are transient information about "what's happening now"
3. **Reversible** — if this proves awkward, we can add a Signal primitive later
4. **Rules prevent sprawl** — the "four primitives first" rule keeps signals in their lane

The `log_signal` factory provides a clean API while maintaining the minimal primitive set.
