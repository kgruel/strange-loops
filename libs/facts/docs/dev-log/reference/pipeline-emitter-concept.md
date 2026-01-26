# Pipeline Emitter Concept

*Reference: Captured from discussion on 2026-01-03, post v0.5.0 release.*

## Context

After implementing uniform context protocol (v0.5.0), explored whether a formal "pipeline emitter" abstraction would reduce composition complexity observed in hlab.

## The Idea

Declarative composition instead of manual nesting:

```python
# Current (manual nesting):
counter = HealthCounter(VerbosityFilter(TeeEmitter(console, file), level=1))

# Hypothetical pipeline:
emitter = (
    Pipeline(console, file)
    .filter(verbosity=1)
    .count(is_healthy)
    .build()
)
```

## Pain Points Observed in hlab

| Pain Point | Location | Nature |
|------------|----------|--------|
| Nested context managers | `deploy.py:112-148` | FileEmitter + Live need manual nesting |
| Mode branching in composition | `deploy.py`, `status.py` | RICH vs others have different wiring |
| Wrapper boilerplate | `ssh.py:114-160` | Every wrapper repeats `__init__(inner)`, delegation |
| Verbosity scattered | Multiple emitters | Each checks `self.verbosity` independently |

### Code Examples (hlab)

**TeeEmitter composition** (`deploy.py`):
```python
with FileEmitter(self.log_file) as file_emitter:
    tee = TeeEmitter(display_emitter, file_emitter)
    if mode == OutputMode.RICH:
        with display_emitter:
            result = await deploy_stack_with_emitter(stack_obj, tee, ...)
            tee.finish(result)
    else:
        result = await deploy_stack_with_emitter(stack_obj, tee, ...)
        tee.finish(result)
```

**Counting wrapper** (`ssh.py`):
```python
class _CountingEmitter:
    def __init__(self, inner: Emitter) -> None:
        self._inner = inner
        self.healthy_count = 0
        self.total_count = 0

    def emit(self, event: Event) -> None:
        if event.is_signal and event.signal_name == "status.stack":
            self.total_count += 1
            if event.data.get("status") == "healthy":
                self.healthy_count += 1
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        self._inner.finish(result)
```

## Analysis

### ev's Design Rule

> Only add a primitive if a renderer capability cannot be reliably implemented without it.

### Arguments Against (core)

1. **Manual nesting works.** Verbose, not impossible.
2. **Pipeline is framework territory.** "How to wire emitters" is framework, not contract.
3. **Stages are domain-specific.** What you filter/count/tee differs per CLI.
4. **Context protocol (v0.5.0) reduces the pain.** Asymmetric `with` handling is now gone.

### Arguments For (ev-toolkit)

1. **Boilerplate reduction is real.** Every wrapper has same shape.
2. **Common wrappers exist.** VerbosityFilter already in recipes.
3. **Composition helper is minimal.** A 5-line function isn't machinery.

## Decision

**Don't add Pipeline to ev core.** Violates design rule.

**Potential ev-toolkit additions (not yet implemented):**

```python
# Base class for wrappers
class WrappingEmitter:
    """Base for emitters that wrap another emitter."""

    def __init__(self, inner: Emitter) -> None:
        self.inner = inner

    def emit(self, event: Event) -> None:
        self.inner.emit(event)

    def finish(self, result: Result) -> None:
        self.inner.finish(result)

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        self.inner.__exit__(*args)

# Simple compose helper
def compose(terminal: Emitter, *wrappers) -> Emitter:
    """Wrap terminal with wrappers, applied right-to-left."""
    result = terminal
    for wrapper in reversed(wrappers):
        result = wrapper(result)
    return result
```

## Documentation Opportunity

The existing `aggregating-emitter.md` pattern doc shows composition briefly:

```python
# Log events → Count → Render
logged = LoggingEmitter(rich_emitter)
counted = HealthCountingEmitter(logged)
```

Could expand with:
- Explicit "Composing Wrappers" section
- More examples of wrapper stacking
- Context manager considerations (now simpler with v0.5.0)
- Common wrapper patterns (filter, count, log, tee)

## Status

Parked. Revisit when:
- More wrapper patterns emerge in practice
- Documentation feels incomplete for composition
- ev-toolkit sees broader adoption

## Related

- `docs/patterns/aggregating-emitter.md` — Current wrapper documentation
- `docs/patterns/command-context.md` — Factory pattern for mode-based emitter creation
- `src/ev/emitters/tee.py` — Fan-out composition primitive
