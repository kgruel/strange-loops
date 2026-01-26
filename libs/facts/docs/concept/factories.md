# Factory Methods vs Raw Constructors

facts provides two ways to create Events and Results:

1. **Factory methods** (recommended) — the blessed path with guardrails
2. **Raw constructors** — the escape hatch for edge cases

## The Blessed Path: Factory Methods

Factory methods encode best practices and enforce conventions:

```python
# Events
Event.log("Starting server...")
Event.progress("Syncing", step=2, of=5)
Event.artifact("file", "Config saved", path="/tmp/config.json")
Event.metric("duration", 2.3, unit="s")
Event.input("Continue?", response="yes")

# Results
Result.ok("3/3 healthy", data={"stacks": [...]})
Result.error("Connection failed", code=2)
```

### What Factories Provide

| Feature | Factory Behavior |
|---------|------------------|
| **Timestamps** | Auto-populated with `time.time()` |
| **Artifact type** | Required first argument — can't forget it |
| **Result invariants** | `ok` → code=0, `error` → code≠0 (default 1) |
| **Defaults** | Sensible defaults for level, message, etc. |

### Factory Signatures

```python
# Event factories
Event.log(message, *, level="info", ts=None, **data)
Event.progress(message="", *, level="info", ts=None, **data)
Event.artifact(type, message="", *, level="info", ts=None, **data)
Event.metric(name, value, *, unit=None, level="info", ts=None, **data)
Event.input(message, *, response=None, level="info", ts=None, **data)

# Result factories
Result.ok(summary="", *, data=None, meta=None)
Result.error(summary="", *, code=1, data=None, meta=None)
```

## The Escape Hatch: Raw Constructors

Raw constructors bypass factory guardrails. Use them when you need full control:

```python
# Raw Event — you handle everything
Event(
    kind="artifact",
    level="info",
    message="",
    data={"type": "custom", "weird": "stuff"},
    ts=1704200000.0,
)

# Raw Result — you ensure invariants
Result(
    status="error",
    code=42,
    summary="Custom error",
    data={},
    meta={},
)
```

### When to Use Raw Constructors

| Scenario | Why Raw |
|----------|---------|
| **Replaying events** | Need exact original timestamps and data |
| **Testing** | Need deterministic values for assertions |
| **Migration** | Reconstructing from legacy formats |
| **Edge cases** | Factory doesn't fit your specific need |

### Raw Constructor Caveats

- **No auto-timestamp**: You must provide `ts` or accept the default
- **No type enforcement**: Artifact type is just data, not required
- **No invariant checks**: Result status/code consistency is your responsibility
- **More verbose**: All fields must be considered

## Timestamps

Events are timestamped automatically at creation:

```python
event = Event.log("Hello")
print(event.ts)  # 1704200000.123 (current time)
```

Override for replay or testing:

```python
event = Event.log("Hello", ts=1704200000.0)
```

### from_dict() Behavior

When reconstructing from serialized data:

```python
# Original timestamp preserved
Event.from_dict({"kind": "log", "ts": 1704200000.0})  # ts = 1704200000.0

# Missing/null ts → 0.0 sentinel (unknown original time)
Event.from_dict({"kind": "log"})           # ts = 0.0
Event.from_dict({"kind": "log", "ts": None})  # ts = 0.0
```

The `0.0` sentinel (Unix epoch, 1970) is clearly not a real emission time, distinguishing "unknown original" from "created now".

## Result Invariants

Factories enforce status/code consistency:

```python
Result.ok()           # status="ok", code=0
Result.error()        # status="error", code=1
Result.error(code=42) # status="error", code=42
```

Raw constructors require you to maintain invariants:

```python
# Valid
Result(status="ok", code=0)
Result(status="error", code=1)

# Raises ValueError
Result(status="ok", code=1)      # ok must have code=0
Result(status="error", code=0)   # error must have code≠0
```

## Recommendation

**Use factories by default.** They're the blessed path — simpler, safer, and self-documenting.

**Use raw constructors when factories don't fit** — but understand what you're bypassing.

```python
# 99% of the time
Event.artifact("file", path="/tmp/x")
Result.ok("Done")

# Edge cases
Event(kind="artifact", data=legacy_dict, ts=original_ts)
```
