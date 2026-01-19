# Design Decisions for ev Library

This document captures the key architectural decisions in ev and the reasoning behind them.

## Event System

### Frozen EventKind Set

`EventKind` is a strict Literal type with exactly 5 values:

```python
EventKind = Literal["log", "progress", "artifact", "metric", "input"]
```

**Rationale:**
- These cover the entire domain of CLI output: narrative text (log), ongoing work (progress), produced outputs (artifact), measurements (metric), and user interaction (input).
- Adding a new kind would be a breaking change requiring all emitters to handle it.
- Signals (structured observations) are not a separate kind—they're logs with a `signal` key in data. This avoids proliferating kinds for domain-specific concepts.
- The frozen set enables exhaustive pattern matching in renderers.

### Signals as Convention, Not Primitive

Signals are structured observations emitted via `Event.log_signal()`. They're stored as logs with `data["signal"]` set:

```python
Event.log_signal("status.stack", stack="media", healthy=True)
# Produces: Event(kind="log", data={"signal": "status.stack", "stack": "media", "healthy": True})
```

**Rationale:**
- Adding a sixth EventKind would require updating every emitter.
- Signals are domain-specific; the contract shouldn't enumerate them.
- Detection is simple: `"signal" in event.data`
- `event.topic` returns `signal:<name>` for filtering/routing.

### Immutability via MappingProxyType

Event and Result `data` dicts are wrapped in `MappingProxyType`:

```python
def __post_init__(self) -> None:
    object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
```

**Rationale:**
- Prevents accidental mutation by emitters or downstream code.
- `MappingProxyType` is the standard library's read-only view.
- Combined with `@dataclass(frozen=True)`, events become effectively immutable.
- Original dict is copied, so caller retains their mutable copy.

### JSON-Serializable by Default

All `data` values must be JSON-serializable. No custom types, no dataclasses in data.

**Rationale:**
- Events flow through many systems: emitters, file loggers, network transports.
- JSON is the universal interchange format.
- Serialization should never fail at runtime.
- `to_dict()` and `from_dict()` provide round-trip serialization.

## Result Semantics

### Status/Code Invariants

Result enforces a strict relationship between `status` and `code`:

```python
- status="ok" requires code=0
- status="error" requires code != 0
```

This is validated in `__post_init__`:

```python
if self.status == "ok" and self.code != 0:
    raise ValueError("Result with status='ok' must have code=0")
if self.status == "error" and self.code == 0:
    raise ValueError("Result with status='error' must have non-zero code")
```

**Rationale:**
- CLI tools use exit codes; `status` must be consistent.
- Prevents confusing states like "ok with error code 1".
- Validation at construction catches bugs early.

### Special Exit Codes

Two exit codes have special semantic meaning:

- `10`: Timeout errors - operation exceeded allowed time
- `20`: Authentication errors - authorization/authentication failure

```python
# Timeout example
Result.error("Operation timed out", code=10, data={"timeout_duration": "30s"})

# Authentication error example
Result.error("Authentication failed", code=20, data={"auth_method": "oauth"})
```

**Rationale:**
- Allows automation to distinguish error types without parsing messages.
- Reserved range (10-29) avoids conflicts with common exit codes.
- Specific semantics enable retry logic (retry on timeout, prompt on auth failure).

## Factory Methods

### Prefer Factories Over Constructors

Both Event and Result provide factory methods (`Event.log()`, `Result.ok()`) alongside raw constructors.

```python
# Preferred
Event.log("Starting...")
Result.ok("Done", data={"count": 3})

# Escape hatch
Event(kind="log", message="Starting...")
Result(status="ok", summary="Done")
```

**Rationale:**
- Factories encode common patterns and sensible defaults.
- `Event.log()` sets `kind="log"` automatically.
- `Result.ok()` sets `status="ok"` and `code=0`.
- `Result.error()` defaults `code=1`.
- Raw constructors remain available for testing and edge cases.

## Emitter Protocol

### Minimal Protocol Surface

The Emitter protocol has exactly two methods:

```python
class Emitter(Protocol):
    def emit(self, event: Event) -> None: ...
    def finish(self, result: Result) -> None: ...
```

**Rationale:**
- Emitters are dependency-injected; small interface means easy mocking.
- `emit()` is called 0-N times during execution.
- `finish()` is called exactly once at the end.
- No start/setup method—stateless is simpler.
- Context managers wrap this protocol; the protocol itself doesn't require it.

### ListEmitter for Testing

`ListEmitter` captures events for test assertions:

```python
emitter = ListEmitter()
run_operation(emitter)
emitter.finish(result)
assert len(emitter.events) == 3
assert emitter.result.is_ok
```

**Rationale:**
- Testing event emission is common; built-in support avoids boilerplate.
- Simple list append—no configuration needed.
- Stores both events and result for full inspection.
