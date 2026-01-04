# Layered Natural Docstring Style

Docstring format for LLM consumption that provides structure without triggering formal verification mode.

## Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Descriptive, not prescriptive** | `Behavior:` invites understanding; `Contract:` demands verification |
| **Semantic anchors** | Labels create attention targets for quick scanning |
| **Negative constraints** | `Instead:` guides choice more effectively than positive explanation |
| **Code-like facts** | `topic="log"` reads as constant, not rule to parse |

## The Format

```
"""One-line semantic description.

Behavior: Guarantees and characteristics. topic="..."
Use for: When to reach for this.
Instead: What to use for other cases.
"""
```

## Factory Method Docstrings

### Event.log

```python
def log(cls, message: str, ...) -> Self:
    """Narrative log for humans.

    Behavior: Idempotent. No side effects. topic="log"
    Instead: Use log_signal() for structured/machine-readable data.
    """
```

### Event.log_signal

```python
def log_signal(cls, name: str, ...) -> Self:
    """Structured observation for machines. Renderers format distinctly from prose.

    Behavior: Idempotent. topic="signal:{name}"
    Use for: Telemetry, state changes, key-value pairs.
    Instead: Use log() for human narrative.
    """
```

### Event.progress

```python
def progress(cls, message: str = "", ...) -> Self:
    """Advancement update during long operations.

    Behavior: Idempotent. topic="progress"
    Data: step/of for discrete, percent for continuous, phase for stages.
    Instead: Use log() for one-off status messages.
    """
```

### Event.artifact

```python
def artifact(cls, type: str, ...) -> Self:
    """Durable output or discovery worth surfacing to tooling.

    Behavior: Idempotent. topic="artifact:{type}"
    Use for: Files, record IDs, URLs, resources.
    """
```

### Event.metric

```python
def metric(cls, name: str, value: Any, ...) -> Self:
    """Named measurement for aggregation or display.

    Behavior: Idempotent. topic="metric"
    Use for: Durations, counts, sizes, rates.
    Data: name, value, optional unit (s, ms, bytes, etc.)
    """
```

### Event.input

```python
def input(cls, message: str, ...) -> Self:
    """Record of user prompt and response.

    Behavior: Idempotent. topic="input"
    Use for: Audit trail of interactive decisions.
    Data: response contains user's answer if captured.
    """
```

### Result.ok

```python
def ok(cls, summary: str = "", ...) -> Self:
    """Success outcome. Emit exactly once at the end of execution.

    Values: status="ok", code=0
    Summary: Short human-readable sentence ("Deployed 3 stacks").
    Data: Structured dictionary for automation consumption.
    """
```

### Result.error

```python
def error(cls, summary: str = "", ...) -> Self:
    """Failure outcome. Emit exactly once at the end of execution.

    Values: status="error", code!=0 (default 1)
    Summary: Short human-readable sentence ("Connection refused").
    Data: Structured error details for automation.
    """
```

## Why This Works

1. **`topic="..."`** - Looks like code/assignment, treated as fact not rule
2. **`Behavior:`** - Signals "how it acts" not "the law"
3. **`Instead:`** - Routing guardrail preventing common misuse
4. **`Use for:`** - Positive guidance when alternatives aren't the issue
5. **One-line semantic** - Immediate understanding before details

## Comparison to Experiment 1

| Aspect | Experiment 1 (Contract:) | Layered Natural |
|--------|--------------------------|-----------------|
| Tone | Formal specification | Senior engineer commentary |
| Effect on Opus/Sonnet | Triggered verification (+84% tools) | Expected: guidance without paralysis |
| Scannability | Key-value parsing required | Labeled sections, natural reading |
| Choice guidance | Implicit | Explicit via `Instead:` |
